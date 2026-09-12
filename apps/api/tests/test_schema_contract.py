from __future__ import annotations

import inspect
from pathlib import Path

from alma_api import persistence

ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = ROOT / "infra" / "supabase" / "migrations"


def migration(name: str) -> str:
    return (MIGRATIONS / name).read_text()


def test_core_schema_has_canonical_api_read_columns() -> None:
    schema = migration("20260912170000_core_schema.sql")
    for column in (
        "normalized_email",
        "resume_object_path",
        "original_filename",
        "detected_media_type",
        "byte_size",
        "reached_out_by_user_id",
        "delivery_kind",
        "recipient",
        "active_claim_token",
        "claim_expires_at",
        "retry_count",
        "provider_message_id",
        "last_error",
        "trigger_kind",
        "reviewer_user_id",
        "started_at",
        "ended_at",
        "sanitized_error",
    ):
        assert column in schema
    for value in ("'pending'", "'processing'", "'provider_accepted'", "'failed'", "'unknown'"):
        assert value in schema
    assert "delivery_kind in ('prospect', 'attorney')" in schema


def test_transaction_functions_cover_every_runtime_write() -> None:
    functions = migration("20260912170100_transaction_functions.sql")
    for name in (
        "reserve_new_lead_email_budget",
        "get_current_email_budget",
        "get_demo_capacity",
        "create_lead_with_deliveries",
        "mark_lead_reached_out",
        "claim_email_delivery",
        "complete_email_delivery_attempt",
        "expire_email_delivery_claim",
    ):
        assert f"function public.{name}" in functions
    assert "perform public._reserve_email_budget(p_attempt_id, 'retry')" in functions
    assert "interval '1 minute'" in functions
    assert "p_resume_object_path text" in functions
    assert "p_duplicate_risk_confirmed boolean default false" in functions
    for status in (
        "'claimed'",
        "'duplicate_confirmation_required'",
        "'cooldown'",
        "'retry_limit_exhausted'",
        "'stale_claim'",
        "'expired_to_unknown'",
    ):
        assert status in functions


def test_runtime_role_is_select_and_execute_only() -> None:
    grants = migration("20260912170200_storage_roles_and_policies.sql").lower()
    assert "grant select on table public.leads to alma_api" in grants
    assert "grant select on table public.email_deliveries to alma_api" in grants
    assert "grant select on table public.email_delivery_attempts to alma_api" in grants
    assert "grant insert" not in grants
    assert "grant update" not in grants
    assert "grant delete" not in grants


def test_api_write_side_contains_function_calls_not_orm_mutations() -> None:
    source = inspect.getsource(persistence)
    assert "p_resume_object_path => :resume_object_path" in source
    assert "reserve_new_lead_email_budget" in source
    assert "expire_email_delivery_claim" in source
    assert "complete_email_delivery_attempt" in source
    assert "session.add(" not in source
    assert "session.delete(" not in source
