"""Supabase asymmetric JWT verification."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from enum import StrEnum
from typing import Any
from uuid import UUID

import httpx
import jwt

from alma_api.application import ApplicationError
from alma_api.domain import AuthenticatedReviewer, DomainError, NormalizedEmail


class AuthenticationError(ApplicationError):
    code = "authentication_failed"


class JwtVerificationMode(StrEnum):
    ASYMMETRIC = "asymmetric"
    LOCAL_HS256 = "local_hs256"


class SupabaseJwtVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        jwks_url: str,
        algorithms: tuple[str, ...],
        client: httpx.AsyncClient,
        mode: JwtVerificationMode = JwtVerificationMode.ASYMMETRIC,
        shared_secret: str | None = None,
        cache_ttl_seconds: int = 300,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._issuer = issuer
        self._jwks_url = jwks_url
        self._algorithms = algorithms
        self._client = client
        self._mode = mode
        self._shared_secret = shared_secret
        self._default_ttl = cache_ttl_seconds
        self._monotonic = monotonic
        self._keys: dict[str, Any] = {}
        self._expires_at = 0.0
        self._lock = asyncio.Lock()
        if mode is JwtVerificationMode.LOCAL_HS256:
            if algorithms != ("HS256",) or shared_secret is None:
                raise ValueError("local HS256 mode requires exactly HS256 and a shared secret")
            if len(shared_secret.encode()) < 32:
                raise ValueError("local HS256 shared secret must contain at least 32 bytes")
        elif "HS256" in algorithms or shared_secret is not None:
            raise ValueError("asymmetric mode cannot use HS256 or a shared secret")

    async def verify(self, token: str) -> AuthenticatedReviewer:
        if len(token) > 16_384:
            raise AuthenticationError("access token is invalid")
        try:
            header = jwt.get_unverified_header(token)
            algorithm = header.get("alg")
            kid = header.get("kid")
            if algorithm not in self._algorithms:
                raise AuthenticationError("access token header is not allowed")
            if self._mode is JwtVerificationMode.LOCAL_HS256:
                if self._shared_secret is None:
                    raise AuthenticationError("JWT verifier configuration is invalid")
                key = self._shared_secret
            else:
                if not isinstance(kid, str) or not kid:
                    raise AuthenticationError("access token header is not allowed")
                key = await self._key_for(kid)
            claims = jwt.decode(
                token,
                key=key,
                algorithms=list(self._algorithms),
                issuer=self._issuer,
                audience="authenticated",
                options={
                    "require": [
                        "iss",
                        "aud",
                        "exp",
                        "nbf",
                        "sub",
                        "role",
                        "email",
                        "app_metadata",
                        "is_anonymous",
                    ]
                },
            )
            return self._reviewer_from_claims(claims)
        except AuthenticationError:
            raise
        except (jwt.PyJWTError, ValueError, TypeError, KeyError, DomainError) as exc:
            raise AuthenticationError("access token is invalid") from exc

    async def _key_for(self, kid: str) -> Any:
        refreshed = False
        if self._monotonic() >= self._expires_at:
            await self._refresh(force=False)
            refreshed = True
        key = self._keys.get(kid)
        if key is None and not refreshed:
            await self._refresh(force=True)
            key = self._keys.get(kid)
        if key is None:
            raise AuthenticationError("access token signing key is unknown")
        return key

    async def _refresh(self, *, force: bool) -> None:
        async with self._lock:
            if not force and self._monotonic() < self._expires_at:
                return
            try:
                response = await self._client.get(self._jwks_url)
                response.raise_for_status()
                document = response.json()
                raw_keys = document.get("keys")
                if not isinstance(raw_keys, list) or not 1 <= len(raw_keys) <= 20:
                    raise ValueError("invalid key set")
                keys: dict[str, Any] = {}
                for raw_key in raw_keys:
                    if not isinstance(raw_key, dict):
                        continue
                    kid = raw_key.get("kid")
                    algorithm = raw_key.get("alg")
                    key_type = raw_key.get("kty")
                    if (
                        isinstance(kid, str)
                        and kid
                        and algorithm in self._algorithms
                        and key_type not in {"oct", None}
                    ):
                        keys[kid] = jwt.PyJWK.from_dict(raw_key).key
                if not keys:
                    raise ValueError("key set contains no allowed keys")
            except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
                raise AuthenticationError("signing keys are unavailable") from exc
            self._keys = keys
            self._expires_at = self._monotonic() + _cache_ttl(
                response.headers.get("cache-control"), self._default_ttl
            )

    @staticmethod
    def _reviewer_from_claims(claims: dict[str, Any]) -> AuthenticatedReviewer:
        if (
            claims.get("aud") != "authenticated"
            or claims.get("role") != "authenticated"
            or claims.get("is_anonymous") is not False
        ):
            raise AuthenticationError("access token is not an authenticated user token")
        app_metadata = claims.get("app_metadata")
        if not isinstance(app_metadata, dict):
            raise AuthenticationError("access token provider metadata is missing")
        providers = app_metadata.get("providers")
        if (
            app_metadata.get("provider") != "google"
            or not isinstance(providers, list)
            or set(providers) != {"google"}
        ):
            raise AuthenticationError("Google OAuth is required")
        subject = UUID(claims["sub"])
        email = NormalizedEmail.parse(claims["email"])
        return AuthenticatedReviewer(id=subject, email=email)


def _cache_ttl(cache_control: str | None, default: int) -> int:
    if cache_control:
        for directive in cache_control.split(","):
            name, separator, raw_value = directive.strip().partition("=")
            if name.lower() == "max-age" and separator and raw_value.isdigit():
                return max(30, min(int(raw_value), 3600))
    return default
