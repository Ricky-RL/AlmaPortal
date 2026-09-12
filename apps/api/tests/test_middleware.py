from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from starlette.middleware.cors import CORSMiddleware

from alma_api.infrastructure import InMemoryRateLimiter, RateLimitExceeded
from alma_api.middleware import (
    BodyCapMiddleware,
    ClientIpResolver,
    InvalidClientAddress,
    PublicSubmissionRateLimitMiddleware,
)

Message = dict[str, Any]


def scope(
    *,
    headers: list[tuple[bytes, bytes]] | None = None,
    client: str = "203.0.113.7",
) -> dict[str, Any]:
    return {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/leads",
        "headers": headers or [],
        "client": (client, 1234),
    }


@pytest.mark.asyncio
async def test_declared_oversize_is_rejected_before_receive_or_parse() -> None:
    called = False
    received = False
    sent: list[Message] = []

    async def app(_: dict[str, Any], __: object, ___: object) -> None:
        nonlocal called
        called = True

    async def receive() -> Message:
        nonlocal received
        received = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    await BodyCapMiddleware(app, max_bytes=4)(
        scope(headers=[(b"content-length", b"5")]),
        receive,
        send,
    )
    assert not called
    assert not received
    assert sent[0]["status"] == 413


@pytest.mark.asyncio
async def test_chunked_body_without_content_length_is_counted() -> None:
    chunks = iter(
        [
            {"type": "http.request", "body": b"123", "more_body": True},
            {"type": "http.request", "body": b"456", "more_body": False},
        ]
    )
    sent: list[Message] = []

    async def receive() -> Message:
        return next(chunks)

    async def send(message: Message) -> None:
        sent.append(message)

    async def app(
        _: dict[str, Any],
        wrapped_receive: Callable[[], Awaitable[Message]],
        __: object,
    ) -> None:
        await wrapped_receive()
        await wrapped_receive()

    await BodyCapMiddleware(app, max_bytes=5)(scope(), receive, send)
    assert sent[0]["status"] == 413


def test_untrusted_peer_cannot_spoof_forwarded_for() -> None:
    resolver = ClientIpResolver(("10.0.0.0/8",))
    request_scope = scope(
        headers=[(b"x-forwarded-for", b"192.0.2.10")],
        client="203.0.113.7",
    )
    assert resolver.resolve(request_scope) == "203.0.113.7"


def test_x_forwarded_for_is_never_trusted() -> None:
    resolver = ClientIpResolver(("10.0.0.0/8",))
    request_scope = scope(
        headers=[
            (
                b"x-forwarded-for",
                b"192.0.2.10, 198.51.100.20, 10.0.0.4",
            )
        ],
        client="10.0.0.5",
    )
    assert resolver.resolve(request_scope) == "10.0.0.5"


def test_configured_client_ip_header_requires_trusted_peer_and_one_valid_ip() -> None:
    resolver = ClientIpResolver(
        ("10.0.0.0/8",),
        client_ip_header="CF-Connecting-IP",
    )
    trusted_scope = scope(
        headers=[(b"cf-connecting-ip", b"198.51.100.20")],
        client="10.0.0.5",
    )
    assert resolver.resolve(trusted_scope) == "198.51.100.20"
    untrusted_scope = scope(
        headers=[(b"cf-connecting-ip", b"198.51.100.20")],
        client="203.0.113.7",
    )
    assert resolver.resolve(untrusted_scope) == "203.0.113.7"
    for headers in (
        [(b"cf-connecting-ip", b"invalid")],
        [(b"cf-connecting-ip", b"192.0.2.1, 198.51.100.2")],
        [
            (b"cf-connecting-ip", b"192.0.2.1"),
            (b"cf-connecting-ip", b"198.51.100.2"),
        ],
    ):
        with pytest.raises(InvalidClientAddress):
            resolver.resolve(scope(headers=headers, client="10.0.0.5"))


@pytest.mark.asyncio
async def test_rate_limit_is_atomic_and_windowed() -> None:
    current = 100.0
    limiter = InMemoryRateLimiter(limit=2, window_seconds=10, monotonic=lambda: current)
    await limiter.consume("client")
    await limiter.consume("client")
    with pytest.raises(RateLimitExceeded):
        await limiter.consume("client")
    current = 111.0
    await limiter.consume("client")


@pytest.mark.asyncio
async def test_rate_limiter_caps_keys_and_evicts_all_inactive_buckets() -> None:
    current = 100.0
    limiter = InMemoryRateLimiter(
        limit=2,
        window_seconds=10,
        max_keys=2,
        monotonic=lambda: current,
    )
    await limiter.consume("one")
    await limiter.consume("two")
    with pytest.raises(RateLimitExceeded):
        await limiter.consume("three")
    current = 111.0
    await limiter.consume("three")


@pytest.mark.asyncio
async def test_public_limiter_runs_before_downstream_body_parsing() -> None:
    parsed = False
    sent: list[Message] = []
    limiter = InMemoryRateLimiter(limit=1, window_seconds=10)
    await limiter.consume("203.0.113.7")

    async def app(_: dict[str, Any], __: object, ___: object) -> None:
        nonlocal parsed
        parsed = True

    middleware = PublicSubmissionRateLimitMiddleware(
        app,
        limiter=limiter,
        resolver=ClientIpResolver(()),
    )

    async def receive() -> Message:
        raise AssertionError("body should not be read")

    async def send(message: Message) -> None:
        sent.append(message)

    await middleware(scope(), receive, send)
    assert not parsed
    assert sent[0]["status"] == 429


@pytest.mark.asyncio
@pytest.mark.parametrize("response_kind", ["body_cap", "rate_limit"])
async def test_cors_wraps_preparse_error_responses(response_kind: str) -> None:
    sent: list[Message] = []

    async def app(_: dict[str, Any], __: object, ___: object) -> None:
        raise AssertionError("request should not reach the application")

    if response_kind == "body_cap":
        inner = BodyCapMiddleware(app, max_bytes=4)
        request_scope = scope(
            headers=[
                (b"origin", b"https://alma.example"),
                (b"content-length", b"5"),
            ]
        )
    else:
        limiter = InMemoryRateLimiter(limit=1, window_seconds=10)
        await limiter.consume("203.0.113.7")
        inner = PublicSubmissionRateLimitMiddleware(
            app,
            limiter=limiter,
            resolver=ClientIpResolver(()),
        )
        request_scope = scope(headers=[(b"origin", b"https://alma.example")])
    middleware = CORSMiddleware(
        inner,
        allow_origins=["https://alma.example"],
        allow_methods=["POST"],
    )

    async def receive() -> Message:
        raise AssertionError("body should not be read")

    async def send(message: Message) -> None:
        sent.append(message)

    await middleware(request_scope, receive, send)
    response_headers = dict(sent[0]["headers"])
    assert response_headers[b"access-control-allow-origin"] == b"https://alma.example"
