from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from alma_api.infrastructure import InMemoryRateLimiter, RateLimitExceeded
from alma_api.middleware import (
    BodyCapMiddleware,
    ClientIpResolver,
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


def test_rightmost_untrusted_address_is_selected_from_proxy_chain() -> None:
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
    assert resolver.resolve(request_scope) == "198.51.100.20"


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
