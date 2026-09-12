"""Application use cases and narrow ports."""

from __future__ import annotations

import base64
import binascii
import json
import logging
import re
import time
import unicodedata
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID, uuid4

from alma_api.domain import (
    AuthenticatedReviewer,
    Delivery,
    DeliveryAttempt,
    DeliveryClaim,
    DeliveryKind,
    DeliveryState,
    DomainError,
    Lead,
    LeadStatus,
    LeadSummary,
    MailMessage,
    MailResult,
    NormalizedEmail,
    PersonName,
    ResumeFormat,
    ResumeMetadata,
    parse_optional_comments,
)

logger = logging.getLogger(__name__)


class ApplicationError(Exception):
    """Base class for use-case failures."""

    code = "application_error"


class NotFoundError(ApplicationError):
    code = "not_found"


class ConcurrencyError(ApplicationError):
    code = "concurrency_conflict"


class BudgetExceededError(ApplicationError):
    code = "budget_exceeded"


class InvalidCursorError(ApplicationError):
    code = "invalid_cursor"


class DependencyUnavailableError(ApplicationError):
    code = "dependency_unavailable"


class ClaimReconciliation(StrEnum):
    NOT_PROCESSING = "not_processing"
    ACTIVE_LEASE = "active_lease"
    EXPIRED_TO_UNKNOWN = "expired_to_unknown"


@dataclass(frozen=True, slots=True)
class ValidatedResume:
    content: bytes
    original_filename: str
    media_type: str
    format: ResumeFormat


@dataclass(frozen=True, slots=True)
class SubmitLeadCommand:
    first_name: str
    last_name: str
    email: str
    synthetic_data_acknowledged: bool
    resume: ValidatedResume
    comments: str | None = None


@dataclass(frozen=True, slots=True)
class LeadSearch:
    q: str | None
    status: LeadStatus | None
    cursor: str | None
    limit: int


@dataclass(frozen=True, slots=True)
class CursorPosition:
    created_at: datetime
    lead_id: UUID


@dataclass(frozen=True, slots=True)
class LeadPage:
    items: tuple[Lead, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class EmailBudget:
    budget_date: date
    new_lead_credit_limit: int
    new_lead_credits_used: int
    new_lead_credits_remaining: int
    retry_credit_limit: int
    retry_credits_used: int
    retry_credits_remaining: int


@dataclass(frozen=True, slots=True)
class DemoCapacity:
    lead_limit: int
    lead_count: int
    lead_slots_remaining: int
    resume_byte_limit: int
    resume_bytes: int
    resume_bytes_remaining: int


@dataclass(frozen=True, slots=True)
class DownloadGrant:
    lead_id: UUID
    reviewer_id: UUID
    object_key: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class StoredObject:
    content: AsyncIterator[bytes]
    media_type: str
    size_bytes: int | None


class Clock(Protocol):
    def now(self) -> datetime: ...


class ObjectStorage(Protocol):
    async def upload(self, key: str, content: bytes, media_type: str) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def open(self, key: str) -> StoredObject: ...

    def list_keys(self, prefix: str) -> AsyncIterator[str]: ...


class Mailer(Protocol):
    async def send(self, message: MailMessage) -> MailResult: ...


class TicketSigner(Protocol):
    def issue(self, grant: DownloadGrant) -> str: ...

    def verify(self, token: str, now: datetime) -> DownloadGrant: ...


class LeadRepository(Protocol):
    async def create_with_deliveries(
        self,
        lead: Lead,
        *,
        prospect_recipient: NormalizedEmail,
        attorney_recipient: NormalizedEmail,
    ) -> Lead: ...

    async def get(self, lead_id: UUID) -> Lead | None: ...

    async def mark_reached_out(self, lead_id: UUID, reviewer: AuthenticatedReviewer) -> Lead: ...

    async def search(
        self,
        *,
        q: str | None,
        status: LeadStatus | None,
        after: CursorPosition | None,
        limit: int,
    ) -> tuple[Lead, ...]: ...

    async def summary(self) -> LeadSummary: ...


class DeliveryRepository(Protocol):
    async def get(self, delivery_id: UUID) -> Delivery | None: ...

    async def list_for_lead(self, lead_id: UUID) -> tuple[Delivery, ...]: ...

    async def list_attempts_for_lead(self, lead_id: UUID) -> tuple[DeliveryAttempt, ...]: ...

    async def claim_initial(self, delivery_id: UUID) -> DeliveryClaim | None: ...

    async def reconcile_claim(self, delivery_id: UUID) -> ClaimReconciliation: ...

    async def claim_manual(
        self,
        delivery_id: UUID,
        *,
        reviewer: AuthenticatedReviewer,
        duplicate_risk_confirmed: bool,
    ) -> DeliveryClaim: ...

    async def complete(self, claim: DeliveryClaim, result: MailResult) -> bool: ...


class BudgetRepository(Protocol):
    async def reserve_new_lead(self, reservation_key: UUID) -> None: ...

    async def current_email_budget(self) -> EmailBudget: ...

    async def current_capacity(self) -> DemoCapacity: ...


class UnitOfWork(Protocol):
    leads: LeadRepository
    deliveries: DeliveryRepository
    budgets: BudgetRepository

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...

    async def check_connection(self) -> None: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> UnitOfWork: ...


class CursorCodec:
    """Opaque, non-authorizing search cursor."""

    @staticmethod
    def encode(position: CursorPosition) -> str:
        raw = json.dumps(
            {
                "created_at": position.created_at.astimezone(UTC).isoformat(),
                "id": str(position.lead_id),
            },
            separators=(",", ":"),
        ).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    @staticmethod
    def decode(value: str | None) -> CursorPosition | None:
        if value is None:
            return None
        try:
            padded = value + "=" * (-len(value) % 4)
            payload = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True))
            if set(payload) != {"created_at", "id"}:
                raise ValueError
            created_at = datetime.fromisoformat(payload["created_at"]).astimezone(UTC)
            return CursorPosition(created_at=created_at, lead_id=UUID(payload["id"]))
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, binascii.Error) as exc:
            raise InvalidCursorError("cursor is malformed") from exc


