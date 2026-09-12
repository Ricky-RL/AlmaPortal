from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from alma_api.domain import (
    AuthenticatedReviewer,
    DeliveryKind,
    DeliveryState,
    MailResult,
    NormalizedEmail,
)
from alma_api.persistence import (
    DeliveryAttemptRow,
    DeliveryRow,
    LeadRow,
    SqlAlchemyBudgetRepository,
    SqlAlchemyDeliveryRepository,
    SqlAlchemyUnitOfWork,
)

NOW = datetime(2026, 6, 1, 10, tzinfo=UTC)


class MappingResult:
    def __init__(self, value: dict[str, Any]) -> None:
        self.value = value

    def mappings(self) -> MappingResult:
        return self

    def one(self) -> dict[str, Any]:
        return self.value


class ScalarResult:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def all(self) -> list[object]:
        return self.values


class FunctionSession:
    def __init__(
        self,
        *,
        execute_results: list[dict[str, Any]] | None = None,
        scalar_results: list[object] | None = None,
        scalars_results: list[list[object]] | None = None,
    ) -> None:
        self.execute_results = list(execute_results or [])
        self.scalar_results = list(scalar_results or [])
        self.scalars_results = list(scalars_results or [])
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    async def execute(
        self, statement: object, parameters: dict[str, Any] | None = None
    ) -> MappingResult:
        self.calls.append((str(statement), parameters))
        return MappingResult(self.execute_results.pop(0))

    async def scalar(self, statement: object, parameters: dict[str, Any] | None = None) -> object:
        self.calls.append((str(statement), parameters))
        return self.scalar_results.pop(0)

    async def scalars(self, statement: object) -> ScalarResult:
        self.calls.append((str(statement), None))
        return ScalarResult(self.scalars_results.pop(0))

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def close(self) -> None:
        self.closed = True


def delivery_row(
    *,
    state: DeliveryState = DeliveryState.PROCESSING,
    attempt_id: UUID | None = None,
    token: UUID | None = None,
    retry_count: int = 0,
) -> DeliveryRow:
    return DeliveryRow(
        id=uuid4(),
        lead_id=uuid4(),
        delivery_kind=DeliveryKind.PROSPECT.value,
        state=state.value,
        active_attempt_id=attempt_id,
        active_claim_token=token,
        claimed_at=NOW if attempt_id else None,
        claim_expires_at=NOW + timedelta(minutes=5) if attempt_id else None,
        retry_count=retry_count,
        last_attempt_at=NOW if attempt_id or state is not DeliveryState.PENDING else None,
        recipient="lead@example.com",
        provider_message_id=None,
        last_error="prior outcome unknown" if state is DeliveryState.UNKNOWN else None,
        created_at=NOW - timedelta(minutes=1),
        updated_at=NOW,
    )


def attempt_mapping(
    attempt_id: UUID,
    delivery_id: UUID,
    token: UUID,
    *,
    trigger: str,
    reviewer: AuthenticatedReviewer | None = None,
) -> dict[str, Any]:
    return {
        "status": "claimed",
        "id": attempt_id,
        "attempt_id": attempt_id,
        "delivery_id": delivery_id,
        "delivery_kind": "prospect",
        "delivery_state": "processing",
        "recipient": "lead@example.com",
        "claim_token": token,
        "attempt_number": 1 if trigger == "initial" else 2,
        "trigger_kind": trigger,
        "reviewer_user_id": reviewer.id if reviewer else None,
        "reviewer_email": reviewer.email.value if reviewer else None,
        "started_at": NOW,
        "ended_at": None,
        "http_status": None,
        "provider_message_id": None,
        "outcome": None,
        "sanitized_error": None,
    }


