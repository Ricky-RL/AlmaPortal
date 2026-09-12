"""Validated runtime configuration."""

from __future__ import annotations

import os
from typing import Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, SecretStr, field_validator, model_validator


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    environment: str = "development"
    database_url: SecretStr
    supabase_url: str
    supabase_service_role_key: SecretStr
    storage_bucket: str = "resumes"
    sendgrid_api_key: SecretStr
    sendgrid_base_url: str = "https://api.sendgrid.com"
    sendgrid_from_email: str
    attorney_notification_email: str
    public_api_url: str
    supabase_jwt_issuer: str
    supabase_jwks_url: str
    jwt_algorithms: tuple[str, ...] = ("RS256", "ES256")
    ticket_signing_secret: SecretStr
    cors_origins: tuple[str, ...]
    trusted_proxy_cidrs: tuple[str, ...] = ()
    overall_body_cap_bytes: int = 12 * 1024 * 1024
    public_rate_limit: int = 5
    public_rate_window_seconds: int = 15 * 60
    provider_timeout_seconds: float = 5.0
    commit_sha: str = "unknown"
    log_level: str = "INFO"

    @field_validator(
        "supabase_url",
        "supabase_jwt_issuer",
        "supabase_jwks_url",
        "sendgrid_base_url",
        "public_api_url",
    )
    @classmethod
    def strip_url(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("cors_origins")
    @classmethod
    def validate_cors(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or "*" in value:
            raise ValueError("CORS_ORIGINS must contain explicit origins")
        if any(
            not origin.startswith(("https://", "http://localhost", "http://127.0.0.1"))
            for origin in value
        ):
            raise ValueError("CORS origins must use HTTPS except for local development")
        return value

    @field_validator("jwt_algorithms")
    @classmethod
    def validate_algorithms(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        allowed = {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "EdDSA"}
        if not value or not set(value).issubset(allowed):
            raise ValueError("JWT algorithms must be an explicit asymmetric allowlist")
        return value

    @field_validator("ticket_signing_secret")
    @classmethod
    def validate_ticket_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value().encode()) < 32:
            raise ValueError("TICKET_SIGNING_SECRET must contain at least 32 bytes")
        return value

    @model_validator(mode="after")
    def validate_runtime_limits(self) -> Self:
        if int(os.getenv("WEB_CONCURRENCY", "1")) != 1:
            raise ValueError("the in-memory public limiter requires WEB_CONCURRENCY=1")
        positive_values = (
            self.overall_body_cap_bytes,
            self.public_rate_limit,
            self.public_rate_window_seconds,
            self.provider_timeout_seconds,
        )
        if any(value <= 0 for value in positive_values):
            raise ValueError("runtime limits must be positive")
        if self.overall_body_cap_bytes <= 10 * 1024 * 1024:
            raise ValueError("overall request cap must leave room for a 10 MiB multipart file")
        if self.environment == "production" and any(
            origin.startswith("http://") for origin in self.cors_origins
        ):
            raise ValueError("production CORS origins must use HTTPS")
        validate_service_url(
            self.sendgrid_base_url,
            environment=self.environment,
            setting="SENDGRID_BASE_URL",
        )
        validate_service_url(
            self.public_api_url,
            environment=self.environment,
            setting="PUBLIC_API_URL",
        )
        return self

    @classmethod
    def from_env(cls) -> Settings:
        supabase_url = required("SUPABASE_URL").rstrip("/")
        return cls(
            environment=os.getenv("ENVIRONMENT", "development"),
            database_url=required("DATABASE_URL"),
            supabase_url=supabase_url,
            supabase_service_role_key=required("SUPABASE_SERVICE_ROLE_KEY"),
            storage_bucket=os.getenv("SUPABASE_STORAGE_BUCKET", "resumes"),
            sendgrid_api_key=required("SENDGRID_API_KEY"),
            sendgrid_base_url=os.getenv("SENDGRID_BASE_URL", "https://api.sendgrid.com"),
            sendgrid_from_email=required("SENDGRID_FROM_EMAIL"),
            attorney_notification_email=required("ATTORNEY_NOTIFICATION_EMAIL"),
            public_api_url=required("PUBLIC_API_URL"),
            supabase_jwt_issuer=os.getenv("SUPABASE_JWT_ISSUER", f"{supabase_url}/auth/v1"),
            supabase_jwks_url=os.getenv(
                "SUPABASE_JWKS_URL", f"{supabase_url}/auth/v1/.well-known/jwks.json"
            ),
            jwt_algorithms=csv("JWT_ALGORITHMS", ("RS256", "ES256")),
            ticket_signing_secret=required("TICKET_SIGNING_SECRET"),
            cors_origins=csv("CORS_ORIGINS"),
            trusted_proxy_cidrs=csv("TRUSTED_PROXY_CIDRS", ()),
            overall_body_cap_bytes=int(os.getenv("OVERALL_BODY_CAP_BYTES", str(12 * 1024 * 1024))),
            public_rate_limit=int(os.getenv("PUBLIC_RATE_LIMIT", "5")),
            public_rate_window_seconds=int(os.getenv("PUBLIC_RATE_WINDOW_SECONDS", "900")),
            provider_timeout_seconds=float(os.getenv("PROVIDER_TIMEOUT_SECONDS", "5")),
            commit_sha=os.getenv("RENDER_GIT_COMMIT", os.getenv("COMMIT_SHA", "unknown")),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )

    @property
    def sqlalchemy_url(self) -> str:
        value = self.database_url.get_secret_value()
        if value.startswith("postgres://"):
            value = f"postgresql://{value.removeprefix('postgres://')}"
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value


def required(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RuntimeError(f"{name} is required")
    return value.strip()


def csv(name: str, default: tuple[str, ...] | None = None) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None:
        if default is None:
            raise RuntimeError(f"{name} is required")
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


def validate_service_url(value: str, *, environment: str, setting: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError(f"{setting} must be an origin without credentials, path, or query")
    if parsed.scheme == "https":
        return
    loopback_hosts = {"localhost", "127.0.0.1", "::1"}
    if environment == "production" or parsed.hostname not in loopback_hosts:
        raise ValueError(f"{setting} permits HTTP only for loopback outside production")