class EmailComposer:
    def __init__(self, attorney_email: NormalizedEmail) -> None:
        self._attorney_email = attorney_email

    @property
    def attorney_email(self) -> NormalizedEmail:
        return self._attorney_email

    def delivery_recipient(self, kind: DeliveryKind, lead: Lead) -> NormalizedEmail:
        if kind is DeliveryKind.PROSPECT:
            return lead.email
        return self._attorney_email

    def compose(self, kind: DeliveryKind, lead: Lead) -> MailMessage:
        name = lead.first_name.value
        if kind is DeliveryKind.PROSPECT:
            return MailMessage(
                recipient=lead.email,
                subject="We received your Alma inquiry",
                plain_body=(
                    f"Hello {name},\n\n"
                    "We received your information and resume. An Alma reviewer will follow up."
                ),
                html_body=(
                    f"<p>Hello {escape_html(name)},</p>"
                    "<p>We received your information and resume. "
                    "An Alma reviewer will follow up.</p>"
                ),
            )
        full_name = f"{lead.first_name.value} {lead.last_name.value}"
        comments_plain = ""
        comments_html = ""
        if lead.comments:
            comments_plain = f"\n\nAdditional comments:\n{lead.comments}"
            comments_html = (
                "<p>Additional comments:</p>"
                f"<p>{escape_html(lead.comments).replace(chr(10), '<br>')}</p>"
            )
        return MailMessage(
            recipient=self._attorney_email,
            subject="New AlmaPortal lead",
            plain_body=(
                f"A new lead was submitted by {full_name} ({lead.email.value}). "
                "Review the lead in AlmaPortal. The resume is not attached."
                f"{comments_plain}"
            ),
            html_body=(
                f"<p>A new lead was submitted by {escape_html(full_name)} "
                f"({escape_html(lead.email.value)}).</p>"
                "<p>Review the lead in AlmaPortal. The resume is not attached.</p>"
                f"{comments_html}"
            ),
        )


