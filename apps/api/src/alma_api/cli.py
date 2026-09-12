"""Small, non-persistent operational checks owned by the API package."""

from __future__ import annotations

import argparse
import asyncio
import os

import httpx

from alma_api.config import required, validate_service_url
from alma_api.domain import DeliveryState, MailMessage, MailResult, NormalizedEmail
from alma_api.infrastructure import SendGridMailer


def email_smoke() -> None:
    parser = argparse.ArgumentParser(
        description="Send one SendGrid smoke message without persisting its recipient."
    )
    parser.add_argument("--to", required=True, help="Explicit unrelated test recipient")
    parser.add_argument(
        "--confirm-unrelated-recipient",
        action="store_true",
        help="Confirm the recipient is unrelated and authorized to receive this test",
    )
    arguments = parser.parse_args()
    if not arguments.confirm_unrelated_recipient:
        parser.error("--confirm-unrelated-recipient is required")
    recipient = NormalizedEmail.parse(arguments.to)
    sender = NormalizedEmail.parse(required("SENDGRID_FROM_EMAIL"))
    attorney = os.getenv("ATTORNEY_NOTIFICATION_EMAIL")
    forbidden = {sender.value}
    if attorney:
        forbidden.add(NormalizedEmail.parse(attorney).value)
    if recipient.value in forbidden:
        parser.error("--to must be an unrelated recipient, not a configured application address")
    base_url = os.getenv("SENDGRID_BASE_URL", "https://api.sendgrid.com").rstrip("/")
    validate_service_url(
        base_url,
        environment=os.getenv("ENVIRONMENT", "development"),
        setting="SENDGRID_BASE_URL",
    )
    result = asyncio.run(
        _send_smoke(
            api_key=required("SENDGRID_API_KEY"),
            base_url=base_url,
            sender=sender,
            recipient=recipient,
        )
    )
    print(f"SendGrid smoke result: {result.state.value}")
    if result.state is not DeliveryState.PROVIDER_ACCEPTED:
        raise SystemExit(1)


async def _send_smoke(
    *,
    api_key: str,
    base_url: str,
    sender: NormalizedEmail,
    recipient: NormalizedEmail,
) -> MailResult:
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(5.0),
        follow_redirects=False,
    ) as client:
        mailer = SendGridMailer(
            api_key=api_key,
            base_url=base_url,
            from_email=sender.value,
            client=client,
        )
        return await mailer.send(
            MailMessage(
                recipient=recipient,
                subject="AlmaPortal SendGrid smoke test",
                plain_body="This is an authorized AlmaPortal SendGrid smoke test.",
                html_body="<p>This is an authorized AlmaPortal SendGrid smoke test.</p>",
            )
        )
