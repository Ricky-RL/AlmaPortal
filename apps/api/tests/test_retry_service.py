from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from alma_api.application import ClaimReconciliation, DeliveryService, EmailComposer
from alma_api.domain import (
    AuthenticatedReviewer,
    Delivery,
    DeliveryClaim,
    DeliveryKind,
    DeliveryState,
    DeliveryTrigger,
    DomainError,
    Lead,
    LeadStatus,
    MailMessage,
    MailResult,
    NormalizedEmail,
    PersonName,
    ResumeFormat,
    ResumeMetadata,
)

NOW = datetime(2026, 9, 12, 12, tzinfo=UTC)


def make_lead() -> Lead:
    lead_id = uuid4()
    return Lead(
        id=lead_id,
        first_name=PersonName("Ada"),
        last_name=PersonName("Lovelace"),
        email=NormalizedEmail("ada@example.com"),
        resume=ResumeMetadata(
            object_key=f"leads/{lead_id}/{uuid4()}.pdf",
            original_filename="resume.pdf",
            media_type="application/pdf",
            size_bytes=10,
            format=ResumeFormat.PDF,
        ),
        status=LeadStatus.PENDING,
        created_at=NOW,
        updated_at=NOW,
    )


def make_delivery(lead_id: UUID, state: DeliveryState) -> Delivery:
    processing = state is DeliveryState.PROCESSING
    return Delivery(
        id=uuid4(),
        lead_id=lead_id,
        kind=DeliveryKind.PROSPECT,
        recipient_email=NormalizedEmail("ada@example.com"),
        state=state,
        active_attempt_id=uuid4() if processing else None,
        active_claim_token=uuid4() if processing else None,
        claimed_at=NOW - timedelta(minutes=6) if processing else None,
        claim_expires_at=NOW - timedelta(minutes=1) if processing else None,
        retry_count=0,
        last_attempt_at=NOW - timedelta(minutes=6) if processing else None,
        provider_message_id=None,
        last_error=None,
        created_at=NOW - timedelta(minutes=10),
        updated_at=NOW,
    )


class RetryLeads:
    def __init__(self, lead: Lead) -> None:
        self.lead = lead

    async def get(self, lead_id: UUID) -> Lead | None:
        return self.lead if lead_id == self.lead.id else None


class RetryDeliveries:
    def __init__(self, delivery: Delivery) -> None:
        self.delivery = delivery
        self.initial_claims = 0
        self.manual_claims = 0
        self.cooldown_elapsed = False

    async def get(self, delivery_id: UUID) -> Delivery | None:
        return self.delivery if delivery_id == self.delivery.id else None

    async def list_for_lead(self, lead_id: UUID) -> tuple[Delivery, ...]:
        return (self.delivery,) if lead_id == self.delivery.lead_id else ()

    async def reconcile_claim(self, delivery_id: UUID) -> ClaimReconciliation:
        assert delivery_id == self.delivery.id
        if self.delivery.state is not DeliveryState.PROCESSING:
            return ClaimReconciliation.NOT_PROCESSING
        if self.delivery.claim_expires_at and self.delivery.claim_expires_at > NOW:
            return ClaimReconciliation.ACTIVE_LEASE
        self.delivery = replace(
            self.delivery,
            state=DeliveryState.UNKNOWN,
            active_attempt_id=None,
            active_claim_token=None,
            claimed_at=None,
            claim_expires_at=None,
            last_error="claim expired before a confirmed provider outcome",
        )
        return ClaimReconciliation.EXPIRED_TO_UNKNOWN

    async def claim_initial(self, delivery_id: UUID) -> DeliveryClaim | None:
        self.initial_claims += 1
        return self._claim(delivery_id, DeliveryTrigger.INITIAL)

    async def claim_manual(
        self,
        delivery_id: UUID,
        *,
        reviewer: AuthenticatedReviewer,
        duplicate_risk_confirmed: bool,
    ) -> DeliveryClaim:
        del reviewer
        self.manual_claims += 1
        if self.delivery.state is DeliveryState.UNKNOWN and not duplicate_risk_confirmed:
            raise DomainError(
                "duplicate_risk_confirmation_required",
                "confirm duplicate-delivery risk",
            )
        if not self.cooldown_elapsed:
            raise DomainError("retry_cooldown", "delivery retry cooldown has not elapsed")
        return self._claim(delivery_id, DeliveryTrigger.MANUAL)

    async def complete(self, _: DeliveryClaim, result: MailResult) -> bool:
        self.delivery = replace(
            self.delivery,
            state=result.state,
            active_attempt_id=None,
            active_claim_token=None,
            claimed_at=None,
            claim_expires_at=None,
            provider_message_id=result.provider_message_id,
            last_error=result.sanitized_error,
        )
        return True

    def _claim(self, delivery_id: UUID, trigger: DeliveryTrigger) -> DeliveryClaim:
        assert delivery_id == self.delivery.id
        attempt_id = uuid4()
        token = uuid4()
        self.delivery = replace(
            self.delivery,
            state=DeliveryState.PROCESSING,
            active_attempt_id=attempt_id,
            active_claim_token=token,
            claimed_at=NOW,
            claim_expires_at=NOW + timedelta(minutes=5),
            retry_count=self.delivery.retry_count + (trigger is DeliveryTrigger.MANUAL),
            last_attempt_at=NOW,
        )
        return DeliveryClaim(
            delivery_id=delivery_id,
            attempt_id=attempt_id,
            token=token,
            lead_id=self.delivery.lead_id,
            kind=self.delivery.kind,
            recipient_email=self.delivery.recipient_email,
            trigger=trigger,
        )