class DeliveryService:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        mailer: Mailer,
        composer: EmailComposer,
    ) -> None:
        self._uow_factory = uow_factory
        self._mailer = mailer
        self._composer = composer

    async def send_initial(self, lead: Lead, delivery_id: UUID) -> None:
        async with self._uow_factory() as uow:
            claim = await uow.deliveries.claim_initial(delivery_id)
            await uow.commit()
        if claim is not None:
            await self._send_claim(lead, claim)

    async def retry(
        self,
        *,
        lead_id: UUID,
        delivery_id: UUID,
        reviewer: AuthenticatedReviewer,
        duplicate_risk_confirmed: bool,
    ) -> Delivery:
        async with self._uow_factory() as uow:
            lead = await uow.leads.get(lead_id)
            if lead is None:
                raise NotFoundError("lead was not found")
            delivery = await uow.deliveries.get(delivery_id)
            if delivery is None or delivery.lead_id != lead_id:
                raise NotFoundError("delivery was not found for this lead")
            reconciliation = await uow.deliveries.reconcile_claim(delivery_id)
            await uow.commit()

        if reconciliation is ClaimReconciliation.ACTIVE_LEASE:
            raise DomainError("delivery_in_progress", "a delivery attempt is already in progress")

        async with self._uow_factory() as uow:
            delivery = await uow.deliveries.get(delivery_id)
            if delivery is None or delivery.lead_id != lead_id:
                raise NotFoundError("delivery was not found for this lead")
            if delivery.state is DeliveryState.PENDING:
                claim = await uow.deliveries.claim_initial(delivery_id)
                if claim is None:
                    raise ConcurrencyError("initial delivery claim is no longer available")
            else:
                claim = await uow.deliveries.claim_manual(
                    delivery_id,
                    reviewer=reviewer,
                    duplicate_risk_confirmed=duplicate_risk_confirmed,
                )
            if claim.lead_id != lead_id:
                raise NotFoundError("delivery was not found for this lead")
            await uow.commit()

        await self._send_claim(lead, claim)
        async with self._uow_factory() as uow:
            deliveries = await uow.deliveries.list_for_lead(lead_id)
        try:
            return next(item for item in deliveries if item.id == delivery_id)
        except StopIteration as exc:
            raise NotFoundError("delivery was not found after retry") from exc

    async def _send_claim(self, lead: Lead, claim: DeliveryClaim) -> None:
        started = time.monotonic()
        composed = self._composer.compose(claim.kind, lead)
        message = MailMessage(
            recipient=claim.recipient_email,
            subject=composed.subject,
            plain_body=composed.plain_body,
            html_body=composed.html_body,
        )
        result = await self._mailer.send(message)
        async with self._uow_factory() as uow:
            completion_applied = await uow.deliveries.complete(claim, result)
            await uow.commit()
        logger.info(
            "delivery_attempt_completed",
            extra={
                "attempt_id": str(claim.attempt_id),
                "delivery_kind": claim.kind.value,
                "outcome": result.state.value,
                "provider_status": result.http_status,
                "completion_applied": completion_applied,
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
            },
        )


class SubmitLead:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        storage: ObjectStorage,
        delivery_service: DeliveryService,
        composer: EmailComposer,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._storage = storage
        self._delivery_service = delivery_service
        self._composer = composer
        self._clock = clock

    async def __call__(self, command: SubmitLeadCommand) -> Lead:
        if not command.synthetic_data_acknowledged:
            raise ApplicationError("synthetic-data acknowledgement is required")
        lead_id = uuid4()
        object_path = f"leads/{lead_id}/{uuid4()}.{command.resume.format.value}"
        submitted = Lead.submit(
            first_name=PersonName.parse(command.first_name, "first_name"),
            last_name=PersonName.parse(command.last_name, "last_name"),
            email=NormalizedEmail.parse(command.email),
            resume=ResumeMetadata(
                object_key=object_path,
                original_filename=safe_filename(command.resume.original_filename),
                media_type=command.resume.media_type,
                size_bytes=len(command.resume.content),
                format=command.resume.format,
            ),
            now=self._clock.now(),
            lead_id=lead_id,
            comments=parse_optional_comments(command.comments),
        )
        uploaded = False
        try:
            async with self._uow_factory() as uow:
                await uow.budgets.reserve_new_lead(lead_id)
                await uow.commit()
            await self._storage.upload(
                object_path, command.resume.content, command.resume.media_type
            )
            uploaded = True
            async with self._uow_factory() as uow:
                created = await uow.leads.create_with_deliveries(
                    submitted,
                    prospect_recipient=submitted.email,
                    attorney_recipient=self._composer.attorney_email,
                )
                await uow.commit()
        except Exception:
            if uploaded:
                try:
                    await self._storage.delete(object_path)
                except Exception as compensation_error:
                    logger.exception(
                        "resume_storage_compensation_failed",
                        extra={
                            "lead_id": str(lead_id),
                            "error_type": type(compensation_error).__name__,
                        },
                    )
            raise

        async with self._uow_factory() as uow:
            deliveries = await uow.deliveries.list_for_lead(created.id)
        for delivery in deliveries:
            try:
                await self._delivery_service.send_initial(created, delivery.id)
            except Exception as delivery_error:
                logger.exception(
                    "initial_delivery_attempt_failed",
                    extra={
                        "lead_id": str(created.id),
                        "delivery_kind": delivery.kind.value,
                        "error_type": type(delivery_error).__name__,
                    },
                )
        return created


