import resend

from app.config import RESEND_WEBHOOK_SECRET
from app.repositories.email_log_repository import get_email_log_by_provider_message_id
from app.repositories.event_repository import create_event
from app.services.scanner_filter import record_open_event


SUPPORTED_EMAIL_EVENTS = {
    "email.sent": "sent", "email.delivered": "delivered",
    "email.delivery_delayed": "delivery_delayed", "email.bounced": "bounced",
    "email.complained": "complained", "email.failed": "failed",
    "email.suppressed": "suppressed", "email.opened": "open",
    "email.clicked": "click",
}


def verify_resend_webhook(payload: bytes, headers: dict[str, str]) -> dict:
    if not RESEND_WEBHOOK_SECRET:
        raise RuntimeError("RESEND_WEBHOOK_SECRET is not set")
    return resend.Webhooks.verify({
        "payload": payload.decode("utf-8"),
        "headers": {
            "id": headers.get("svix-id"),
            "timestamp": headers.get("svix-timestamp"),
            "signature": headers.get("svix-signature"),
        },
        "webhook_secret": RESEND_WEBHOOK_SECRET,
    })


def process_resend_event(event: dict, provider_event_id: str) -> dict:
    provider_type = event.get("type")
    event_type = SUPPORTED_EMAIL_EVENTS.get(provider_type)
    if not event_type:
        return {"status": "ignored", "reason": "unsupported_event_type"}
    data = event.get("data") or {}
    message_id = data.get("email_id")
    email_log = get_email_log_by_provider_message_id(message_id) if message_id else None
    if not email_log:
        return {"status": "ignored", "reason": "email_log_not_found"}
    click = data.get("click") or {}
    kwargs = {
        "lead_id": email_log["lead_id"], "email_log_id": email_log["id"],
        "metadata": {
            "provider_type": provider_type,
            "provider_created_at": event.get("created_at"),
            "provider_message_id": message_id,
            "clicked_url": click.get("link"), "provider_data": data,
        },
        "ip_address": click.get("ipAddress"), "user_agent": click.get("userAgent"),
        "provider": "resend", "provider_event_id": provider_event_id,
    }
    created = (
        record_open_event(**kwargs)
        if event_type == "open"
        else create_event(event_type=event_type, **kwargs)
    )
    return {"status": "processed" if created else "duplicate", "event": created or None}
