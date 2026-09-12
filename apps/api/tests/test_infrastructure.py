from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from alma_api.application import DownloadGrant
from alma_api.domain import DeliveryState, MailMessage, NormalizedEmail
from alma_api.infrastructure import HmacTicketSigner, SendGridMailer, TicketError

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
        (202, DeliveryState.PROVIDER_ACCEPTED, None),
        (429, DeliveryState.FAILED, "sendgrid_retryable_429"),
        (500, DeliveryState.FAILED, "sendgrid_retryable_500"),
        (400, DeliveryState.FAILED, "sendgrid_rejected_400"),
    ],
)
async def test_sendgrid_response_classification(
    status: int,
    expected_state: DeliveryState,
    error: str | None,
) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(status, headers={"x-message-id": "provider-id"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await SendGridMailer(
            api_key="secret",
            base_url="http://127.0.0.1:4010",
            from_email="sender@example.com",
            client=client,
        ).send(message())
    assert result.state is expected_state
    assert result.sanitized_error == error
    assert captured[0].url == "http://127.0.0.1:4010/v3/mail/send"
    body = captured[0].read().decode()
    assert "text/plain" in body
    assert "text/html" in body
    assert "attachment" not in body


@pytest.mark.asyncio
async def test_sendgrid_connection_ambiguity_is_unknown() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("response may have been accepted", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await SendGridMailer(
            api_key="secret",
            base_url="https://api.sendgrid.com",
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
