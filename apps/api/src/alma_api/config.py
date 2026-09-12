"""Validated runtime configuration."""

from __future__ import annotations

import os
from ipaddress import ip_address, ip_network
from typing import Self
from urllib.parse import parse_qs, urlsplit

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
    supabase_jwt_secret: SecretStr | None = None
    ticket_signing_secret: SecretStr
    cors_origins: tuple[str, ...]
    trusted_proxy_cidrs: tuple[str, ...] = ()
    trusted_client_ip_header: str | None = None
    overall_body_cap_bytes: int = 12 * 1024 * 1024
    public_rate_limit: int = 5
    public_rate_window_seconds: int = 15 * 60
    public_rate_limit_max_keys: int = 10_000
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

    @field_validator("environment")
    @classmethod
    def normalize_environment(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"development", "test", "production"}:
            raise ValueError("ENVIRONMENT must be development, test, or production")
        return normalized

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
        if value == ("HS256",):
            return value
        if "HS256" in value:
            raise ValueError("HS256 cannot be combined with asymmetric JWT algorithms")
        if not value or not set(value).issubset(allowed):
            raise ValueError("JWT algorithms must be an explicit asymmetric allowlist")
        return value

    @field_validator("trusted_proxy_cidrs")
    @classmethod
    def validate_proxy_cidrs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        try:
            for cidr in value:
                ip_network(cidr, strict=False)
        except ValueError as exc:
            raise ValueError("TRUSTED_PROXY_CIDRS contains an invalid network") from exc
        return value

    @field_validator("trusted_client_ip_header")
    @classmethod
    def validate_client_ip_header(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value.strip().lower() != "cf-connecting-ip":
            raise ValueError("TRUSTED_CLIENT_IP_HEADER may only be CF-Connecting-IP")
        return "CF-Connecting-IP"

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
            self.public_rate_limit_max_keys,
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
        if self.trusted_client_ip_header is not None and not self.trusted_proxy_cidrs:
            raise ValueError("TRUSTED_CLIENT_IP_HEADER requires documented TRUSTED_PROXY_CIDRS")
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
        validate_service_url(
            self.supabase_url,
            environment=self.environment,
            setting="SUPABASE_URL",
        )
        expected_issuer = f"{self.supabase_url}/auth/v1"
        expected_jwks = f"{expected_issuer}/.well-known/jwks.json"
        if self.supabase_jwt_issuer != expected_issuer:
            raise ValueError("SUPABASE_JWT_ISSUER must be the auth child of SUPABASE_URL")
        if self.supabase_jwks_url != expected_jwks:
            raise ValueError("SUPABASE_JWKS_URL must be the JWKS child of SUPABASE_URL")
        if (
            self.environment == "production"
            and self.sendgrid_base_url != "https://api.sendgrid.com"
        ):
            raise ValueError("production SENDGRID_BASE_URL must be https://api.sendgrid.com")
        validate_database_tls(self.database_url.get_secret_value())
        local_hs256 = self.jwt_algorithms == ("HS256",)
        if local_hs256:
            if self.environment == "production":
                raise ValueError("HS256 Supabase JWT verification is forbidden in production")
            if not is_loopback_host(urlsplit(self.supabase_url).hostname):
                raise ValueError("HS256 Supabase JWT verification requires a loopback Supabase URL")
            if (
                self.supabase_jwt_secret is None
                or len(self.supabase_jwt_secret.get_secret_value().encode()) < 32
            ):
                raise ValueError("SUPABASE_JWT_SECRET must contain at least 32 bytes")
        elif self.supabase_jwt_secret is not None:
            raise ValueError("SUPABASE_JWT_SECRET is accepted only for explicit local HS256 mode")
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
            supabase_jwt_secret=optional("SUPABASE_JWT_SECRET"),
            ticket_signing_secret=required("TICKET_SIGNING_SECRET"),
            cors_origins=csv("CORS_ORIGINS"),
            trusted_proxy_cidrs=csv("TRUSTED_PROXY_CIDRS", ()),
            trusted_client_ip_header=optional("TRUSTED_CLIENT_IP_HEADER"),
            overall_body_cap_bytes=int(os.getenv("OVERALL_BODY_CAP_BYTES", str(12 * 1024 * 1024))),
            public_rate_limit=int(os.getenv("PUBLIC_RATE_LIMIT", "5")),
            public_rate_window_seconds=int(os.getenv("PUBLIC_RATE_WINDOW_SECONDS", "900")),
            public_rate_limit_max_keys=int(os.getenv("PUBLIC_RATE_LIMIT_MAX_KEYS", "10000")),
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


def optional(name: str) -> str | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
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


def is_loopback_host(hostname: str | None) -> bool:
    if hostname is None:
        return False
    if hostname.lower() == "localhost":
        return True
    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False


def validate_database_tls(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme not in {"postgres", "postgresql", "postgresql+psycopg"}:
        raise ValueError("DATABASE_URL must use PostgreSQL")
    if parsed.hostname is None or is_loopback_host(parsed.hostname):
        return
    ssl_modes = parse_qs(parsed.query).get("sslmode", [])
    if len(ssl_modes) != 1 or ssl_modes[0] not in {"require", "verify-ca", "verify-full"}:
        raise ValueError(
            "non-loopback DATABASE_URL requires sslmode=require, verify-ca, or verify-full"
        )
