"""Application composition root."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, ClassVar

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from alma_api.application import (
    CreateResumeDownloadTicket,
    DeliveryService,
    DownloadResume,
    EmailComposer,
    GetLead,
    GetLeadSummary,
    SearchLeads,
    SubmitLead,
    TransitionLead,
)
from alma_api.auth import JwtVerificationMode, SupabaseJwtVerifier
from alma_api.config import Settings
from alma_api.domain import NormalizedEmail
from alma_api.infrastructure import (
    HmacTicketSigner,
    InMemoryRateLimiter,
    SendGridMailer,
    SupabaseStorage,
    SystemClock,
)
from alma_api.middleware import (
    BodyCapMiddleware,
    ClientIpResolver,
    PublicSubmissionRateLimitMiddleware,
    RequestContextMiddleware,
)
from alma_api.persistence import create_engine, create_uow_factory
from alma_api.presentation import Services, create_router, install_exception_handlers


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings.from_env()
    jwt_mode = (
        JwtVerificationMode.LOCAL_HS256
        if resolved.jwt_algorithms == ("HS256",)
        else JwtVerificationMode.ASYMMETRIC
    )
    configure_logging(resolved.log_level)
    engine = create_engine(resolved.sqlalchemy_url)
    provider_client = httpx.AsyncClient(
        timeout=httpx.Timeout(resolved.provider_timeout_seconds),
        follow_redirects=False,
    )
    auth_client = httpx.AsyncClient(
        timeout=httpx.Timeout(5.0),
        follow_redirects=False,
    )
    uow_factory = create_uow_factory(engine)
    clock = SystemClock()
    storage = SupabaseStorage(
        base_url=resolved.supabase_url,
        service_role_key=resolved.supabase_service_role_key.get_secret_value(),
        bucket=resolved.storage_bucket,
        client=provider_client,
    )
    mailer = SendGridMailer(
        api_key=resolved.sendgrid_api_key.get_secret_value(),
        base_url=resolved.sendgrid_base_url,
        from_email=NormalizedEmail.parse(resolved.sendgrid_from_email).value,
        client=provider_client,
    )
    composer = EmailComposer(NormalizedEmail.parse(resolved.attorney_notification_email))
    delivery_service = DeliveryService(
        uow_factory=uow_factory,
        mailer=mailer,
        composer=composer,
    )
    signer = HmacTicketSigner(resolved.ticket_signing_secret.get_secret_value().encode())
    container = Services(
        submit_lead=SubmitLead(
            uow_factory=uow_factory,
            storage=storage,
            delivery_service=delivery_service,
            composer=composer,
            clock=clock,
        ),
        search_leads=SearchLeads(uow_factory),
        get_lead=GetLead(uow_factory),
        get_summary=GetLeadSummary(uow_factory),
        transition_lead=TransitionLead(uow_factory),
        create_download_ticket=CreateResumeDownloadTicket(
            uow_factory,
            signer,
            clock,
        ),
        download_resume=DownloadResume(signer, storage, clock),
        delivery_service=delivery_service,
        jwt_verifier=SupabaseJwtVerifier(
            issuer=resolved.supabase_jwt_issuer,
            jwks_url=resolved.supabase_jwks_url,
            algorithms=resolved.jwt_algorithms,
            client=auth_client,
            mode=jwt_mode,
            shared_secret=(
                resolved.supabase_jwt_secret.get_secret_value()
                if resolved.supabase_jwt_secret is not None
                else None
            ),
        ),
        uow_factory=uow_factory,
        public_api_url=resolved.public_api_url,
        commit_sha=resolved.commit_sha,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await provider_client.aclose()
        await auth_client.aclose()
        await engine.dispose()

    app = FastAPI(
        title="AlmaPortal API",
        version="0.1.0",
        docs_url=None if resolved.environment == "production" else "/docs",
        redoc_url=None,
        openapi_url=None if resolved.environment == "production" else "/openapi.json",
        lifespan=lifespan,
    )
    app.state.services = container
    app.include_router(create_router())
    install_exception_handlers(app)
    app.add_middleware(
        PublicSubmissionRateLimitMiddleware,
        limiter=InMemoryRateLimiter(
            limit=resolved.public_rate_limit,
            window_seconds=resolved.public_rate_window_seconds,
            max_keys=resolved.public_rate_limit_max_keys,
        ),
        resolver=ClientIpResolver(
            resolved.trusted_proxy_cidrs,
            client_ip_header=resolved.trusted_client_ip_header,
        ),
    )
    app.add_middleware(BodyCapMiddleware, max_bytes=resolved.overall_body_cap_bytes)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )
    return app


class JsonFormatter(logging.Formatter):
    _standard: ClassVar[set[str]] = {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in self._standard and key not in {"authorization", "token", "query"}:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"), default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").disabled = True


def run() -> None:
    uvicorn.run(
        "alma_api.main:create_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104
        port=8000,
        workers=1,
        access_log=False,
    )


if __name__ == "__main__":
    run()
