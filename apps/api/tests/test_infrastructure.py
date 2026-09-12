from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from alma_api.application import DownloadGrant
from alma_api.domain import DeliveryState, MailMessage, NormalizedEmail
from alma_api.infrastructure import HmacTicketSigner, ResendMailer, TicketError

NOW = datetime(2026, 2, 3, 10, tzinfo=UTC)


def message() -> MailMessage:
    return MailMessage(
        recipient=NormalizedEmail.parse("recipient@example.net"),
        subject="Subject",
        plain_body="plain",
        html_body="<p>html</p>",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected_state", "error"),
    [
        (200, DeliveryState.PROVIDER_ACCEPTED, None),
        (429, DeliveryState.FAILED, "resend_retryable_429"),
        (500, DeliveryState.FAILED, "resend_retryable_500"),
        (400, DeliveryState.FAILED, "resend_rejected_400"),
    ],
)
async def test_resend_response_classification(
    status: int,
    expected_state: DeliveryState,
    error: str | None,
) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if status == 200:
            return httpx.Response(status, json={"id": "provider-id"})
        return httpx.Response(status)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ResendMailer(
            api_key="secret",
            base_url="http://127.0.0.1:4010",
            from_email="sender@example.com",
            client=client,
        ).send(message())
    assert result.state is expected_state
    assert result.sanitized_error == error
    if expected_state is DeliveryState.PROVIDER_ACCEPTED:
        assert result.provider_message_id == "provider-id"
    assert captured[0].url == "http://127.0.0.1:4010/emails"
    body = json.loads(captured[0].read().decode())
    assert body["from"] == "sender@example.com"
    assert body["to"] == ["recipient@example.net"]
    assert body["text"] == "plain"
    assert body["html"] == "<p>html</p>"
    assert "attachment" not in body
    assert "attachments" not in body


@pytest.mark.asyncio
async def test_resend_accepted_without_id_uses_fallback_provider_id() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": ""})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ResendMailer(
            api_key="secret",
            base_url="http://127.0.0.1:4010",
            from_email="sender@example.com",
            client=client,
        ).send(message())
    assert result.state is DeliveryState.PROVIDER_ACCEPTED
    assert result.provider_message_id == "resend-accepted-without-id"


@pytest.mark.asyncio
async def test_resend_connection_ambiguity_is_unknown() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("response may have been accepted", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ResendMailer(
            api_key="secret",
            base_url="https://api.resend.com",
            from_email="sender@example.com",
            client=client,
        ).send(message())
    assert result.state is DeliveryState.UNKNOWN
    assert result.sanitized_error
    assert result.sanitized_error.startswith("connection_ambiguous:")


def test_download_ticket_is_bound_signed_and_expires() -> None:
    signer = HmacTicketSigner(b"x" * 32)
    lead_id = uuid4()
    reviewer_id = uuid4()
    token = signer.issue(
        DownloadGrant(
            lead_id=lead_id,
            reviewer_id=reviewer_id,
            object_key=f"leads/{lead_id}/{uuid4()}.pdf",
            expires_at=NOW + timedelta(seconds=60),
        )
    )
    grant = signer.verify(token, NOW)
    assert grant.lead_id == lead_id
    assert grant.reviewer_id == reviewer_id
    payload, signature = token.split(".")
    replacement = "A" if signature[0] != "A" else "B"
    with pytest.raises(TicketError):
        signer.verify(f"{payload}.{replacement}{signature[1:]}", NOW)
    with pytest.raises(TicketError, match="expired"):
        signer.verify(token, NOW + timedelta(seconds=60))
