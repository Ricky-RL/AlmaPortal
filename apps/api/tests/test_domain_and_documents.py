from __future__ import annotations

import io
import zipfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from alma_api.documents import MAX_DOCX_ENTRIES, MAX_RESUME_BYTES, validate_resume
from alma_api.domain import (
    COMMENTS_MAX_LENGTH,
    AuthenticatedReviewer,
    Delivery,
    DeliveryKind,
    DeliveryState,
    DomainError,
    Lead,
    LeadStatus,
    NormalizedEmail,
    PersonName,
    ResumeFormat,
    ResumeMetadata,
    parse_optional_comments,
    resume_format_from_media_type,
)

NOW = datetime(2026, 1, 2, 12, tzinfo=UTC)


def make_lead() -> Lead:
    lead_id = uuid4()
    return Lead.submit(
        first_name=PersonName.parse(" Ada ", "first_name"),
        last_name=PersonName.parse("Lovelace", "last_name"),
        email=NormalizedEmail.parse(" ADA@Example.COM "),
        resume=ResumeMetadata(
            object_key=f"leads/{lead_id}/{uuid4()}.pdf",
            original_filename="resume.pdf",
            media_type="application/pdf",
            size_bytes=5,
            format=ResumeFormat.PDF,
        ),
        now=NOW,
        lead_id=lead_id,
    )


def reviewer() -> AuthenticatedReviewer:
    return AuthenticatedReviewer(uuid4(), NormalizedEmail.parse("reviewer@example.com"))


def make_delivery(**changes: object) -> Delivery:
    base = Delivery(
        id=uuid4(),
        lead_id=uuid4(),
        kind=DeliveryKind.PROSPECT,
        recipient_email=NormalizedEmail.parse("lead@example.com"),
        state=DeliveryState.FAILED,
        active_attempt_id=None,
        active_claim_token=None,
        claimed_at=None,
        claim_expires_at=None,
        retry_count=0,
        last_attempt_at=NOW - timedelta(minutes=2),
        provider_message_id=None,
        last_error="sendgrid_retryable_500",
        created_at=NOW - timedelta(minutes=3),
        updated_at=NOW,
    )
    return replace(base, **changes)


def test_lead_transition_is_idempotent_and_reversal_is_rejected() -> None:
    pending = make_lead()
    reached = pending.transition(LeadStatus.REACHED_OUT, reviewer(), NOW + timedelta(seconds=1))
    assert reached.status is LeadStatus.REACHED_OUT
    assert (
        reached.transition(LeadStatus.REACHED_OUT, reviewer(), NOW + timedelta(seconds=2))
        is reached
    )
    with pytest.raises(DomainError, match="cannot transition"):
        reached.transition(LeadStatus.PENDING, reviewer(), NOW + timedelta(seconds=3))


def test_names_and_email_are_trimmed_normalized_and_bounded() -> None:
    lead = make_lead()
    assert lead.first_name.value == "Ada"
    assert lead.email.value == "ada@example.com"
    with pytest.raises(DomainError):
        PersonName.parse("x" * 101, "first_name")
    with pytest.raises(DomainError):
        PersonName.parse("bad\x00name", "first_name")
    with pytest.raises(DomainError):
        NormalizedEmail.parse("not-an-address")


def test_optional_comments_are_trimmed_bounded_and_reject_controls() -> None:
    assert parse_optional_comments(None) is None
    assert parse_optional_comments("   ") is None
    assert parse_optional_comments("  Please review visa timing.  ") == (
        "Please review visa timing."
    )
    assert parse_optional_comments("Line one\nLine two") == "Line one\nLine two"
    with pytest.raises(DomainError, match="at most"):
        parse_optional_comments("x" * (COMMENTS_MAX_LENGTH + 1))
    with pytest.raises(DomainError, match="unsupported"):
        parse_optional_comments("bad\x00comment")


def test_canonical_delivery_values_and_mime_derived_format() -> None:
    assert {kind.value for kind in DeliveryKind} == {"prospect", "attorney"}
    assert {state.value for state in DeliveryState} == {
        "pending",
        "processing",
        "provider_accepted",
        "failed",
        "unknown",
    }
    assert resume_format_from_media_type("application/pdf") is ResumeFormat.PDF
    assert resume_format_from_media_type("application/msword") is ResumeFormat.DOC


def test_pdf_doc_and_docx_magic_are_validated() -> None:
    assert validate_resume(b"%PDF-1.7\n", "r.pdf").format is ResumeFormat.PDF
    assert (
        validate_resume(bytes.fromhex("D0CF11E0A1B11AE1") + b"data", "r.doc").format
        is ResumeFormat.DOC
    )
    assert validate_resume(docx_bytes(), "r.docx").format is ResumeFormat.DOCX
    with pytest.raises(DomainError) as unsupported:
        validate_resume(b"pretend pdf", "r.pdf")
    assert unsupported.value.code == "unsupported_resume_format"


def test_resume_size_and_docx_required_entries_are_enforced() -> None:
    with pytest.raises(DomainError) as too_large:
        validate_resume(b"%PDF-" + b"x" * MAX_RESUME_BYTES, "r.pdf")
    assert too_large.value.code == "resume_too_large"

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "types")
    with pytest.raises(DomainError) as missing:
        validate_resume(output.getvalue(), "r.docx")
    assert missing.value.code == "invalid_docx"


def test_docx_entry_count_and_expansion_ratio_are_bounded() -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "types")
        archive.writestr("word/document.xml", "document")
        for index in range(MAX_DOCX_ENTRIES):
            archive.writestr(f"word/item-{index}.xml", "x")
    with pytest.raises(DomainError) as entries:
        validate_resume(output.getvalue(), "r.docx")
    assert entries.value.code == "unsafe_docx"

    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "types")
        archive.writestr("word/document.xml", "0" * 100_000)
    with pytest.raises(DomainError) as ratio:
        validate_resume(bomb.getvalue(), "r.docx")
    assert ratio.value.code == "unsafe_docx"


def docx_bytes() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "types")
        archive.writestr("word/document.xml", "document")
    return output.getvalue()
