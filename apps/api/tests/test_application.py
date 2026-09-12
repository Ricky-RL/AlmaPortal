from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from alma_api.application import (
    CursorPosition,
    EmailComposer,
    GetLeadSummary,
    LeadSearch,
    SearchLeads,
    SubmitLead,
    SubmitLeadCommand,
    TransitionLead,
    ValidatedResume,
)
from alma_api.domain import (
    AuthenticatedReviewer,
    Delivery,
    DeliveryKind,
    DeliveryState,
    Lead,
    LeadStatus,
    LeadSummary,
    NormalizedEmail,
    PersonName,
    ResumeFormat,
    ResumeMetadata,
)

NOW = datetime(2026, 5, 1, 12, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class FakeStorage:
    def __init__(
        self,
        events: list[str],
        *,
        active_uow: Callable[[], bool] = lambda: False,
        fail_upload: bool = False,
    ) -> None:
        self.events = events
        self.uploaded: dict[str, bytes] = {}
        self.deleted: list[str] = []
        self.active_uow = active_uow
        self.fail_upload = fail_upload
        self.upload_outside_uow = False

    async def upload(self, key: str, content: bytes, _: str) -> None:
        self.events.append("upload")
        self.upload_outside_uow = not self.active_uow()
        if self.fail_upload:
            raise RuntimeError("storage failed")
        self.uploaded[key] = content

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.uploaded.pop(key, None)


class FakeBudgets:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.reservation_key: UUID | None = None

    async def reserve_new_lead(self, reservation_key: UUID) -> None:
        self.events.append("reserve")
        self.reservation_key = reservation_key


class FakeLeads:
    def __init__(
        self,
        events: list[str],
        *,
        fail_create: bool = False,
        rows: tuple[Lead, ...] = (),
    ) -> None:
        self.events = events
        self.fail_create = fail_create
        self.values: dict[UUID, Lead] = {}
        self.rows = rows
        self.last_after: CursorPosition | None = None

    async def create_with_deliveries(
        self,
        lead: Lead,
        **_: Any,
    ) -> Lead:
        self.events.append("create")
        if self.fail_create:
            raise RuntimeError("database function failed")
        self.values[lead.id] = lead
        return lead

    async def get(self, lead_id: UUID) -> Lead | None:
        return self.values.get(lead_id)

    async def mark_reached_out(self, lead_id: UUID, reviewer: AuthenticatedReviewer) -> Lead:
        lead = self.values[lead_id]
        transitioned = lead.transition(LeadStatus.REACHED_OUT, reviewer, NOW)
        self.values[lead_id] = transitioned
        return transitioned

    async def search(self, *, after: CursorPosition | None, **_: Any) -> tuple[Lead, ...]:
        self.last_after = after
        return self.rows

    async def summary(self) -> LeadSummary:
        statuses = [lead.status for lead in self.values.values()]
        return LeadSummary(
            total=len(statuses),
            pending=statuses.count(LeadStatus.PENDING),
            reached_out=statuses.count(LeadStatus.REACHED_OUT),
        )


class FakeDeliveries:
    def __init__(self, rows: tuple[Delivery, ...] = ()) -> None:
        self.rows = rows

    async def list_for_lead(self, _: UUID) -> tuple[Delivery, ...]:
        return self.rows

    async def list_attempts_for_lead(self, _: UUID) -> tuple[object, ...]:
        return ()


class FakeUow:
    def __init__(self, leads: FakeLeads, deliveries: FakeDeliveries, budgets: FakeBudgets) -> None:
        self.leads = leads
        self.deliveries = deliveries
        self.budgets = budgets
        self.committed = False
        self.active = False

    async def __aenter__(self) -> FakeUow:
        self.active = True
        return self

    async def __aexit__(self, *_: object) -> None:
        self.active = False
        return None

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        return None

    async def check_connection(self) -> None:
        return None


class FakeDeliveryService:
    def __init__(self) -> None:
        self.calls: list[UUID] = []

    async def send_initial(self, _: Lead, delivery_id: UUID) -> None:
        self.calls.append(delivery_id)


def resume() -> ValidatedResume:
    return ValidatedResume(
        content=b"%PDF-1.7",
        original_filename="../../My Resume.pdf",
        media_type="application/pdf",
        format=ResumeFormat.PDF,
    )


@pytest.mark.asyncio
async def test_submit_reserves_before_upload_then_calls_create_function() -> None:
    events: list[str] = []
    deliveries = (
        make_delivery(DeliveryKind.PROSPECT),
        make_delivery(DeliveryKind.ATTORNEY),
    )
    leads = FakeLeads(events)
    budgets = FakeBudgets(events)
    uow = FakeUow(leads, FakeDeliveries(deliveries), budgets)
    storage = FakeStorage(events, active_uow=lambda: uow.active)
    sender = FakeDeliveryService()
    use_case = SubmitLead(
        uow_factory=lambda: uow,
        storage=storage,
        delivery_service=sender,
        composer=EmailComposer(NormalizedEmail.parse("attorney@example.com")),
        clock=FixedClock(),
    )
    lead = await use_case(SubmitLeadCommand("Ada", "Lovelace", "ada@example.com", True, resume()))
    assert events[:3] == ["reserve", "upload", "create"]
    assert budgets.reservation_key == lead.id
    assert lead.resume.original_filename == "My_Resume.pdf"
    assert lead.resume.object_key.startswith(f"leads/{lead.id}/")
    assert len(lead.resume.object_key.split("/")) == 3
    assert len(storage.uploaded) == 1
    assert storage.upload_outside_uow
    assert sender.calls == [delivery.id for delivery in deliveries]


@pytest.mark.asyncio
async def test_storage_upload_is_compensated_when_create_function_fails() -> None:
    events: list[str] = []
    uow = FakeUow(
        FakeLeads(events, fail_create=True),
        FakeDeliveries(),
        FakeBudgets(events),
    )
    storage = FakeStorage(events)
    use_case = SubmitLead(
        uow_factory=lambda: uow,
        storage=storage,
        delivery_service=FakeDeliveryService(),
        composer=EmailComposer(NormalizedEmail.parse("attorney@example.com")),
        clock=FixedClock(),
    )
    with pytest.raises(RuntimeError, match="database function failed"):
        await use_case(SubmitLeadCommand("Ada", "Lovelace", "ada@example.com", True, resume()))
    assert storage.uploaded == {}
    assert len(storage.deleted) == 1


@pytest.mark.asyncio
async def test_upload_failure_keeps_committed_email_credit_reservation() -> None:
    events: list[str] = []
    uow = FakeUow(FakeLeads(events), FakeDeliveries(), FakeBudgets(events))
    storage = FakeStorage(
        events,
        active_uow=lambda: uow.active,
        fail_upload=True,
    )
    use_case = SubmitLead(
        uow_factory=lambda: uow,
        storage=storage,
        delivery_service=FakeDeliveryService(),
        composer=EmailComposer(NormalizedEmail.parse("attorney@example.com")),
        clock=FixedClock(),
    )
    with pytest.raises(RuntimeError, match="storage failed"):
        await use_case(SubmitLeadCommand("Ada", "Lovelace", "ada@example.com", True, resume()))
    assert uow.committed
    assert storage.upload_outside_uow
    assert storage.deleted == []


@pytest.mark.asyncio
async def test_duplicate_email_is_not_used_as_submission_identity() -> None:
    events: list[str] = []
    leads = FakeLeads(events)
    uow = FakeUow(leads, FakeDeliveries(), FakeBudgets(events))
    use_case = SubmitLead(
        uow_factory=lambda: uow,
        storage=FakeStorage(events),
        delivery_service=FakeDeliveryService(),
        composer=EmailComposer(NormalizedEmail.parse("attorney@example.com")),
        clock=FixedClock(),
    )
    first = await use_case(SubmitLeadCommand("Ada", "One", "same@example.com", True, resume()))
    second = await use_case(SubmitLeadCommand("Ada", "Two", "same@example.com", True, resume()))
    assert first.id != second.id
    assert len(leads.values) == 2


@pytest.mark.asyncio
async def test_cursor_uses_created_at_and_id_of_last_returned_lead() -> None:
    events: list[str] = []
    rows = tuple(make_lead(index) for index in range(3))
    leads = FakeLeads(events, rows=rows)
    use_case = SearchLeads(lambda: FakeUow(leads, FakeDeliveries(), FakeBudgets(events)))
    page = await use_case(LeadSearch(q=None, status=None, cursor=None, limit=2))
    assert page.items == rows[:2]
    assert page.next_cursor is not None
    await use_case(LeadSearch(q=None, status=None, cursor=page.next_cursor, limit=2))
    assert leads.last_after == CursorPosition(rows[1].created_at, rows[1].id)


@pytest.mark.asyncio
async def test_status_transition_uses_idempotent_database_function_port() -> None:
    events: list[str] = []
    lead = make_lead(1)
    leads = FakeLeads(events)
    leads.values[lead.id] = lead
    use_case = TransitionLead(lambda: FakeUow(leads, FakeDeliveries(), FakeBudgets(events)))
    first = AuthenticatedReviewer(uuid4(), NormalizedEmail.parse("first-reviewer@example.com"))
    second = AuthenticatedReviewer(uuid4(), NormalizedEmail.parse("second-reviewer@example.com"))
    transitioned = await use_case(lead.id, LeadStatus.REACHED_OUT, first)
    repeated = await use_case(lead.id, LeadStatus.REACHED_OUT, second)
    assert transitioned.reached_out_by == first
    assert repeated.reached_out_by == first


@pytest.mark.asyncio
async def test_summary_counts_current_statuses() -> None:
    events: list[str] = []
    leads = FakeLeads(events)
    pending = make_lead(1)
    reached = make_lead(2).transition(
        LeadStatus.REACHED_OUT,
        AuthenticatedReviewer(uuid4(), NormalizedEmail.parse("reviewer@example.com")),
        NOW,
    )
    leads.values[pending.id] = pending
    leads.values[reached.id] = reached
    summary = await GetLeadSummary(lambda: FakeUow(leads, FakeDeliveries(), FakeBudgets(events)))()
    assert summary == LeadSummary(total=2, pending=1, reached_out=1)


def make_lead(index: int) -> Lead:
    lead_id = uuid4()
    timestamp = NOW.replace(microsecond=index)
    return Lead(
        id=lead_id,
        first_name=PersonName("Ada"),
        last_name=PersonName(str(index)),
        email=NormalizedEmail(f"ada{index}@example.com"),
        resume=ResumeMetadata(
            object_key=f"leads/{lead_id}/{uuid4()}.pdf",
            original_filename="resume.pdf",
            media_type="application/pdf",
            size_bytes=10,
            format=ResumeFormat.PDF,
        ),
        status=LeadStatus.PENDING,
        created_at=timestamp,
        updated_at=timestamp,
    )


def make_delivery(kind: DeliveryKind) -> Delivery:
    return Delivery(
        id=uuid4(),
        lead_id=uuid4(),
        kind=kind,
        recipient_email=NormalizedEmail("recipient@example.com"),
        state=DeliveryState.PENDING,
        active_attempt_id=None,
        active_claim_token=None,
        claimed_at=None,
        claim_expires_at=None,
        retry_count=0,
        last_attempt_at=None,
        provider_message_id=None,
        last_error=None,
        created_at=NOW - timedelta(seconds=1),
        updated_at=NOW,
    )