class RetryUow:
    def __init__(
        self,
        leads: RetryLeads,
        deliveries: RetryDeliveries,
        commits: list[str],
    ) -> None:
        self.leads = leads
        self.deliveries = deliveries
        self.commits = commits

    async def __aenter__(self) -> RetryUow:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def commit(self) -> None:
        self.commits.append("commit")


class UnusedMailer:
    async def send(self, _: object) -> object:
        raise AssertionError("send is replaced in these unit tests")


class AcceptedMailer:
    async def send(self, _: MailMessage) -> MailResult:
        return MailResult(
            state=DeliveryState.PROVIDER_ACCEPTED,
            http_status=202,
            provider_message_id="provider-id",
        )


def service_for(
    lead: Lead,
    deliveries: RetryDeliveries,
) -> tuple[DeliveryService, list[str]]:
    commits: list[str] = []
    leads = RetryLeads(lead)
    service = DeliveryService(
        uow_factory=lambda: RetryUow(leads, deliveries, commits),  # type: ignore[arg-type]
        mailer=UnusedMailer(),  # type: ignore[arg-type]
        composer=object(),  # type: ignore[arg-type]
    )
    service._send_claim = AsyncMock()  # type: ignore[method-assign]
    return service, commits


@pytest.mark.asyncio
async def test_expired_reconciliation_commits_before_confirmation_then_retry_claims() -> None:
    lead = make_lead()
    deliveries = RetryDeliveries(make_delivery(lead.id, DeliveryState.PROCESSING))
    service, commits = service_for(lead, deliveries)
    reviewer = AuthenticatedReviewer(uuid4(), NormalizedEmail("reviewer@example.com"))

    with pytest.raises(DomainError) as confirmation:
        await service.retry(
            lead_id=lead.id,
            delivery_id=deliveries.delivery.id,
            reviewer=reviewer,
            duplicate_risk_confirmed=False,
        )
    assert confirmation.value.code == "duplicate_risk_confirmation_required"
    assert deliveries.delivery.state is DeliveryState.UNKNOWN
    assert commits == ["commit"]

    deliveries.cooldown_elapsed = True
    result = await service.retry(
        lead_id=lead.id,
        delivery_id=deliveries.delivery.id,
        reviewer=reviewer,
        duplicate_risk_confirmed=True,
    )
    assert result.state is DeliveryState.PROCESSING
    assert deliveries.manual_claims == 2
    assert commits == ["commit", "commit", "commit"]


@pytest.mark.asyncio
async def test_pending_delivery_uses_initial_claim_without_manual_retry_budget() -> None:
    lead = make_lead()
    deliveries = RetryDeliveries(make_delivery(lead.id, DeliveryState.PENDING))
    service, commits = service_for(lead, deliveries)

    result = await service.retry(
        lead_id=lead.id,
        delivery_id=deliveries.delivery.id,
        reviewer=AuthenticatedReviewer(uuid4(), NormalizedEmail("reviewer@example.com")),
        duplicate_risk_confirmed=False,
    )
    assert result.state is DeliveryState.PROCESSING
    assert deliveries.initial_claims == 1
    assert deliveries.manual_claims == 0
    assert commits == ["commit", "commit"]


@pytest.mark.asyncio
async def test_active_processing_delivery_remains_conflict() -> None:
    lead = make_lead()
    active = replace(
        make_delivery(lead.id, DeliveryState.PROCESSING),
        claim_expires_at=NOW + timedelta(minutes=1),
    )
    deliveries = RetryDeliveries(active)
    service, commits = service_for(lead, deliveries)

    with pytest.raises(DomainError) as conflict:
        await service.retry(
            lead_id=lead.id,
            delivery_id=deliveries.delivery.id,
            reviewer=AuthenticatedReviewer(uuid4(), NormalizedEmail("reviewer@example.com")),
            duplicate_risk_confirmed=True,
        )
    assert conflict.value.code == "delivery_in_progress"
    assert deliveries.initial_claims == 0
    assert deliveries.manual_claims == 0
    assert commits == ["commit"]


@pytest.mark.asyncio
async def test_delivery_completion_log_contains_only_sanitized_operational_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    lead = make_lead()
    deliveries = RetryDeliveries(make_delivery(lead.id, DeliveryState.PENDING))
    commits: list[str] = []
    leads = RetryLeads(lead)
    service = DeliveryService(
        uow_factory=lambda: RetryUow(leads, deliveries, commits),  # type: ignore[arg-type]
        mailer=AcceptedMailer(),
        composer=EmailComposer(NormalizedEmail("attorney@example.com")),
    )
    claim = deliveries._claim(deliveries.delivery.id, DeliveryTrigger.INITIAL)

    with caplog.at_level(logging.INFO, logger="alma_api.application"):
        await service._send_claim(lead, claim)

    record = next(item for item in caplog.records if item.message == "delivery_attempt_completed")
    assert record.attempt_id == str(claim.attempt_id)
    assert record.delivery_kind == "prospect"
    assert record.outcome == "provider_accepted"
    assert record.provider_status == 202
    assert "ada@example.com" not in str(record.__dict__)