def test_read_models_match_canonical_migration_columns() -> None:
    assert set(LeadRow.__table__.columns.keys()) == {
        "id",
        "first_name",
        "last_name",
        "normalized_email",
        "resume_object_path",
        "original_filename",
        "detected_media_type",
        "byte_size",
        "status",
        "created_at",
        "updated_at",
        "reached_out_at",
        "reached_out_by_user_id",
        "reached_out_by_email",
    }
    assert set(DeliveryRow.__table__.columns.keys()) >= {
        "delivery_kind",
        "recipient",
        "active_claim_token",
        "claim_expires_at",
        "retry_count",
        "provider_message_id",
        "last_error",
    }
    assert set(DeliveryAttemptRow.__table__.columns.keys()) >= {
        "claim_token",
        "attempt_number",
        "trigger_kind",
        "reviewer_user_id",
        "reviewer_email",
        "started_at",
        "ended_at",
        "outcome",
        "sanitized_error",
    }


@pytest.mark.asyncio
async def test_initial_claim_uses_database_claim_function_and_result_identity() -> None:
    attempt_id = uuid4()
    token = uuid4()
    delivery = delivery_row(attempt_id=attempt_id, token=token)
    session = FunctionSession(
        scalar_results=[
            attempt_mapping(
                attempt_id,
                delivery.id,
                token,
                trigger="initial",
            ),
            delivery,
        ],
    )
    repository = SqlAlchemyDeliveryRepository(session)  # type: ignore[arg-type]
    claim = await repository.claim_initial(delivery.id)
    assert claim is not None
    assert claim.attempt_id == attempt_id
    assert claim.token == token
    assert claim.kind is DeliveryKind.PROSPECT
    sql = "\n".join(call[0] for call in session.calls).lower()
    assert "claim_email_delivery" in sql
    assert "insert " not in sql
    assert "update " not in sql


@pytest.mark.asyncio
async def test_manual_claim_expires_first_and_database_owns_retry_budget() -> None:
    reviewer = AuthenticatedReviewer(uuid4(), NormalizedEmail("reviewer@example.com"))
    attempt_id = uuid4()
    token = uuid4()
    before = delivery_row(state=DeliveryState.UNKNOWN, retry_count=0)
    after = delivery_row(
        state=DeliveryState.PROCESSING,
        attempt_id=attempt_id,
        token=token,
        retry_count=1,
    )
    after.id = before.id
    after.lead_id = before.lead_id
    session = FunctionSession(
        scalar_results=[
            {"status": "expired_to_unknown"},
            attempt_mapping(
                attempt_id,
                before.id,
                token,
                trigger="manual",
                reviewer=reviewer,
            ),
            after,
        ],
    )
    repository = SqlAlchemyDeliveryRepository(session)  # type: ignore[arg-type]
    reconciliation = await repository.reconcile_claim(before.id)
    assert reconciliation.value == "expired_to_unknown"
    claim = await repository.claim_manual(
        before.id,
        reviewer=reviewer,
        duplicate_risk_confirmed=True,
    )
    assert claim.token == token
    sql = "\n".join(call[0] for call in session.calls).lower()
    assert sql.index("expire_email_delivery_claim") < sql.index("claim_email_delivery")
    assert "reserve_retry_email_budget" not in sql
    claim_parameters = next(
        parameters for sql_text, parameters in session.calls if "claim_email_delivery" in sql_text
    )
    assert claim_parameters and claim_parameters["duplicate_risk_confirmed"] is True


@pytest.mark.asyncio
async def test_unknown_manual_claim_requires_confirmation_before_claim_function() -> None:
    delivery = delivery_row(state=DeliveryState.UNKNOWN)
    duplicate_required = {
        "status": "duplicate_confirmation_required",
        "delivery_id": str(delivery.id),
        "delivery_kind": "prospect",
        "delivery_state": "unknown",
        "recipient": "lead@example.com",
    }
    session = FunctionSession(
        scalar_results=[
            {"status": "not_processing"},
            duplicate_required,
            delivery,
        ]
    )
    repository = SqlAlchemyDeliveryRepository(session)  # type: ignore[arg-type]
    reconciliation = await repository.reconcile_claim(delivery.id)
    assert reconciliation.value == "not_processing"
    with pytest.raises(Exception) as error:
        await repository.claim_manual(
            delivery.id,
            reviewer=AuthenticatedReviewer(uuid4(), NormalizedEmail("reviewer@example.com")),
            duplicate_risk_confirmed=False,
        )
    assert getattr(error.value, "code", None) == "duplicate_risk_confirmation_required"
    assert any("claim_email_delivery" in call[0] for call in session.calls)


