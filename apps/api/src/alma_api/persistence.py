"""SQLAlchemy read models and migration-function write adapters."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime
from types import TracebackType
from typing import Any, NoReturn, cast
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Uuid,
    and_,
    case,
    func,
    or_,
    select,
    text,
)
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from alma_api.application import (
    ApplicationError,
    BudgetExceededError,
    ClaimReconciliation,
    ConcurrencyError,
    CursorPosition,
    DemoCapacity,
    DependencyUnavailableError,
    EmailBudget,
    NotFoundError,
    UnitOfWork,
)
from alma_api.domain import (
    AuthenticatedReviewer,
    Delivery,
    DeliveryAttempt,
    DeliveryClaim,
    DeliveryKind,
    DeliveryState,
    DeliveryTrigger,
    DomainError,
    Lead,
    LeadStatus,
    LeadSummary,
    MailResult,
    NormalizedEmail,
    PersonName,
    ResumeMetadata,
    resume_format_from_media_type,
)


class Base(DeclarativeBase):
    pass


class LeadRow(Base):
    __tablename__ = "leads"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    normalized_email: Mapped[str] = mapped_column(String(320))
    comments: Mapped[str | None] = mapped_column(String(2000))
    resume_object_path: Mapped[str] = mapped_column(String(260), unique=True)
    original_filename: Mapped[str] = mapped_column(String(180))
    detected_media_type: Mapped[str] = mapped_column(String(100))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reached_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reached_out_by_user_id: Mapped[UUID | None] = mapped_column(Uuid)
    reached_out_by_email: Mapped[str | None] = mapped_column(String(320))

    __table_args__ = (Index("leads_created_cursor_idx", created_at, id),)


class DeliveryRow(Base):
    __tablename__ = "email_deliveries"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    lead_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("leads.id", ondelete="RESTRICT"))
    delivery_kind: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(24))
    active_attempt_id: Mapped[UUID | None] = mapped_column(Uuid)
    active_claim_token: Mapped[UUID | None] = mapped_column(Uuid)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_count: Mapped[int] = mapped_column(SmallInteger)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recipient: Mapped[str] = mapped_column(String(320))
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    last_error: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("email_deliveries_one_per_lead_kind", lead_id, delivery_kind, unique=True),
    )


class DeliveryAttemptRow(Base):
    __tablename__ = "email_delivery_attempts"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    delivery_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("email_deliveries.id", ondelete="RESTRICT")
    )
    claim_token: Mapped[UUID] = mapped_column(Uuid, unique=True)
    attempt_number: Mapped[int] = mapped_column(SmallInteger)
    trigger_kind: Mapped[str] = mapped_column(String(16))
    reviewer_user_id: Mapped[UUID | None] = mapped_column(Uuid)
    reviewer_email: Mapped[str | None] = mapped_column(String(320))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    http_status: Mapped[int | None] = mapped_column(SmallInteger)
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    outcome: Mapped[str | None] = mapped_column(String(24))
    sanitized_error: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "email_delivery_attempts_delivery_number_unique",
            delivery_id,
            attempt_number,
            unique=True,
        ),
    )


class SqlAlchemyLeadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_with_deliveries(
        self,
        lead: Lead,
        *,
        prospect_recipient: NormalizedEmail,
        attorney_recipient: NormalizedEmail,
    ) -> Lead:
        statement = text(
            """
            select *
              from public.create_lead_with_deliveries(
                p_lead_id => :lead_id,
                p_first_name => :first_name,
                p_last_name => :last_name,
                p_normalized_email => :normalized_email,
                p_resume_object_path => :resume_object_path,
                p_original_filename => :original_filename,
                p_detected_media_type => :detected_media_type,
                p_byte_size => :byte_size,
                p_prospect_recipient => :prospect_recipient,
                p_attorney_recipient => :attorney_recipient,
                p_comments => :comments
              )
            """
        )
        try:
            result = await self._session.execute(
                statement,
                {
                    "lead_id": lead.id,
                    "first_name": lead.first_name.value,
                    "last_name": lead.last_name.value,
                    "normalized_email": lead.email.value,
                    "resume_object_path": lead.resume.object_key,
                    "original_filename": lead.resume.original_filename,
                    "detected_media_type": lead.resume.media_type,
                    "byte_size": lead.resume.size_bytes,
                    "prospect_recipient": prospect_recipient.value,
                    "attorney_recipient": attorney_recipient.value,
                    "comments": lead.comments,
                },
            )
            return _mapping_to_lead(result.mappings().one())
        except DBAPIError as exc:
            _translate_database_error(exc, "create_lead")

    async def get(self, lead_id: UUID) -> Lead | None:
        row = await self._session.scalar(select(LeadRow).where(LeadRow.id == lead_id))
        return _row_to_lead(row) if row is not None else None

    async def mark_reached_out(self, lead_id: UUID, reviewer: AuthenticatedReviewer) -> Lead:
        try:
            result = await self._session.execute(
                text(
                    """
                    select *
                      from public.mark_lead_reached_out(
                        p_lead_id => :lead_id,
                        p_reviewer_user_id => :reviewer_id,
                        p_reviewer_email => :reviewer_email
                      )
                    """
                ),
                {
                    "lead_id": lead_id,
                    "reviewer_id": reviewer.id,
                    "reviewer_email": reviewer.email.value,
                },
            )
            return _mapping_to_lead(result.mappings().one())
        except DBAPIError as exc:
            _translate_database_error(exc, "status_transition")

    async def search(
        self,
        *,
        q: str | None,
        status: LeadStatus | None,
        after: CursorPosition | None,
        limit: int,
    ) -> tuple[Lead, ...]:
        statement = select(LeadRow)
        if q is not None:
            escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            statement = statement.where(
                or_(
                    LeadRow.first_name.ilike(pattern, escape="\\"),
                    LeadRow.last_name.ilike(pattern, escape="\\"),
                    LeadRow.normalized_email.ilike(pattern, escape="\\"),
                    LeadRow.comments.ilike(pattern, escape="\\"),
                )
            )
        if status is not None:
            statement = statement.where(LeadRow.status == status.value)
        if after is not None:
            statement = statement.where(
                or_(
                    LeadRow.created_at < after.created_at,
                    and_(
                        LeadRow.created_at == after.created_at,
                        LeadRow.id < after.lead_id,
                    ),
                )
            )
        statement = statement.order_by(LeadRow.created_at.desc(), LeadRow.id.desc()).limit(limit)
        rows = (await self._session.scalars(statement)).all()
        return tuple(_row_to_lead(row) for row in rows)

    async def summary(self) -> LeadSummary:
        result = await self._session.execute(
            select(
                func.count(LeadRow.id),
                func.sum(case((LeadRow.status == LeadStatus.PENDING.value, 1), else_=0)),
                func.sum(case((LeadRow.status == LeadStatus.REACHED_OUT.value, 1), else_=0)),
            )
        )
        total, pending, reached_out = result.one()
        return LeadSummary(int(total or 0), int(pending or 0), int(reached_out or 0))


class SqlAlchemyDeliveryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, delivery_id: UUID) -> Delivery | None:
        row = await self._session.scalar(select(DeliveryRow).where(DeliveryRow.id == delivery_id))
        return _row_to_delivery(row) if row is not None else None

    async def list_for_lead(self, lead_id: UUID) -> tuple[Delivery, ...]:
        rows = (
            await self._session.scalars(
                select(DeliveryRow)
                .where(DeliveryRow.lead_id == lead_id)
                .order_by(DeliveryRow.delivery_kind)
            )
        ).all()
        return tuple(_row_to_delivery(row) for row in rows)

    async def list_attempts_for_lead(self, lead_id: UUID) -> tuple[DeliveryAttempt, ...]:
        delivery_ids = select(DeliveryRow.id).where(DeliveryRow.lead_id == lead_id)
        rows = (
            await self._session.scalars(
                select(DeliveryAttemptRow)
                .where(DeliveryAttemptRow.delivery_id.in_(delivery_ids))
                .order_by(
                    DeliveryAttemptRow.delivery_id,
                    DeliveryAttemptRow.attempt_number,
                )
            )
        ).all()
        return tuple(_row_to_attempt(row) for row in rows)

    async def claim_initial(self, delivery_id: UUID) -> DeliveryClaim | None:
        try:
            claim_result = await self._claim(
                delivery_id,
                attempt_id=uuid4(),
                trigger=DeliveryTrigger.INITIAL,
                reviewer=None,
                duplicate_risk_confirmed=False,
            )
        except DBAPIError as exc:
            if _sqlstate(exc) == "55000" and "initial" in _primary_message(exc).lower():
                return None
            _translate_database_error(exc, "initial_claim")
        delivery = await self._get_delivery(delivery_id)
        return _claim_from_function(claim_result, delivery)

    async def reconcile_claim(self, delivery_id: UUID) -> ClaimReconciliation:
        try:
            expiration_raw = await self._session.scalar(
                text(
                    """
                    select public.expire_email_delivery_claim(
                        p_delivery_id => :delivery_id
                    )
                    """
                ),
                {"delivery_id": delivery_id},
            )
        except DBAPIError as exc:
            _translate_database_error(exc, "expire_claim")
        expiration = _json_mapping(expiration_raw)
        try:
            return ClaimReconciliation(str(expiration["status"]))
        except (KeyError, ValueError) as exc:
            raise DependencyUnavailableError(
                "database returned an unsupported expiration status"
            ) from exc

    async def claim_manual(
        self,
        delivery_id: UUID,
        *,
        reviewer: AuthenticatedReviewer,
        duplicate_risk_confirmed: bool,
    ) -> DeliveryClaim:
        try:
            claim_result = await self._claim(
                delivery_id,
                attempt_id=uuid4(),
                trigger=DeliveryTrigger.MANUAL,
                reviewer=reviewer,
                duplicate_risk_confirmed=duplicate_risk_confirmed,
            )
        except DBAPIError as exc:
            _translate_database_error(exc, "manual_claim")
        refreshed = await self._get_delivery(delivery_id)
        return _claim_from_function(claim_result, refreshed)

    async def complete(self, claim: DeliveryClaim, result: MailResult) -> bool:
        try:
            completion_raw = await self._session.scalar(
                text(
                    """
                    select public.complete_email_delivery_attempt(
                        p_attempt_id => :attempt_id,
                        p_claim_token => :claim_token,
                        p_outcome => :outcome,
                        p_http_status => :http_status,
                        p_provider_message_id => :provider_message_id,
                        p_sanitized_error => :sanitized_error
                    )
                    """
                ),
                {
                    "attempt_id": claim.attempt_id,
                    "claim_token": claim.token,
                    "outcome": result.state.value,
                    "http_status": result.http_status,
                    "provider_message_id": result.provider_message_id,
                    "sanitized_error": result.sanitized_error,
                },
            )
            completion = _json_mapping(completion_raw)
            return completion.get("status") == "completed"
        except DBAPIError as exc:
            _translate_database_error(exc, "complete_claim")

    async def _claim(
        self,
        delivery_id: UUID,
        *,
        attempt_id: UUID,
        trigger: DeliveryTrigger,
        reviewer: AuthenticatedReviewer | None,
        duplicate_risk_confirmed: bool,
    ) -> Mapping[str, Any]:
        raw = await self._session.scalar(
            text(
                """
                select public.claim_email_delivery(
                    p_delivery_id => :delivery_id,
                    p_attempt_id => :attempt_id,
                    p_trigger_kind => :trigger_kind,
                    p_reviewer_user_id => :reviewer_id,
                    p_reviewer_email => :reviewer_email,
                    p_duplicate_risk_confirmed => :duplicate_risk_confirmed
                  )
                """
            ),
            {
                "delivery_id": delivery_id,
                "attempt_id": attempt_id,
                "trigger_kind": trigger.value,
                "reviewer_id": reviewer.id if reviewer else None,
                "reviewer_email": reviewer.email.value if reviewer else None,
                "duplicate_risk_confirmed": duplicate_risk_confirmed,
            },
        )
        return _json_mapping(raw)

    async def _get_delivery(self, delivery_id: UUID) -> Delivery:
        row = await self._session.scalar(select(DeliveryRow).where(DeliveryRow.id == delivery_id))
        if row is None:
            raise NotFoundError("delivery was not found")
        return _row_to_delivery(row)


class SqlAlchemyBudgetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def reserve_new_lead(self, reservation_key: UUID) -> None:
        try:
            await self._session.scalar(
                text(
                    """
                    select public.reserve_new_lead_email_budget(
                        p_reservation_key => :reservation_key
                    )
                    """
                ),
                {"reservation_key": reservation_key},
            )
        except DBAPIError as exc:
            _translate_database_error(exc, "new_lead_budget")

    async def current_email_budget(self) -> EmailBudget:
        try:
            raw = await self._session.scalar(text("select public.get_current_email_budget()"))
            value = _json_mapping(raw)
            return EmailBudget(
                budget_date=date.fromisoformat(str(value["budget_date"])),
                new_lead_credit_limit=int(value["new_lead_credit_limit"]),
                new_lead_credits_used=int(value["new_lead_credits_used"]),
                new_lead_credits_remaining=int(value["new_lead_credits_remaining"]),
                retry_credit_limit=int(value["retry_credit_limit"]),
                retry_credits_used=int(value["retry_credits_used"]),
                retry_credits_remaining=int(value["retry_credits_remaining"]),
            )
        except DBAPIError as exc:
            _translate_database_error(exc, "read_email_budget")

    async def current_capacity(self) -> DemoCapacity:
        try:
            raw = await self._session.scalar(text("select public.get_demo_capacity()"))
            value = _json_mapping(raw)
            return DemoCapacity(
                lead_limit=int(value["lead_limit"]),
                lead_count=int(value["lead_count"]),
                lead_slots_remaining=int(value["lead_slots_remaining"]),
                resume_byte_limit=int(value["resume_byte_limit"]),
                resume_bytes=int(value["resume_bytes"]),
                resume_bytes_remaining=int(value["resume_bytes_remaining"]),
            )
        except DBAPIError as exc:
            _translate_database_error(exc, "read_capacity")


class SqlAlchemyUnitOfWork(UnitOfWork):
    leads: SqlAlchemyLeadRepository
    deliveries: SqlAlchemyDeliveryRepository
    budgets: SqlAlchemyBudgetRepository

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._committed = False

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        self._session = self._session_factory()
        self.leads = SqlAlchemyLeadRepository(self._session)
        self.deliveries = SqlAlchemyDeliveryRepository(self._session)
        self.budgets = SqlAlchemyBudgetRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._session is None:
            return
        database_failure = isinstance(exc, SQLAlchemyError)
        try:
            if exc is not None or not self._committed:
                await self._session.rollback()
            await self._session.close()
        finally:
            self._session = None
        if database_failure:
            raise DependencyUnavailableError("database operation failed") from exc

    async def commit(self) -> None:
        await self._require_session().commit()
        self._committed = True

    async def rollback(self) -> None:
        await self._require_session().rollback()

    async def check_connection(self) -> None:
        result = await self._require_session().execute(
            text(
                """
                select
                    current_user as runtime_role,
                    to_regclass('public.leads') is not null as has_leads,
                    to_regclass('public.email_deliveries') is not null as has_deliveries,
                    to_regclass('public.email_delivery_attempts') is not null as has_attempts,
                    has_table_privilege(current_user, 'public.leads', 'SELECT')
                        as can_read_leads,
                    has_table_privilege(current_user, 'public.email_deliveries', 'SELECT')
                        as can_read_deliveries,
                    has_table_privilege(
                        current_user, 'public.email_delivery_attempts', 'SELECT'
                    ) as can_read_attempts,
                    coalesce(has_function_privilege(
                        current_user,
                        to_regprocedure('public.reserve_new_lead_email_budget(uuid)'),
                        'EXECUTE'
                    ), false) as can_reserve_lead_budget,
                    coalesce(has_function_privilege(
                        current_user,
                        to_regprocedure(
                            'public.create_lead_with_deliveries(uuid,text,text,text,text,text,text,bigint,text,text,text)'
                        ),
                        'EXECUTE'
                    ), false) as can_create_lead,
                    coalesce(has_function_privilege(
                        current_user,
                        to_regprocedure('public.mark_lead_reached_out(uuid,uuid,text)'),
                        'EXECUTE'
                    ), false) as can_transition_lead,
                    coalesce(has_function_privilege(
                        current_user,
                        to_regprocedure(
                            'public.claim_email_delivery(uuid,uuid,text,uuid,text,boolean)'
                        ),
                        'EXECUTE'
                    ), false) as can_claim_delivery,
                    coalesce(has_function_privilege(
                        current_user,
                        to_regprocedure('public.expire_email_delivery_claim(uuid)'),
                        'EXECUTE'
                    ), false) as can_expire_claim,
                    coalesce(has_function_privilege(
                        current_user,
                        to_regprocedure(
                            'public.complete_email_delivery_attempt(uuid,uuid,text,integer,text,text)'
                        ),
                        'EXECUTE'
                    ), false) as can_complete_delivery
                """
            )
        )
        readiness = result.mappings().one()
        if readiness["runtime_role"] != "alma_api" or not all(
            value is True for key, value in readiness.items() if key != "runtime_role"
        ):
            raise DependencyUnavailableError("database schema, role, or grants are not ready")

    def _require_session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("unit of work must be entered before use")
        return self._session


def create_engine(url: str) -> AsyncEngine:
    return create_async_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_timeout=3,
        connect_args={
            "connect_timeout": 3,
            "options": (
                "-c statement_timeout=3000 "
                "-c lock_timeout=1000 "
                "-c idle_in_transaction_session_timeout=5000"
            ),
        },
    )


class SqlAlchemyUnitOfWorkFactory:
    def __init__(self, engine: AsyncEngine) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    def __call__(self) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(self._sessions)


def create_uow_factory(engine: AsyncEngine) -> SqlAlchemyUnitOfWorkFactory:
    return SqlAlchemyUnitOfWorkFactory(engine)


def _row_to_lead(row: LeadRow) -> Lead:
    return _lead_from_values(
        {
            "id": row.id,
            "first_name": row.first_name,
            "last_name": row.last_name,
            "normalized_email": row.normalized_email,
            "comments": row.comments,
            "resume_object_path": row.resume_object_path,
            "original_filename": row.original_filename,
            "detected_media_type": row.detected_media_type,
            "byte_size": row.byte_size,
            "status": row.status,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "reached_out_at": row.reached_out_at,
            "reached_out_by_user_id": row.reached_out_by_user_id,
            "reached_out_by_email": row.reached_out_by_email,
        }
    )


def _mapping_to_lead(row: Mapping[Any, Any]) -> Lead:
    return _lead_from_values(row)


def _lead_from_values(value: Mapping[Any, Any]) -> Lead:
    reviewer = None
    reviewer_id = value["reached_out_by_user_id"]
    reviewer_email = value["reached_out_by_email"]
    if reviewer_id is not None and reviewer_email is not None:
        reviewer = AuthenticatedReviewer(
            id=cast(UUID, reviewer_id),
            email=NormalizedEmail(str(reviewer_email)),
        )
    media_type = str(value["detected_media_type"])
    return Lead(
        id=cast(UUID, value["id"]),
        first_name=PersonName(str(value["first_name"])),
        last_name=PersonName(str(value["last_name"])),
        email=NormalizedEmail(str(value["normalized_email"])),
        resume=ResumeMetadata(
            object_key=str(value["resume_object_path"]),
            original_filename=str(value["original_filename"]),
            media_type=media_type,
            size_bytes=int(value["byte_size"]),
            format=resume_format_from_media_type(media_type),
        ),
        status=LeadStatus(str(value["status"])),
        created_at=cast(datetime, value["created_at"]),
        updated_at=cast(datetime, value["updated_at"]),
        comments=str(value["comments"]) if value.get("comments") else None,
        reached_out_by=reviewer,
        reached_out_at=cast(datetime | None, value["reached_out_at"]),
    )


def _row_to_delivery(row: DeliveryRow) -> Delivery:
    return Delivery(
        id=row.id,
        lead_id=row.lead_id,
        kind=DeliveryKind(row.delivery_kind),
        recipient_email=NormalizedEmail(row.recipient),
        state=DeliveryState(row.state),
        active_attempt_id=row.active_attempt_id,
        active_claim_token=row.active_claim_token,
        claimed_at=row.claimed_at,
        claim_expires_at=row.claim_expires_at,
        retry_count=row.retry_count,
        last_attempt_at=row.last_attempt_at,
        provider_message_id=row.provider_message_id,
        last_error=row.last_error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_attempt(row: DeliveryAttemptRow) -> DeliveryAttempt:
    return _attempt_from_values(
        {
            "id": row.id,
            "delivery_id": row.delivery_id,
            "attempt_number": row.attempt_number,
            "trigger_kind": row.trigger_kind,
            "reviewer_user_id": row.reviewer_user_id,
            "reviewer_email": row.reviewer_email,
            "started_at": row.started_at,
            "ended_at": row.ended_at,
            "http_status": row.http_status,
            "provider_message_id": row.provider_message_id,
            "outcome": row.outcome,
            "sanitized_error": row.sanitized_error,
        }
    )


def _mapping_to_attempt(row: Mapping[Any, Any]) -> DeliveryAttempt:
    return _attempt_from_values(row)


def _attempt_from_values(value: Mapping[Any, Any]) -> DeliveryAttempt:
    reviewer = None
    reviewer_id = value["reviewer_user_id"]
    reviewer_email = value["reviewer_email"]
    if reviewer_id is not None and reviewer_email is not None:
        reviewer = AuthenticatedReviewer(
            id=cast(UUID, reviewer_id),
            email=NormalizedEmail(str(reviewer_email)),
        )
    outcome = value["outcome"]
    return DeliveryAttempt(
        id=cast(UUID, value["id"]),
        delivery_id=cast(UUID, value["delivery_id"]),
        attempt_number=int(value["attempt_number"]),
        trigger=DeliveryTrigger(str(value["trigger_kind"])),
        reviewer=reviewer,
        started_at=cast(datetime, value["started_at"]),
        ended_at=cast(datetime | None, value["ended_at"]),
        http_status=cast(int | None, value["http_status"]),
        outcome=DeliveryState(str(outcome)) if outcome is not None else None,
        provider_message_id=cast(str | None, value["provider_message_id"]),
        sanitized_error=cast(str | None, value["sanitized_error"]),
    )


def _claim_from_function(result: Mapping[str, Any], delivery: Delivery) -> DeliveryClaim:
    status = str(result["status"])
    if status == "duplicate_confirmation_required":
        raise DomainError(
            "duplicate_risk_confirmation_required",
            "the previous attempt outcome is unknown; confirm duplicate-delivery risk",
        )
    if status == "cooldown":
        raise DomainError("retry_cooldown", "delivery retry cooldown has not elapsed")
    if status == "retry_limit_exhausted":
        raise DomainError("retry_limit_reached", "delivery has reached the manual retry limit")
    if status not in {"claimed", "existing_attempt"}:
        raise ConcurrencyError("database returned an unsupported delivery claim status")
    attempt_id = UUID(str(result["attempt_id"]))
    claim_token = UUID(str(result["claim_token"]))
    if (
        delivery.active_claim_token != claim_token
        or delivery.active_attempt_id != attempt_id
        or delivery.state is not DeliveryState.PROCESSING
    ):
        raise ConcurrencyError("delivery claim identity was not activated")
    return DeliveryClaim(
        delivery_id=delivery.id,
        attempt_id=attempt_id,
        token=claim_token,
        lead_id=delivery.lead_id,
        kind=delivery.kind,
        recipient_email=delivery.recipient_email,
        trigger=DeliveryTrigger(str(result["trigger_kind"])),
    )


def _json_mapping(raw: object) -> Mapping[str, Any]:
    value = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(value, Mapping):
        raise DependencyUnavailableError("database function returned an invalid result")
    return cast(Mapping[str, Any], value)


def _translate_database_error(exc: DBAPIError, operation: str) -> NoReturn:
    sqlstate = _sqlstate(exc)
    message = _primary_message(exc).lower()
    if sqlstate == "P0002":
        raise NotFoundError("requested record was not found") from exc
    if sqlstate == "P0001":
        raise BudgetExceededError("database-owned capacity or email budget is exhausted") from exc
    if sqlstate == "54000":
        raise DomainError(
            "retry_limit_reached", "delivery has reached the manual retry limit"
        ) from exc
    if sqlstate == "55000" and "cooldown" in message:
        raise DomainError("retry_cooldown", "delivery retry cooldown has not elapsed") from exc
    if sqlstate == "55000" and "manual retry" in message:
        raise DomainError("delivery_not_retryable", "delivery cannot be retried") from exc
    if sqlstate == "55P03":
        raise DomainError(
            "delivery_in_progress", "a delivery attempt is already in progress"
        ) from exc
    if sqlstate in {"23505", "55000"}:
        raise ConcurrencyError(f"{operation} conflicted with current state") from exc
    if sqlstate == "23514":
        raise DomainError("invalid_status_transition", "status transition is not allowed") from exc
    if sqlstate in {"22004", "22023"}:
        raise ApplicationError(f"{operation} arguments were rejected") from exc
    raise DependencyUnavailableError(f"{operation} failed") from exc


def _sqlstate(exc: DBAPIError) -> str | None:
    return cast(str | None, getattr(exc.orig, "sqlstate", None))


def _primary_message(exc: DBAPIError) -> str:
    diagnostic = getattr(exc.orig, "diag", None)
    message = getattr(diagnostic, "message_primary", None)
    return str(message or exc.orig)
