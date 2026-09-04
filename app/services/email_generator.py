import json
import logging

from openai import OpenAI

from app.config import OPENAI_API_KEY, OPENAI_MODEL
from app.logging_utils import log_event


logger = logging.getLogger(__name__)


def generate_initial_email(
    name: str,
    title: str,
    company: str,
    score_reason: str,
) -> dict:
    """
    Generate a concise personalized SDR outreach email.
    """

    log_event(logger, "email_generation_started", email_type="initial", company=company)
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")

    client = OpenAI(api_key=OPENAI_API_KEY)

    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {
                "role": "system",
                "content": (
                    "You write concise B2B SDR outreach emails. "
                    "Do not make unsupported claims. "
                    "Do not use spammy language. "
                    "Keep the email professional and brief."
                ),
            },
            {
    "role": "user",
    "content": f"""
Create an initial outreach email for this test lead.

Name: {name}
Title: {title}
Company: {company}

Lead context:
{score_reason}

Sender name: Saurabh Shinde

Requirements:
- Subject under 60 characters
- Body under 120 words
- Mention the company naturally
- Use a low-pressure CTA
- Do not invent facts
- Sign off as "Saurabh Shinde"
- Never use placeholders like [Your Name]
- Use natural paragraph breaks
""",
},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "outreach_email",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "subject": {
                            "type": "string",
                        },
                        "body": {
                            "type": "string",
                        },
                    },
                    "required": [
                        "subject",
                        "body",
                    ],
                    "additionalProperties": False,
                },
            }
        },
    )

    result = json.loads(response.output_text)
    log_event(logger, "email_generation_completed", email_type="initial", company=company)
    return result


def generate_followup_email(
    *,
    name: str,
    company: str,
    follow_up_type: str,
    clicked_url: str | None = None,
) -> dict:
    """Generate a brief follow-up without revealing behavioral tracking."""
    log_event(logger, "email_generation_started", email_type=follow_up_type, company=company)
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")

    context = (
        f"The prior email linked to {clicked_url}; use its topic as context, "
        "but never state or imply that a click was tracked."
        if clicked_url
        else "The recipient showed repeat interest; provide useful context without mentioning tracking."
    )
    if follow_up_type == "restructured_subject":
        context = "There was no engagement. Use a distinctly restructured subject and a fresh angle."

    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {
                "role": "system",
                "content": (
                    "Write concise, truthful B2B follow-up emails. Do not mention opens, "
                    "click tracking, surveillance, or unsupported facts."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Write a follow-up to {name} at {company}. {context} "
                    "Return a subject under 60 characters and body under 100 words, "
                    "with a low-pressure CTA and sign off as Saurabh Shinde."
                ),
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "followup_email",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {"subject": {"type": "string"}, "body": {"type": "string"}},
                    "required": ["subject", "body"],
                    "additionalProperties": False,
                },
            }
        },
    )
    result = json.loads(response.output_text)
    log_event(logger, "email_generation_completed", email_type=follow_up_type, company=company)
    return result
