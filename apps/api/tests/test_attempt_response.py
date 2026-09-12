from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from alma_api.domain import (
    AuthenticatedReviewer,
    Delivery,
    DeliveryAttempt,
    DeliveryKind,
    DeliveryState,
    DeliveryTrigger,
    Lead,
    LeadStatus,
    NormalizedEmail,
    PersonName,
    ResumeFormat,
    ResumeMetadata,
)
from alma_api.presentation import LeadResponse

NOW = datetime(2026, 8, 1, 12, tzinfo=UTC)


def test_protected_detail_nests_tolerant_attempt_history_shape() -> None:
    lead_id = uuid4()
    delivery_id = uuid4()
    reviewer = AuthenticatedReviewer(uuid4(), NormalizedEmail("reviewer@example.com"))
    lead = Lead(
        id=lead_id,
        first_name=PersonName("Ada"),
        last_name=PersonName("Lovelace"),
        email=NormalizedEmail("ada@example.com"),
        resume=ResumeMetadata(
            object_key=f"leads/{lead_id}/{uuid4()}.pdf",
            original_filename="resume.pdf",
            media_type="application/pdf",
            size_bytes=100,
            format=ResumeFormat.PDF,
        ),
        status=LeadStatus.PENDING,
        created_at=NOW,
        updated_at=NOW,
    )
    delivery = Delivery(
        id=delivery_id,
        lead_id=lead_id,
        kind=DeliveryKind.ATTORNEY,
        recipient_email=NormalizedEmail("attorney@example.com"),
        state=DeliveryState.FAILED,
        active_attempt_id=None,
        active_claim_token=None,
        claimed_at=None,
        claim_expires_at=None,
        retry_count=0,
        last_attempt_at=NOW + timedelta(seconds=1),
        provider_message_id=None,
        last_error="resend_rejected_400",
        created_at=NOW,
        updated_at=NOW + timedelta(seconds=1),
    )
    attempt = DeliveryAttempt(
        id=uuid4(),
        delivery_id=delivery_id,
        attempt_number=1,
        trigger=DeliveryTrigger.INITIAL,
        reviewer=reviewer,
        started_at=NOW,
        ended_at=NOW + timedelta(seconds=1),
        http_status=400,
        outcome=DeliveryState.FAILED,
        provider_message_id=None,
        sanitized_error="resend_rejected_400",
    )
    payload = LeadResponse.from_domain(lead, (delivery,), (attempt,)).model_dump(mode="json")
    projected = payload["deliveries"][0]
    assert projected["kind"] == "attorney"
    assert projected["state"] == "failed"
    assert projected["attempt_count"] == 1
    history = projected["attempts"][0]
    assert history["state"] == "failed"
    assert history["attempted_at"] == history["started_at"]
    assert history["error"] == history["sanitized_error"]
    assert history["trigger"] == "initial"
    assert history["reviewer"]["email"] == "reviewer@example.com"