class SearchLeads:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def __call__(self, query: LeadSearch) -> LeadPage:
        if not 1 <= query.limit <= 100:
            raise ApplicationError("limit must be between 1 and 100")
        q = query.q.strip() if query.q else None
        after = CursorCodec.decode(query.cursor)
        async with self._uow_factory() as uow:
            rows = await uow.leads.search(
                q=q or None,
                status=query.status,
                after=after,
                limit=query.limit + 1,
            )
        items = rows[: query.limit]
        cursor = None
        if len(rows) > query.limit and items:
            last = items[-1]
            cursor = CursorCodec.encode(CursorPosition(last.created_at, last.id))
        return LeadPage(items=items, next_cursor=cursor)


class GetLead:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def __call__(
        self, lead_id: UUID
    ) -> tuple[Lead, tuple[Delivery, ...], tuple[DeliveryAttempt, ...]]:
        async with self._uow_factory() as uow:
            lead = await uow.leads.get(lead_id)
            if lead is None:
                raise NotFoundError("lead was not found")
            deliveries = await uow.deliveries.list_for_lead(lead_id)
            attempts = await uow.deliveries.list_attempts_for_lead(lead_id)
        return lead, deliveries, attempts


class GetLeadSummary:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def __call__(self) -> LeadSummary:
        async with self._uow_factory() as uow:
            return await uow.leads.summary()


class TransitionLead:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def __call__(
        self, lead_id: UUID, target: LeadStatus, reviewer: AuthenticatedReviewer
    ) -> Lead:
        if target is not LeadStatus.REACHED_OUT:
            raise ApplicationError("status target must be REACHED_OUT")
        async with self._uow_factory() as uow:
            lead = await uow.leads.mark_reached_out(lead_id, reviewer)
            await uow.commit()
            return lead


class CreateResumeDownloadTicket:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        signer: TicketSigner,
        clock: Clock,
        ttl: timedelta = timedelta(seconds=60),
    ) -> None:
        self._uow_factory = uow_factory
        self._signer = signer
        self._clock = clock
        self._ttl = ttl

    async def __call__(self, lead_id: UUID, reviewer: AuthenticatedReviewer) -> str:
        async with self._uow_factory() as uow:
            lead = await uow.leads.get(lead_id)
            if lead is None:
                raise NotFoundError("lead was not found")
        now = self._clock.now()
        return self._signer.issue(
            DownloadGrant(
                lead_id=lead.id,
                reviewer_id=reviewer.id,
                object_key=lead.resume.object_key,
                expires_at=now + self._ttl,
            )
        )


class DownloadResume:
    def __init__(self, signer: TicketSigner, storage: ObjectStorage, clock: Clock) -> None:
        self._signer = signer
        self._storage = storage
        self._clock = clock

    async def __call__(self, token: str) -> tuple[DownloadGrant, StoredObject]:
        grant = self._signer.verify(token, self._clock.now())
        return grant, await self._storage.open(grant.object_key)


def safe_filename(value: str) -> str:
    leaf = unicodedata.normalize("NFKD", value.replace("\\", "/").split("/")[-1].strip())
    ascii_leaf = leaf.encode("ascii", "ignore").decode()
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_leaf).strip("._-")
    if not cleaned:
        cleaned = "resume"
    if not cleaned[0].isalnum():
        cleaned = f"resume_{cleaned}"
    return cleaned[:180]


def escape_html(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )
