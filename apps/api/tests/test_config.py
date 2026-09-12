from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from alma_api.config import Settings


def settings_values(**changes: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "environment": "development",
        "database_url": "postgresql://user:password@localhost/alma",
        "supabase_url": "http://127.0.0.1:54321",
        "supabase_service_role_key": "service-key",
        "sendgrid_api_key": "sendgrid-key",
        "sendgrid_from_email": "sender@example.com",
        "attorney_notification_email": "attorney@example.com",
        "public_api_url": "http://127.0.0.1:8000",
        "supabase_jwt_issuer": "http://127.0.0.1:54321/auth/v1",
        "supabase_jwks_url": "http://127.0.0.1:54321/auth/v1/.well-known/jwks.json",
        "ticket_signing_secret": "x" * 32,
        "cors_origins": ("http://localhost:3000",),
    }
    values.update(changes)
    return values


def test_provider_defaults_match_canonical_services() -> None:
    settings = Settings(**settings_values())
    assert settings.storage_bucket == "resumes"
    assert settings.sendgrid_base_url == "https://api.sendgrid.com"


def test_sendgrid_http_loopback_is_allowed_only_outside_production() -> None:
    settings = Settings(**settings_values(sendgrid_base_url="http://127.0.0.1:4010"))
    assert settings.sendgrid_base_url == "http://127.0.0.1:4010"
    with pytest.raises(ValidationError):
        Settings(
            **settings_values(
                environment="production",
                cors_origins=("https://alma.example",),
                public_api_url="https://api.alma.example",
                sendgrid_base_url="http://127.0.0.1:4010",
            )
        )
    with pytest.raises(ValidationError):
        Settings(**settings_values(sendgrid_base_url="http://sendgrid.example"))


def test_public_api_url_rejects_paths_credentials_and_insecure_remote_hosts() -> None:
    for url in (
        "https://api.alma.example/path",
        "https://user:password@api.alma.example",
        "http://api.alma.example",
    ):
        with pytest.raises(ValidationError):
            Settings(**settings_values(public_api_url=url))
