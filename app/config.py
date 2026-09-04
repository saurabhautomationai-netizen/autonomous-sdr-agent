import os

from dotenv import load_dotenv


load_dotenv()


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise RuntimeError(f"Invalid boolean configuration value: {value!r}")

DATABASE_URL = os.getenv("DATABASE_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_WEBHOOK_SECRET = os.getenv("RESEND_WEBHOOK_SECRET")
RESEND_TEST_MODE = parse_bool(os.getenv("RESEND_TEST_MODE"), default=False)
RESEND_TEST_RECIPIENT = os.getenv("RESEND_TEST_RECIPIENT", "delivered@resend.dev").strip()
HUNTER_API_KEY = os.getenv("HUNTER_API_KEY")
APOLLO_API_KEY = os.getenv("APOLLO_API_KEY")
ENRICHMENT_PROVIDER_TIMEOUT_SECONDS = float(
    os.getenv("ENRICHMENT_PROVIDER_TIMEOUT_SECONDS", "8")
)

NO_OPEN_THRESHOLD_SECONDS = int(os.getenv("NO_OPEN_THRESHOLD_SECONDS", "60"))
SCANNER_OPEN_BURST_COUNT = int(os.getenv("SCANNER_OPEN_BURST_COUNT", "20"))
SCANNER_OPEN_BURST_WINDOW_SECONDS = int(
    os.getenv("SCANNER_OPEN_BURST_WINDOW_SECONDS", "5")
)
SCHEDULER_POLL_INTERVAL_SECONDS = float(
    os.getenv("SCHEDULER_POLL_INTERVAL_SECONDS", "10")
)
SCANNER_IMMEDIATE_OPEN_SECONDS = float(
    os.getenv("SCANNER_IMMEDIATE_OPEN_SECONDS", "2")
)
