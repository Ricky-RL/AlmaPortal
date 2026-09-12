"""ASGI security and observability middleware."""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from alma_api.infrastructure import InMemoryRateLimiter, RateLimitExceeded

logger = logging.getLogger("alma_api.request")

AsgiMessage = dict[str, Any]
Receive = Callable[[], Awaitable[AsgiMessage]]
Send = Callable[[AsgiMessage], Awaitable[None]]
AsgiApp = Callable[[dict[str, Any], Receive, Send], Awaitable[None]]

_REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,64}\Z")


class RequestBodyTooLarge(Exception):
    pass


class InvalidClientAddress(Exception):
    pass


class BodyCapMiddleware:
    def __init__(self, app: AsgiApp, max_bytes: int) -> None:
        self._app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        content_length = _single_header(scope, b"content-length")
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                await _send_problem(
                    send, 400, "invalid_content_length", "Content-Length is invalid"
                )
                return
            if declared < 0:
                await _send_problem(
                    send, 400, "invalid_content_length", "Content-Length is invalid"
                )
                return
            if declared > self._max_bytes:
                await _send_problem(send, 413, "request_too_large", "request body is too large")
                return

        received = 0
        response_started = False

        async def capped_receive() -> AsgiMessage:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._max_bytes:
                    raise RequestBodyTooLarge
            return message

        async def tracked_send(message: AsgiMessage) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self._app(scope, capped_receive, tracked_send)
        except RequestBodyTooLarge:
            if not response_started:
                await _send_problem(send, 413, "request_too_large", "request body is too large")
                return
            raise


class ClientIpResolver:
    def __init__(
        self,
        trusted_proxy_cidrs: tuple[str, ...],
        *,
        client_ip_header: str | None = None,
    ) -> None:
        self._trusted = tuple(
            ipaddress.ip_network(cidr, strict=False) for cidr in trusted_proxy_cidrs
        )
        self._client_ip_header = (
            client_ip_header.lower().encode() if client_ip_header is not None else None
        )

    def resolve(self, scope: dict[str, Any]) -> str:
        peer_text = scope.get("client", ("unknown", 0))[0]
        try:
            peer = ipaddress.ip_address(peer_text)
        except ValueError:
            return "unknown"
        if not self._is_trusted(peer) or self._client_ip_header is None:
            return peer.compressed
        values = _header_values(scope, self._client_ip_header)
        if not values:
            return peer.compressed
        if len(values) != 1 or "," in values[0]:
            raise InvalidClientAddress("trusted client IP header is malformed")
        try:
            return ipaddress.ip_address(values[0].strip()).compressed
        except ValueError as exc:
            raise InvalidClientAddress("trusted client IP header is malformed") from exc

    def _is_trusted(self, address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        return any(address in network for network in self._trusted)


class PublicSubmissionRateLimitMiddleware:
    def __init__(
        self,
        app: AsgiApp,
        *,
        limiter: InMemoryRateLimiter,
        resolver: ClientIpResolver,
    ) -> None:
        self._app = app
        self._limiter = limiter
        self._resolver = resolver

    async def __call__(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["method"] == "POST"
            and scope["path"] == "/api/v1/leads"
        ):
            try:
                await self._limiter.consume(self._resolver.resolve(scope))
            except InvalidClientAddress:
                await _send_problem(
                    send,
                    400,
                    "invalid_client_address",
                    "trusted client IP header is malformed",
                )
                return
            except RateLimitExceeded as exc:
                await _send_problem(
                    send,
                    429,
                    exc.code,
                    str(exc),
                    headers=[(b"retry-after", str(exc.retry_after_seconds).encode())],
                )
                return
        await self._app(scope, receive, send)


class RequestContextMiddleware:
    def __init__(self, app: AsgiApp) -> None:
        self._app = app

    async def __call__(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        supplied = _single_header(scope, b"x-request-id")
        request_id = supplied if supplied and _REQUEST_ID.fullmatch(supplied) else str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.monotonic()
        status = 500

        async def add_request_id(message: AsgiMessage) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self._app(scope, receive, add_request_id)
        finally:
            route = scope.get("route")
            route_template = getattr(route, "path", "<unmatched>")
            logger.info(
                "request_completed",
                extra={
                    "request_id": request_id,
                    "method": scope["method"],
                    "route": route_template,
                    "status": status,
                    "duration_ms": round((time.monotonic() - started) * 1000, 2),
                },
            )


def _single_header(scope: dict[str, Any], name: bytes) -> str | None:
    values = _header_values(scope, name)
    if len(values) != 1:
        return None
    return values[0]


def _header_values(scope: dict[str, Any], name: bytes) -> list[str]:
    return [
        value.decode("latin-1") for key, value in scope.get("headers", []) if key.lower() == name
    ]


async def _send_problem(
    send: Send,
    status: int,
    code: str,
    detail: str,
    *,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    body = json.dumps(
        {
            "type": f"urn:alma-portal:problem:{code}",
            "title": code.replace("_", " "),
            "status": status,
            "detail": detail,
            "code": code,
        },
        separators=(",", ":"),
    ).encode()
    response_headers = [
        (b"content-type", b"application/problem+json"),
        (b"content-length", str(len(body)).encode()),
        *(headers or []),
    ]
    await send({"type": "http.response.start", "status": status, "headers": response_headers})
    await send({"type": "http.response.body", "body": body})
