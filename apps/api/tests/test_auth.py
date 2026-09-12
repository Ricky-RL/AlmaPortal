from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from alma_api.auth import AuthenticationError, JwtVerificationMode, SupabaseJwtVerifier

ISSUER = "https://project.supabase.co/auth/v1"
LOCAL_ISSUER = "http://127.0.0.1:54321/auth/v1"
LOCAL_SECRET = "local-supabase-jwt-secret-at-least-32-bytes"


def key_pair(kid: str) -> tuple[Any, dict[str, Any]]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key(), as_dict=True)
    jwk.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return private, jwk


def claims(**changes: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    base: dict[str, Any] = {
        "iss": ISSUER,
        "aud": "authenticated",
        "exp": now + timedelta(minutes=5),
        "nbf": now - timedelta(seconds=1),
        "sub": str(uuid4()),
        "role": "authenticated",
        "email": "reviewer@example.com",
        "is_anonymous": False,
        "app_metadata": {"provider": "google", "providers": ["google"]},
        "user_metadata": {"provider": "untrusted-value"},
    }
    base.update(changes)
    return base


def encoded(private: Any, kid: str, token_claims: dict[str, Any]) -> str:
    return jwt.encode(token_claims, private, algorithm="RS256", headers={"kid": kid})


@pytest.mark.asyncio
async def test_valid_google_token_uses_signed_app_metadata_not_user_metadata() -> None:
    private, jwk = key_pair("key-1")
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"keys": [jwk]}))
    async with httpx.AsyncClient(transport=transport) as client:
        verifier = SupabaseJwtVerifier(
            issuer=ISSUER,
            jwks_url=f"{ISSUER}/.well-known/jwks.json",
            algorithms=("RS256",),
            client=client,
        )
        current = await verifier.verify(encoded(private, "key-1", claims()))
    assert current.email.value == "reviewer@example.com"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_claims",
    [
        {"iss": "https://attacker.example/auth/v1"},
        {"aud": "other"},
        {"aud": ["authenticated", "other"]},
        {"role": "anon"},
        {"is_anonymous": True},
        {"app_metadata": {"provider": "email", "providers": ["email"]}},
        {"app_metadata": {"provider": "google", "providers": ["google", "email"]}},
        {"exp": datetime.now(UTC) - timedelta(seconds=1)},
        {"nbf": datetime.now(UTC) + timedelta(minutes=1)},
    ],
)
async def test_rejects_invalid_supabase_claims(invalid_claims: dict[str, Any]) -> None:
    private, jwk = key_pair("key-1")
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"keys": [jwk]}))
    async with httpx.AsyncClient(transport=transport) as client:
        verifier = SupabaseJwtVerifier(
            issuer=ISSUER,
            jwks_url=f"{ISSUER}/.well-known/jwks.json",
            algorithms=("RS256",),
            client=client,
        )
        with pytest.raises(AuthenticationError):
            await verifier.verify(encoded(private, "key-1", claims(**invalid_claims)))


@pytest.mark.asyncio
async def test_unknown_kid_forces_one_jwks_refresh_for_key_rotation() -> None:
    private_one, jwk_one = key_pair("key-1")
    private_two, jwk_two = key_pair("key-2")
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        keys = [jwk_one] if calls == 1 else [jwk_one, jwk_two]
        return httpx.Response(200, json={"keys": keys})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        verifier = SupabaseJwtVerifier(
            issuer=ISSUER,
            jwks_url=f"{ISSUER}/.well-known/jwks.json",
            algorithms=("RS256",),
            client=client,
        )
        await verifier.verify(encoded(private_one, "key-1", claims()))
        await verifier.verify(encoded(private_two, "key-2", claims()))
    assert calls == 2


@pytest.mark.asyncio
async def test_symmetric_algorithm_is_rejected_before_key_use() -> None:
    transport = httpx.MockTransport(lambda _: pytest.fail("JWKS should not be fetched"))
    token = jwt.encode(claims(), "x" * 32, algorithm="HS256", headers={"kid": "key"})
    async with httpx.AsyncClient(transport=transport) as client:
        verifier = SupabaseJwtVerifier(
            issuer=ISSUER,
            jwks_url=f"{ISSUER}/.well-known/jwks.json",
            algorithms=("RS256",),
            client=client,
        )
        with pytest.raises(AuthenticationError):
            await verifier.verify(token)


@pytest.mark.asyncio
async def test_local_hs256_verifies_genuine_shaped_supabase_token_without_kid() -> None:
    transport = httpx.MockTransport(lambda _: pytest.fail("JWKS should not be fetched"))
    token = jwt.encode(
        claims(iss=LOCAL_ISSUER),
        LOCAL_SECRET,
        algorithm="HS256",
    )
    async with httpx.AsyncClient(transport=transport) as client:
        verifier = SupabaseJwtVerifier(
            issuer=LOCAL_ISSUER,
            jwks_url=f"{LOCAL_ISSUER}/.well-known/jwks.json",
            algorithms=("HS256",),
            client=client,
            mode=JwtVerificationMode.LOCAL_HS256,
            shared_secret=LOCAL_SECRET,
        )
        current = await verifier.verify(token)
    assert current.email.value == "reviewer@example.com"


@pytest.mark.asyncio
async def test_local_hs256_rejects_wrong_secret() -> None:
    token = jwt.encode(
        claims(iss=LOCAL_ISSUER),
        "a-different-local-secret-that-is-long-enough",
        algorithm="HS256",
    )
    async with httpx.AsyncClient() as client:
        verifier = SupabaseJwtVerifier(
            issuer=LOCAL_ISSUER,
            jwks_url=f"{LOCAL_ISSUER}/.well-known/jwks.json",
            algorithms=("HS256",),
            client=client,
            mode=JwtVerificationMode.LOCAL_HS256,
            shared_secret=LOCAL_SECRET,
        )
        with pytest.raises(AuthenticationError):
            await verifier.verify(token)


@pytest.mark.asyncio
async def test_local_hs256_keeps_google_provider_claim_checks() -> None:
    token = jwt.encode(
        claims(
            iss=LOCAL_ISSUER,
            app_metadata={"provider": "email", "providers": ["email"]},
        ),
        LOCAL_SECRET,
        algorithm="HS256",
    )
    async with httpx.AsyncClient() as client:
        verifier = SupabaseJwtVerifier(
            issuer=LOCAL_ISSUER,
            jwks_url=f"{LOCAL_ISSUER}/.well-known/jwks.json",
            algorithms=("HS256",),
            client=client,
            mode=JwtVerificationMode.LOCAL_HS256,
            shared_secret=LOCAL_SECRET,
        )
        with pytest.raises(AuthenticationError):
            await verifier.verify(token)
