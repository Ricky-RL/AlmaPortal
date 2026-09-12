from __future__ import annotations

import os

import pytest

from alma_api.persistence import create_engine, create_uow_factory

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_local_supabase_database_is_ready() -> None:
    if os.getenv("ALMA_RUN_SUPABASE_INTEGRATION") != "1":
        pytest.skip("set ALMA_RUN_SUPABASE_INTEGRATION=1 for local Supabase checks")
    database_url = os.environ["TEST_DATABASE_URL"]
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(database_url)
    try:
        async with create_uow_factory(engine)() as uow:
            await uow.check_connection()
    finally:
        await engine.dispose()
