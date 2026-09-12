"""FastAPI routes, schemas, and error translation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, cast
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException

from alma_api.application import (
    ApplicationError,
    BudgetExceededError,
    ConcurrencyError,
    CreateResumeDownloadTicket,
    DeliveryService,
    DownloadResume,
    GetLead,
    GetLeadSummary,
    InvalidCursorError,
    LeadSearch,
    NotFoundError,
    SearchLeads,
    SubmitLead,
    SubmitLeadCommand,
    TransitionLead,
    UnitOfWorkFactory,
)
from alma_api.auth import AuthenticationError, SupabaseJwtVerifier
from alma_api.documents import MAX_RESUME_BYTES, validate_resume
from alma_api.domain import (
    AuthenticatedReviewer,
    Delivery,
    DeliveryAttempt,
    DomainError,
    Lead,
    LeadStatus,
)
from alma_api.infrastructure import RateLimitExceeded, TicketError
from alma_api.middleware import RequestBodyTooLarge

logger = logging.getLogger(__name__)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewerResponse(StrictModel):
    id: UUID
    email: str


class DeliveryAttemptResponse(StrictModel):
    id: UUID
    attempt_number: int
    state: str
    outcome: str | None
    trigger: str
    reviewer: ReviewerResponse | None
    attempted_at: datetime
    started_at: datetime
    ended_at: datetime | None
    provider_message_id: str | None
    error: str | None
    sanitized_error: str | None

    @classmethod
    def from_domain(cls, attempt: DeliveryAttempt) -> DeliveryAttemptResponse:
        reviewer_value = (
            ReviewerResponse(
                id=attempt.reviewer.id,
                email=attempt.reviewer.email.value,
            )
            if attempt.reviewer
            else None
        )
        return cls(
            id=attempt.id,
            attempt_number=attempt.attempt_number,
            state=attempt.state.value,
            outcome=attempt.outcome.value if attempt.outcome else None,
            trigger=attempt.trigger.value,
            reviewer=reviewer_value,
            attempted_at=attempt.started_at,
            started_at=attempt.started_at,
            ended_at=attempt.ended_at,
            provider_message_id=attempt.provider_message_id,
            error=attempt.sanitized_error,
            sanitized_error=attempt.sanitized_error,
        )


class DeliveryResponse(StrictModel):
    id: UUID
    kind: str
    delivery_kind: str
    state: str
    attempt_count: int
    manual_retry_count: int
    retry_count: int
    last_attempt_at: datetime | None
    last_error_code: str | None
    last_error: str | None
    provider_message_id: str | None
    provider_accepted: bool
    updated_at: datetime
    attempts: tuple[DeliveryAttemptResponse, ...]

    @classmethod
    def from_domain(
        cls,
        delivery: Delivery,
        attempts: tuple[DeliveryAttempt, ...] = (),
    ) -> DeliveryResponse:
        return cls(
            id=delivery.id,
            kind=delivery.kind.value,
            delivery_kind=delivery.kind.value,
            state=delivery.state.value,
            attempt_count=delivery.attempt_count,
            manual_retry_count=delivery.retry_count,
            retry_count=delivery.retry_count,
            last_attempt_at=delivery.last_attempt_at,
            last_error_code=delivery.last_error,
            last_error=delivery.last_error,
            provider_message_id=delivery.provider_message_id,
            provider_accepted=delivery.state.value == "provider_accepted",
            updated_at=delivery.updated_at,
            attempts=tuple(DeliveryAttemptResponse.from_domain(item) for item in attempts),
        )


class LeadResponse(StrictModel):
    id: UUID
    first_name: str
    last_name: str
    email: str
    resume_filename: str
    resume_media_type: str
    resume_size_bytes: int
    status: LeadStatus
    created_at: datetime
    updated_at: datetime
    reached_out_by: ReviewerResponse | None
    reached_out_at: datetime | None
    deliveries: tuple[DeliveryResponse, ...] | None = None

    @classmethod
    def from_domain(
        cls,
        lead: Lead,
        deliveries: tuple[Delivery, ...] | None = None,
        attempts: tuple[DeliveryAttempt, ...] = (),
    ) -> LeadResponse:
        reviewer = (
            ReviewerResponse(id=lead.reached_out_by.id, email=lead.reached_out_by.email.value)
            if lead.reached_out_by
            else None
        )
        return cls(
            id=lead.id,
            first_name=lead.first_name.value,
            last_name=lead.last_name.value,
            email=lead.email.value,
            resume_filename=lead.resume.original_filename,
            resume_media_type=lead.resume.media_type,
            resume_size_bytes=lead.resume.size_bytes,
            status=lead.status,
            created_at=lead.created_at,
            updated_at=lead.updated_at,
            reached_out_by=reviewer,
            reached_out_at=lead.reached_out_at,
            deliveries=(
                tuple(
                    DeliveryResponse.from_domain(
                        item,
                        tuple(attempt for attempt in attempts if attempt.delivery_id == item.id),
                    )
                    for item in deliveries
                )
                if deliveries is not None
                else None
            ),
        )


class SubmissionResponse(StrictModel):
    id: UUID
    status: LeadStatus
    created_at: datetime


class SearchRequest(StrictModel):
    q: str | None = Field(default=None, max_length=200)
    status: LeadStatus | None = None
    cursor: str | None = Field(default=None, max_length=1024)
    limit: int = Field(default=25, ge=1, le=100)


class SearchResponse(StrictModel):
    items: tuple[LeadResponse, ...]
    next_cursor: str | None


class SummaryResponse(StrictModel):
    total: int
    pending: int
    reached_out: int


class StatusRequest(StrictModel):
    status: LeadStatus


class DownloadTicketResponse(StrictModel):
    url: str
    expires_in_seconds: int = 60


class RetryRequest(StrictModel):
    duplicate_risk_confirmed: bool = False


class VersionResponse(StrictModel):
    commit_sha: str


@dataclass(frozen=True, slots=True)
class Services:
    submit_lead: SubmitLead
    search_leads: SearchLeads
    get_lead: GetLead
    get_summary: GetLeadSummary
    transition_lead: TransitionLead
    create_download_ticket: CreateResumeDownloadTicket
    download_resume: DownloadResume
    delivery_service: DeliveryService
    jwt_verifier: SupabaseJwtVerifier
    uow_factory: UnitOfWorkFactory
    public_api_url: str
    commit_sha: str


def services(request: Request) -> Services:
    return cast(Services, request.app.state.services)


async def reviewer(
    request: Request,
    container: Annotated[Services, Depends(services)],
) -> AuthenticatedReviewer:
    authorization_values = request.headers.getlist("authorization")
    if len(authorization_values) != 1:
        raise AuthenticationError("a bearer token is required")
    scheme, separator, token = authorization_values[0].partition(" ")
    if scheme.lower() != "bearer" or not separator or not token or " " in token:
        raise AuthenticationError("a bearer token is required")
    return await container.jwt_verifier.verify(token)


def create_router() -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/leads", status_code=201, response_model=SubmissionResponse)
    async def submit_lead(
        request: Request,
        container: Annotated[Services, Depends(services)],
    ) -> SubmissionResponse:
        try:
            async with request.form(
                max_files=1,
                max_fields=4,
                max_part_size=MAX_RESUME_BYTES + 1,
            ) as form:
                expected = {
                    "first_name",
                    "last_name",
                    "email",
                    "synthetic_data_acknowledged",
                    "resume",
                }
                items = form.multi_items()
                if {name for name, _ in items} != expected or len(items) != len(expected):
                    raise DomainError(
                        "invalid_multipart_fields",
                        "submit exactly first_name, last_name, email, "
                        "synthetic_data_acknowledged, and one resume",
                    )
                values = dict(items)
                file = values["resume"]
                if not isinstance(file, UploadFile):
                    raise DomainError("invalid_resume", "resume must be one uploaded file")
                text_fields: dict[str, str] = {}
                for name in (
                    "first_name",
                    "last_name",
                    "email",
                    "synthetic_data_acknowledged",
                ):
                    value = values[name]
                    if not isinstance(value, str):
                        raise DomainError(
                            "invalid_multipart_fields",
                            "text fields cannot be files",
                        )
                    text_fields[name] = value
                content = await _read_upload(file)
                validated = validate_resume(content, file.filename or "resume")
                consent = text_fields["synthetic_data_acknowledged"].strip().lower()
                if consent not in {"true", "false"}:
                    raise DomainError(
                        "invalid_acknowledgement",
                        "synthetic_data_acknowledged must be true",
                    )
                lead = await container.submit_lead(
                    SubmitLeadCommand(
                        first_name=text_fields["first_name"],
                        last_name=text_fields["last_name"],
                        email=text_fields["email"],
                        synthetic_data_acknowledged=consent == "true",
                        resume=validated,
                    )
                )
        except HTTPException as exc:
            raise DomainError("invalid_multipart", "multipart body is invalid") from exc
        return SubmissionResponse(id=lead.id, status=lead.status, created_at=lead.created_at)

    @router.get("/api/v1/me", response_model=ReviewerResponse)
    async def me(
        current: Annotated[AuthenticatedReviewer, Depends(reviewer)],
    ) -> ReviewerResponse:
        return ReviewerResponse(id=current.id, email=current.email.value)

    @router.post("/api/v1/leads/search", response_model=SearchResponse)
    async def search_leads(
        body: SearchRequest,
        _: Annotated[AuthenticatedReviewer, Depends(reviewer)],
        container: Annotated[Services, Depends(services)],
    ) -> SearchResponse:
        page = await container.search_leads(
            LeadSearch(q=body.q, status=body.status, cursor=body.cursor, limit=body.limit)
        )
        return SearchResponse(
            items=tuple(LeadResponse.from_domain(item) for item in page.items),
            next_cursor=page.next_cursor,
        )

    @router.get("/api/v1/leads/summary", response_model=SummaryResponse)
    async def lead_summary(
        _: Annotated[AuthenticatedReviewer, Depends(reviewer)],
        container: Annotated[Services, Depends(services)],
    ) -> SummaryResponse:
        summary = await container.get_summary()
        return SummaryResponse(
            total=summary.total,
            pending=summary.pending,
            reached_out=summary.reached_out,
        )

    @router.get("/api/v1/leads/{lead_id}", response_model=LeadResponse)
    async def get_lead(
        lead_id: UUID,
        _: Annotated[AuthenticatedReviewer, Depends(reviewer)],
        container: Annotated[Services, Depends(services)],
    ) -> LeadResponse:
        lead, deliveries, attempts = await container.get_lead(lead_id)
        return LeadResponse.from_domain(lead, deliveries, attempts)

    @router.patch("/api/v1/leads/{lead_id}/status", response_model=LeadResponse)
    async def transition_lead(
        lead_id: UUID,
        body: StatusRequest,
        current: Annotated[AuthenticatedReviewer, Depends(reviewer)],
        container: Annotated[Services, Depends(services)],
    ) -> LeadResponse:
        lead = await container.transition_lead(lead_id, body.status, current)
        return LeadResponse.from_domain(lead)

    @router.post(
        "/api/v1/leads/{lead_id}/resume-download",
        response_model=DownloadTicketResponse,
    )
    async def create_resume_download(
        lead_id: UUID,
        current: Annotated[AuthenticatedReviewer, Depends(reviewer)],
        container: Annotated[Services, Depends(services)],
    ) -> DownloadTicketResponse:
        ticket = await container.create_download_ticket(lead_id, current)
        return DownloadTicketResponse(
            url=(
                f"{container.public_api_url}/api/v1/downloads/resume"
                f"?ticket={quote(ticket, safe='')}"
            )
        )

    @router.get("/api/v1/downloads/resume", name="download_resume")
    async def download_resume(
        container: Annotated[Services, Depends(services)],
        ticket: Annotated[str, Query(min_length=1, max_length=4096)],
    ) -> StreamingResponse:
        _, stored = await container.download_resume(ticket)
        extension = {
            "application/pdf": "pdf",
            "application/msword": "doc",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        }.get(stored.media_type, "bin")
        headers = {
            "Content-Disposition": f'attachment; filename="resume.{extension}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        }
        if stored.size_bytes is not None:
            headers["Content-Length"] = str(stored.size_bytes)
        return StreamingResponse(stored.content, media_type=stored.media_type, headers=headers)

    @router.post(
        "/api/v1/leads/{lead_id}/deliveries/{delivery_id}/retry",
        response_model=DeliveryResponse,
    )
    async def retry_delivery(
        lead_id: UUID,
        delivery_id: UUID,
        body: RetryRequest,
        current: Annotated[AuthenticatedReviewer, Depends(reviewer)],
        container: Annotated[Services, Depends(services)],
    ) -> DeliveryResponse:
        delivery = await container.delivery_service.retry(
            lead_id=lead_id,
            delivery_id=delivery_id,
            reviewer=current,
            duplicate_risk_confirmed=body.duplicate_risk_confirmed,
        )
        return DeliveryResponse.from_domain(delivery)

    @router.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/health/ready")
    async def ready(container: Annotated[Services, Depends(services)]) -> JSONResponse:
        try:
            async with container.uow_factory() as uow:
                await uow.check_connection()
        except Exception:
            return problem_response(
                503,
                "database_unavailable",
                "database readiness check failed",
            )
        return JSONResponse({"status": "ready"})

    @router.get("/version", response_model=VersionResponse)
    async def version(container: Annotated[Services, Depends(services)]) -> VersionResponse:
        return VersionResponse(commit_sha=container.commit_sha)

    return router


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestBodyTooLarge)
    async def body_too_large(_: Request, __: RequestBodyTooLarge) -> JSONResponse:
        return problem_response(413, "request_too_large", "request body is too large")

    @app.exception_handler(AuthenticationError)
    async def authentication_error(_: Request, exc: AuthenticationError) -> JSONResponse:
        return problem_response(
            401,
            exc.code,
            str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.exception_handler(NotFoundError)
    async def not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return problem_response(404, exc.code, str(exc))

    @app.exception_handler(ConcurrencyError)
    async def concurrency_error(_: Request, exc: ConcurrencyError) -> JSONResponse:
        return problem_response(409, exc.code, str(exc))

    @app.exception_handler(TicketError)
    async def ticket_error(_: Request, exc: TicketError) -> JSONResponse:
        return problem_response(401, exc.code, str(exc))

    @app.exception_handler(BudgetExceededError)
    async def budget_error(_: Request, exc: BudgetExceededError) -> JSONResponse:
        return problem_response(429, exc.code, str(exc))

    @app.exception_handler(InvalidCursorError)
    async def cursor_error(_: Request, exc: InvalidCursorError) -> JSONResponse:
        return problem_response(422, exc.code, str(exc))

    @app.exception_handler(RateLimitExceeded)
    async def rate_error(_: Request, exc: RateLimitExceeded) -> JSONResponse:
        return problem_response(
            429,
            exc.code,
            str(exc),
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        conflicts = {
            "invalid_status_transition",
            "delivery_already_accepted",
            "retry_limit_reached",
            "retry_cooldown",
            "delivery_in_progress",
            "delivery_not_retryable",
            "duplicate_risk_confirmation_required",
        }
        return problem_response(409 if exc.code in conflicts else 422, exc.code, exc.message)

    @app.exception_handler(ApplicationError)
    async def application_error(_: Request, exc: ApplicationError) -> JSONResponse:
        return problem_response(422, exc.code, str(exc))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {
                "location": [str(part) for part in item["loc"] if part not in {"body"}],
                "message": item["msg"],
                "type": item["type"],
            }
            for item in exc.errors()
        ]
        return problem_response(
            422, "validation_failed", "request validation failed", errors=errors
        )

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        return problem_response(exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_request_error",
            extra={
                "request_id": getattr(request.state, "request_id", None),
                "error_type": type(exc).__name__,
            },
        )
        return problem_response(500, "internal_error", "an internal error occurred")


def problem_response(
    status: int,
    code: str,
    detail: str,
    *,
    headers: dict[str, str] | None = None,
    errors: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"urn:alma-portal:problem:{code}",
        "title": code.replace("_", " "),
        "status": status,
        "detail": detail,
        "code": code,
    }
    if errors is not None:
        body["errors"] = errors
    return JSONResponse(
        body,
        status_code=status,
        media_type="application/problem+json",
        headers=headers,
    )


async def _read_upload(file: UploadFile) -> bytes:
    parts: list[bytes] = []
    size = 0
    while chunk := await file.read(64 * 1024):
        size += len(chunk)
        if size > MAX_RESUME_BYTES:
            raise DomainError("resume_too_large", "resume must be at most 10 MiB")
        parts.append(chunk)
    return b"".join(parts)
