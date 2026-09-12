from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from alma_api.application import StoredObject
from alma_api.domain import (
    AuthenticatedReviewer,
    Lead,
    NormalizedEmail,
    PersonName,
    ResumeFormat,
    ResumeMetadata,
)
from alma_api.presentation import (
    create_router,
    install_exception_handlers,
)
from alma_api.presentation import (
    reviewer as reviewer_dependency,
)

NOW = datetime(2026, 7, 1, 9, tzinfo=UTC)


class ReadyUow:
    async def __aenter__(self) -> ReadyUow:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def check_connection(self) -> None:
        return None


class FakeSubmit:
    def __init__(self) -> None:
        self.commands: list[object] = []

    async def __call__(self, command: object) -> Lead:
        self.commands.append(command)
        lead_id = uuid4()
        return Lead.submit(
            first_name=PersonName("Ada"),
            last_name=PersonName("Lovelace"),
            email=NormalizedEmail("ada@example.com"),
            resume=ResumeMetadata(
                object_key=f"leads/{lead_id}/{uuid4()}.pdf",
                original_filename="resume.pdf",
                media_type="application/pdf",
                size_bytes=8,
                format=ResumeFormat.PDF,
            ),
            now=NOW,
            lead_id=lead_id,
        )


class FakeDownload:
    async def __call__(self, _: str) -> tuple[object, StoredObject]:
        async def content():
            yield b"%PDF-1.7"

        return object(), StoredObject(content(), "application/pdf", 8)


class FakeTicket:
    async def __call__(self, _: object, __: object) -> str:
        return "signed.ticket"


def build_test_app() -> tuple[FastAPI, FakeSubmit]:
    app = FastAPI()
    submit = FakeSubmit()
    app.state.services = SimpleNamespace(
        submit_lead=submit,
        download_resume=FakeDownload(),
        create_download_ticket=FakeTicket(),
        uow_factory=lambda: ReadyUow(),
        public_api_url="https://api.alma.example",
        commit_sha="abc123",
    )
    app.dependency_overrides[reviewer_dependency] = lambda: AuthenticatedReviewer(
        uuid4(), NormalizedEmail("reviewer@example.com")
    )
    app.include_router(create_router())
    install_exception_handlers(app)
    return app, submit


@pytest.mark.asyncio
async def test_public_multipart_contract_accepts_exact_fields() -> None:
    app, submit = build_test_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/leads",
            data={
                "first_name": "Ada",
                "last_name": "Lovelace",
                "email": "ada@example.com",
                "synthetic_data_acknowledged": "true",
            },
            files={"resume": ("resume.pdf", b"%PDF-1.7", "application/pdf")},
        )
    assert response.status_code == 201
    assert len(submit.commands) == 1


@pytest.mark.asyncio
async def test_public_multipart_contract_rejects_extra_fields() -> None:
    app, submit = build_test_app()
    boundary = "alma-test-boundary"
    parts = []
    for name, value in {
        "first_name": "Ada",
        "last_name": "Lovelace",
        "email": "ada@example.com",
        "synthetic_data_acknowledged": "true",
        "unexpected": "value",
    }.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
        )
    parts.append(
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="resume"; filename="resume.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
        "%PDF-1.7\r\n"
        f"--{boundary}--\r\n"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/leads",
            content="".join(parts).encode(),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
    assert response.status_code in {400, 422}
    assert response.json()["type"].startswith("urn:alma-portal:problem:")
    assert submit.commands == []


@pytest.mark.asyncio
async def test_download_stream_has_private_attachment_headers() -> None:
    app, _ = build_test_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/downloads/resume", params={"ticket": "signed"})
    assert response.status_code == 200
    assert response.content == b"%PDF-1.7"
    assert response.headers["content-disposition"] == 'attachment; filename="resume.pdf"'
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.asyncio
async def test_download_ticket_url_is_absolute_public_api_url() -> None:
    app, _ = build_test_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(f"/api/v1/leads/{uuid4()}/resume-download")
    assert response.status_code == 200
    assert response.json()["url"] == (
        "https://api.alma.example/api/v1/downloads/resume?ticket=signed.ticket"
    )


@pytest.mark.asyncio
async def test_health_and_version_contracts() -> None:
    app, _ = build_test_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        live = await client.get("/health/live")
        ready = await client.get("/health/ready")
        version = await client.get("/version")
    assert live.json() == {"status": "ok"}
    assert ready.json() == {"status": "ready"}
    assert version.json() == {"commit_sha": "abc123"}