@pytest.mark.asyncio
async def test_completion_calls_guarded_function_with_attempt_and_token() -> None:
    attempt_id = uuid4()
    token = uuid4()
    delivery = delivery_row(attempt_id=attempt_id, token=token)
    from alma_api.domain import DeliveryClaim, DeliveryTrigger

    claim = DeliveryClaim(
        delivery_id=delivery.id,
        attempt_id=attempt_id,
        token=token,
        lead_id=delivery.lead_id,
        kind=DeliveryKind.PROSPECT,
        recipient_email=NormalizedEmail("lead@example.com"),
        trigger=DeliveryTrigger.INITIAL,
    )
    session = FunctionSession(scalar_results=[{"status": "completed"}])
    repository = SqlAlchemyDeliveryRepository(session)  # type: ignore[arg-type]
    completed = await repository.complete(
        claim,
        MailResult(
            DeliveryState.PROVIDER_ACCEPTED,
            http_status=202,
            provider_message_id="provider-id",
        ),
    )
    assert completed
    sql, parameters = session.calls[0]
    assert "complete_email_delivery_attempt" in sql
    assert parameters and parameters["attempt_id"] == attempt_id
    assert parameters["claim_token"] == token


@pytest.mark.asyncio
async def test_stale_completion_is_reported_without_projection_success() -> None:
    attempt_id = uuid4()
    token = uuid4()
    delivery = delivery_row(attempt_id=attempt_id, token=token)
    from alma_api.domain import DeliveryClaim, DeliveryTrigger

    claim = DeliveryClaim(
        delivery_id=delivery.id,
        attempt_id=attempt_id,
        token=token,
        lead_id=delivery.lead_id,
        kind=DeliveryKind.PROSPECT,
        recipient_email=NormalizedEmail("lead@example.com"),
        trigger=DeliveryTrigger.INITIAL,
    )
    session = FunctionSession(scalar_results=[{"status": "stale_claim"}])
    repository = SqlAlchemyDeliveryRepository(session)  # type: ignore[arg-type]
    assert not await repository.complete(
        claim,
        MailResult(
            DeliveryState.FAILED,
            http_status=500,
            sanitized_error="sendgrid_retryable_500",
        ),
    )


@pytest.mark.asyncio
async def test_new_lead_budget_uses_database_function() -> None:
    reservation_key = uuid4()
    session = FunctionSession(scalar_results=[{"already_reserved": False}])
    repository = SqlAlchemyBudgetRepository(session)  # type: ignore[arg-type]
    await repository.reserve_new_lead(reservation_key)
    sql, parameters = session.calls[0]
    assert "reserve_new_lead_email_budget" in sql
    assert parameters == {"reservation_key": reservation_key}


@pytest.mark.asyncio
async def test_readiness_requires_runtime_role_schema_and_grants() -> None:
    ready = {
        "runtime_role": "alma_api",
        "has_leads": True,
        "has_deliveries": True,
        "has_attempts": True,
        "can_read_leads": True,
        "can_read_deliveries": True,
        "can_read_attempts": True,
        "can_reserve_lead_budget": True,
        "can_create_lead": True,
        "can_transition_lead": True,
        "can_claim_delivery": True,
        "can_expire_claim": True,
        "can_complete_delivery": True,
    }
    session = FunctionSession(execute_results=[ready])
    uow = SqlAlchemyUnitOfWork(lambda: session)  # type: ignore[arg-type]
    async with uow:
        await uow.check_connection()
    sql = session.calls[0][0].lower()
    assert "current_user" in sql
    assert "to_regclass('public.leads')" in sql
    assert "has_function_privilege" in sql

    not_ready = {**ready, "runtime_role": "postgres"}
    session = FunctionSession(execute_results=[not_ready])
    uow = SqlAlchemyUnitOfWork(lambda: session)  # type: ignore[arg-type]
    with pytest.raises(Exception) as error:
        async with uow:
            await uow.check_connection()
    assert getattr(error.value, "code", None) == "dependency_unavailable"
