"""Provider-free domain model for lead management."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

NAME_MAX_LENGTH = 100
EMAIL_MAX_LENGTH = 320
_EMAIL_PATTERN = re.compile(
    r"(?=.{3,320}\Z)[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,63}\Z",
    re.IGNORECASE,
)


class DomainError(Exception):
    """A rule violation safe to map to a problem response."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class LeadStatus(StrEnum):
    PENDING = "PENDING"
    REACHED_OUT = "REACHED_OUT"


class DeliveryKind(StrEnum):
    PROSPECT = "prospect"
    ATTORNEY = "attorney"


class DeliveryState(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    PROVIDER_ACCEPTED = "provider_accepted"
    FAILED = "failed"
    UNKNOWN = "unknown"


class DeliveryTrigger(StrEnum):
    INITIAL = "initial"
    MANUAL = "manual"


class ResumeFormat(StrEnum):
    PDF = "pdf"
    DOC = "doc"
    DOCX = "docx"


@dataclass(frozen=True, slots=True)
class PersonName:
    value: str

    @classmethod
    def parse(cls, raw: str, field: str) -> PersonName:
        value = unicodedata.normalize("NFKC", raw).strip()
        if not value:
            raise DomainError("invalid_name", f"{field} is required")
        if len(value) > NAME_MAX_LENGTH:
            raise DomainError(
                "invalid_name", f"{field} must be at most {NAME_MAX_LENGTH} characters"
            )
        if any(unicodedata.category(character).startswith("C") for character in value):
            raise DomainError("invalid_name", f"{field} contains unsupported characters")
        return cls(value)


@dataclass(frozen=True, slots=True)
class NormalizedEmail:
    value: str

    @classmethod
    def parse(cls, raw: str) -> NormalizedEmail:
        value = unicodedata.normalize("NFKC", raw).strip().lower()
        if len(value) > EMAIL_MAX_LENGTH or not _EMAIL_PATTERN.fullmatch(value):
            raise DomainError("invalid_email", "email is not a valid address")
        return cls(value)


@dataclass(frozen=True, slots=True)
class AuthenticatedReviewer:
    id: UUID
    email: NormalizedEmail


@dataclass(frozen=True, slots=True)
class ResumeMetadata:
    object_key: str
    original_filename: str
    media_type: str
    size_bytes: int
    format: ResumeFormat

    def __post_init__(self) -> None:
        path_parts = self.object_key.split("/")
        object_name = path_parts[2] if len(path_parts) == 3 else ""
        object_id, separator, extension = object_name.rpartition(".")
        if (
            not self.object_key
            or self.object_key.startswith("/")
            or ".." in path_parts
            or len(path_parts) != 3
            or path_parts[0] != "leads"
            or not separator
            or extension != self.format.value
        ):
            raise DomainError("invalid_object_key", "resume object path is invalid")
        try:
            parsed_id = UUID(object_id)
        except ValueError as exc:
            raise DomainError("invalid_object_key", "resume object path is invalid") from exc
        if parsed_id.version != 4:
            raise DomainError("invalid_object_key", "resume object path is invalid")
        if self.size_bytes <= 0:
            raise DomainError("invalid_resume", "resume cannot be empty")


@dataclass(frozen=True, slots=True)
class Lead:
    id: UUID
    first_name: PersonName
    last_name: PersonName
    email: NormalizedEmail
    resume: ResumeMetadata
    status: LeadStatus
    created_at: datetime
    updated_at: datetime
    reached_out_by: AuthenticatedReviewer | None = None
    reached_out_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.resume.object_key.split("/")[1] != str(self.id):
            raise DomainError("invalid_object_key", "resume object path is not bound to lead")

    @classmethod
    def submit(
        cls,
        *,
        first_name: PersonName,
        last_name: PersonName,
        email: NormalizedEmail,
        resume: ResumeMetadata,
        now: datetime,
        lead_id: UUID | None = None,
    ) -> Lead:
        timestamp = require_aware(now)
        return cls(
            id=lead_id or uuid4(),
            first_name=first_name,
            last_name=last_name,
            email=email,
            resume=resume,
            status=LeadStatus.PENDING,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def transition(
        self, target: LeadStatus, reviewer: AuthenticatedReviewer, now: datetime
    ) -> Lead:
        if target is self.status:
            return self
        if self.status is not LeadStatus.PENDING or target is not LeadStatus.REACHED_OUT:
            raise DomainError(
                "invalid_status_transition",
                f"cannot transition lead from {self.status.value} to {target.value}",
            )
        timestamp = require_aware(now)
        return replace(
            self,
            status=target,
            reached_out_by=reviewer,
            reached_out_at=timestamp,
            updated_at=timestamp,
        )


@dataclass(frozen=True, slots=True)
class Delivery:
    id: UUID
    lead_id: UUID
    kind: DeliveryKind
    recipient_email: NormalizedEmail
    state: DeliveryState
    active_attempt_id: UUID | None
    active_claim_token: UUID | None
    claimed_at: datetime | None
    claim_expires_at: datetime | None
    retry_count: int
    last_attempt_at: datetime | None
    provider_message_id: str | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    @property
    def attempt_count(self) -> int:
        return self.retry_count + (1 if self.last_attempt_at is not None else 0)


@dataclass(frozen=True, slots=True)
class DeliveryAttempt:
    id: UUID
    delivery_id: UUID
    attempt_number: int
    trigger: DeliveryTrigger
    reviewer: AuthenticatedReviewer | None
    started_at: datetime
    ended_at: datetime | None
    http_status: int | None
    outcome: DeliveryState | None
    provider_message_id: str | None
    sanitized_error: str | None

    @property
    def state(self) -> DeliveryState:
        return self.outcome or DeliveryState.PROCESSING


@dataclass(frozen=True, slots=True)
class DeliveryClaim:
    delivery_id: UUID
    attempt_id: UUID
    token: UUID
    lead_id: UUID
    kind: DeliveryKind
    recipient_email: NormalizedEmail
    trigger: DeliveryTrigger


@dataclass(frozen=True, slots=True)
class MailMessage:
    recipient: NormalizedEmail
    subject: str
    plain_body: str
    html_body: str


@dataclass(frozen=True, slots=True)
class MailResult:
    state: DeliveryState
    http_status: int | None
    provider_message_id: str | None = None
    sanitized_error: str | None = None

    def __post_init__(self) -> None:
        if self.state in {DeliveryState.PENDING, DeliveryState.PROCESSING}:
            raise DomainError("invalid_mail_result", "mail result must be a terminal state")
        if self.state is DeliveryState.PROVIDER_ACCEPTED:
            if self.http_status is None or not 200 <= self.http_status <= 299:
                raise DomainError("invalid_mail_result", "accepted mail requires a 2xx status")
            if not self.provider_message_id:
                raise DomainError("invalid_mail_result", "accepted mail requires a provider ID")
        elif not self.sanitized_error:
            raise DomainError("invalid_mail_result", "failed mail requires a sanitized error")


@dataclass(frozen=True, slots=True)
class LeadSummary:
    total: int
    pending: int
    reached_out: int


def resume_format_from_media_type(media_type: str) -> ResumeFormat:
    formats = {
        "application/pdf": ResumeFormat.PDF,
        "application/msword": ResumeFormat.DOC,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
            ResumeFormat.DOCX
        ),
    }
    try:
        return formats[media_type]
    except KeyError as exc:
        raise DomainError(
            "invalid_resume_media_type", "stored resume media type is invalid"
        ) from exc


def require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainError("invalid_timestamp", "timestamp must include a timezone")
    return value.astimezone(UTC)
