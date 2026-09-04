import resend
import logging
from uuid import UUID

from app.config import RESEND_API_KEY, RESEND_TEST_MODE, RESEND_TEST_RECIPIENT
from app.repositories.lead_repository import get_lead
from app.logging_utils import log_event


BLOCKED_STATUSES = frozenset({"unsubscribed", "dead"})
RESEND_TEST_RECIPIENTS = frozenset({
    "delivered@resend.dev", "bounced@resend.dev", "complained@resend.dev",
    "suppressed@resend.dev",
})


class OutboundBlockedError(RuntimeError):
    pass


class ResendTestModeConfigurationError(RuntimeError):
    pass


logger = logging.getLogger(__name__)


def resolve_provider_recipient(logical_recipient: str) -> tuple[str, bool]:
    if not RESEND_TEST_MODE:
        return logical_recipient, False
    if not RESEND_TEST_RECIPIENT:
        raise ResendTestModeConfigurationError(
            "RESEND_TEST_RECIPIENT is required when RESEND_TEST_MODE is enabled"
        )
    if RESEND_TEST_RECIPIENT not in RESEND_TEST_RECIPIENTS:
        raise ResendTestModeConfigurationError(
            "RESEND_TEST_RECIPIENT must be a supported Resend test recipient"
        )
    return RESEND_TEST_RECIPIENT, True


def send_email(
    to_email: str,
    subject: str,
    body: str,
    lead_id: UUID | None = None,
    allow_test_recipient: bool = False,
) -> dict:
    """
    Send an email through Resend.
    """

    if lead_id is not None:
        lead = get_lead(lead_id)
        if not lead or (lead.get("status") or "").lower() in BLOCKED_STATUSES:
            log_event(logger, "transport_blocked", lead_id=lead_id)
            raise OutboundBlockedError("Lead status blocks outbound email")
        if lead.get("email") != to_email:
            log_event(logger, "transport_recipient_mismatch", lead_id=lead_id)
            raise OutboundBlockedError("Recipient does not match the current lead record")
    elif not (allow_test_recipient and to_email in RESEND_TEST_RECIPIENTS):
        raise OutboundBlockedError(
            "A lead_id safety check or an explicit Resend test recipient is required"
        )

    if not RESEND_API_KEY:
        raise RuntimeError("RESEND_API_KEY is not set")

    provider_recipient, test_mode = resolve_provider_recipient(to_email)
    log_event(
        logger, "recipient_routed", logical_recipient=to_email,
        provider_recipient=provider_recipient, test_mode=test_mode,
        lead_id=lead_id,
    )

    resend.api_key = RESEND_API_KEY

    params = {
        "from": "Autonomous SDR <onboarding@resend.dev>",
        "to": [provider_recipient],
        "subject": subject,
        "text": body,
    }

    response = resend.Emails.send(params)
    log_event(logger, "provider_send_accepted", lead_id=lead_id, test_mode=test_mode)

    result = dict(response)
    result["routing"] = {
        "logical_recipient": to_email,
        "provider_recipient": provider_recipient,
        "test_mode": test_mode,
    }
    return result
