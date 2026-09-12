"""External provider adapters and process-local primitives."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hmac
import json
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import PurePosixPath
from urllib.parse import quote

import httpx

from alma_api.application import (
    ApplicationError,
    DependencyUnavailableError,
    DownloadGrant,
    StoredObject,
)
from alma_api.domain import DeliveryState, MailMessage, MailResult


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class TicketError(ApplicationError):
    code = "invalid_download_ticket"


class HmacTicketSigner:
    def __init__(self, secret: bytes) -> None:
        if len(secret) < 32:
            raise ValueError("ticket signing secret must contain at least 32 bytes")
        self._secret = secret

    def issue(self, grant: DownloadGrant) -> str:
        payload = {
            "v": 1,
            "lead_id": str(grant.lead_id),
            "reviewer_id": str(grant.reviewer_id),
            "object_key": grant.object_key,
            "exp": int(grant.expires_at.timestamp()),
        }
        encoded = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
        signature = _b64encode(hmac.digest(self._secret, encoded.encode(), "sha256"))
        return f"{encoded}.{signature}"

    def verify(self, token: str, now: datetime) -> DownloadGrant:
        from uuid import UUID

        if len(token) > 4096:
            raise TicketError("download ticket is invalid")
        try:
            encoded, supplied_signature = token.split(".", 1)
            expected_signature = hmac.digest(self._secret, encoded.encode(), "sha256")
            if not hmac.compare_digest(_b64decode(supplied_signature), expected_signature):
                raise ValueError
            payload = json.loads(_b64decode(encoded))
            if set(payload) != {"v", "lead_id", "reviewer_id", "object_key", "exp"}:
                raise ValueError
            if payload["v"] != 1 or not isinstance(payload["exp"], int):
                raise ValueError
            expires_at = datetime.fromtimestamp(payload["exp"], UTC)
            if expires_at <= now.astimezone(UTC):
                raise TicketError("download ticket has expired")
            lead_id = UUID(payload["lead_id"])
            reviewer_id = UUID(payload["reviewer_id"])
            object_key = payload["object_key"]
            path = PurePosixPath(object_key)
            object_id, separator, extension = path.name.rpartition(".")
            if (
                not isinstance(object_key, str)
                or path.is_absolute()
                or ".." in path.parts
                or len(path.parts) != 3
                or path.parts[0] != "leads"
                or path.parts[1] != str(lead_id)
                or not separator
                or extension not in {"pdf", "doc", "docx"}
                or UUID(object_id).version != 4
            ):
                raise ValueError
            return DownloadGrant(
                lead_id=lead_id,
                reviewer_id=reviewer_id,
                object_key=object_key,
                expires_at=expires_at,
            )
        except TicketError:
            raise
        except (
            ValueError,
            TypeError,
            KeyError,
            json.JSONDecodeError,
            binascii.Error,
        ) as exc:
            raise TicketError("download ticket is invalid") from exc


class SupabaseStorage:
    def __init__(
        self,
        *,
        base_url: str,
        service_role_key: str,
        bucket: str,
        client: httpx.AsyncClient,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._key = service_role_key
        self._bucket = bucket
        self._client = client

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._key}",
            "apikey": self._key,
        }

    def _object_url(self, key: str) -> str:
        encoded_bucket = quote(self._bucket, safe="")
        encoded_key = quote(key, safe="/")
        return f"{self._base_url}/storage/v1/object/{encoded_bucket}/{encoded_key}"

    async def upload(self, key: str, content: bytes, media_type: str) -> None:
        try:
            response = await self._client.put(
                self._object_url(key),
                content=content,
                headers={
                    **self._headers,
                    "Content-Type": media_type,
                    "x-upsert": "false",
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DependencyUnavailableError("resume storage upload failed") from exc

    async def delete(self, key: str) -> None:
        try:
            response = await self._client.delete(self._object_url(key), headers=self._headers)
            if response.status_code != 404:
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DependencyUnavailableError("resume storage delete failed") from exc

    async def open(self, key: str) -> StoredObject:
        response: httpx.Response | None = None
        try:
            request = self._client.build_request(
                "GET", self._object_url(key), headers=self._headers
            )
            response = await self._client.send(request, stream=True)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            if response is not None:
                await response.aclose()
            raise DependencyUnavailableError("resume storage download failed") from exc
        if response is None:
            raise DependencyUnavailableError("resume storage download failed")
        size_header = response.headers.get("content-length")
        size = int(size_header) if size_header and size_header.isdigit() else None
        media_type = response.headers.get("content-type", "application/octet-stream")

        async def stream() -> AsyncIterator[bytes]:
            try:
                async for chunk in response.aiter_bytes():
                    yield chunk
            finally:
                await response.aclose()

        return StoredObject(content=stream(), media_type=media_type, size_bytes=size)

    async def list_keys(self, prefix: str) -> AsyncIterator[str]:
        offset = 0
        page_size = 100
        encoded_bucket = quote(self._bucket, safe="")
        url = f"{self._base_url}/storage/v1/object/list/{encoded_bucket}"
        while True:
            try:
                response = await self._client.post(
                    url,
                    headers={**self._headers, "Content-Type": "application/json"},
                    json={
                        "prefix": prefix,
                        "limit": page_size,
                        "offset": offset,
                        "sortBy": {"column": "name", "order": "asc"},
                    },
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise DependencyUnavailableError("resume storage listing failed") from exc
            try:
                rows = response.json()
            except ValueError as exc:
                raise DependencyUnavailableError(
                    "resume storage returned an invalid listing"
                ) from exc
            if not isinstance(rows, list):
                raise DependencyUnavailableError("resume storage returned an invalid listing")
            for row in rows:
                name = row.get("name") if isinstance(row, dict) else None
                if isinstance(name, str):
                    yield f"{prefix.rstrip('/')}/{name}"
            if len(rows) < page_size:
                return
            offset += page_size


class ResendMailer:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        from_email: str,
        client: httpx.AsyncClient,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._from_email = from_email
        self._client = client

    async def send(self, message: MailMessage) -> MailResult:
        try:
            response = await self._client.post(
                f"{self._base_url}/emails",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": self._from_email,
                    "to": [message.recipient.value],
                    "subject": message.subject,
                    "text": message.plain_body,
                    "html": message.html_body,
                },
            )
        except httpx.RequestError as exc:
            return MailResult(
                state=DeliveryState.UNKNOWN,
                http_status=None,
                sanitized_error=f"connection_ambiguous:{type(exc).__name__}",
            )
        if response.status_code == 200:
            return MailResult(
                state=DeliveryState.PROVIDER_ACCEPTED,
                http_status=response.status_code,
                provider_message_id=_resend_message_id(response),
            )
        if response.status_code == 429 or response.status_code >= 500:
            return MailResult(
                state=DeliveryState.FAILED,
                http_status=response.status_code,
                sanitized_error=f"resend_retryable_{response.status_code}",
            )
        return MailResult(
            state=DeliveryState.FAILED,
            http_status=response.status_code,
            sanitized_error=f"resend_rejected_{response.status_code}",
        )


def _resend_message_id(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return "resend-accepted-without-id"
    if not isinstance(payload, dict):
        return "resend-accepted-without-id"
    raw_id = payload.get("id")
    if isinstance(raw_id, str) and raw_id.strip():
        return raw_id.strip()
    return "resend-accepted-without-id"


class RateLimitExceeded(ApplicationError):
    code = "rate_limit_exceeded"

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("submission rate limit exceeded")
        self.retry_after_seconds = retry_after_seconds


class InMemoryRateLimiter:
    """Atomic process-local limiter for the configured single worker."""

    def __init__(
        self,
        *,
        limit: int,
        window_seconds: int,
        max_keys: int = 10_000,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._max_keys = max_keys
        self._monotonic = monotonic
        self._entries: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()
        if limit <= 0 or window_seconds <= 0 or max_keys <= 0:
            raise ValueError("rate limiter bounds must be positive")

    async def consume(self, key: str) -> None:
        async with self._lock:
            now = self._monotonic()
            cutoff = now - self._window
            inactive = [
                existing_key
                for existing_key, timestamps in self._entries.items()
                if not timestamps or timestamps[-1] <= cutoff
            ]
            for existing_key in inactive:
                del self._entries[existing_key]
            entries = self._entries.get(key)
            if entries is None:
                if len(self._entries) >= self._max_keys:
                    raise RateLimitExceeded(self._window)
                entries = deque()
                self._entries[key] = entries
            while entries and entries[0] <= cutoff:
                entries.popleft()
            if len(entries) >= self._limit:
                retry_after = max(1, int(entries[0] + self._window - now) + 1)
                raise RateLimitExceeded(retry_after)
            entries.append(now)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _b64decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    decoded = base64.b64decode(padded, altchars=b"-_", validate=True)
    if _b64encode(decoded) != value:
        raise ValueError("non-canonical base64")
    return decoded
