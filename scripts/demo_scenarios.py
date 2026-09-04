"""Safe, deterministic scenario helper: no database, providers, LLM, or email."""
from datetime import datetime, timedelta, timezone

from app.services.behavior_engine import evaluate_behavior
from app.services.scanner_filter import detect_scanner_burst


def main() -> None:
    cases = {
        "A_no_open": dict(lead_status="contacted", seconds_since_sent=60),
        "B_click": dict(
            lead_status="contacted", seconds_since_sent=10, click_count=1,
            last_clicked_url="https://example.com/demo",
        ),
        "B_multiple_opens": dict(
            lead_status="contacted", seconds_since_sent=10, valid_open_count=2,
        ),
        "C_unsubscribe": dict(
            lead_status="contacted", seconds_since_sent=10,
            latest_reply_text="Please unsubscribe me",
        ),
        "already_unsubscribed": dict(
            lead_status="unsubscribed", seconds_since_sent=600,
        ),
    }
    for label, inputs in cases.items():
        print(label, evaluate_behavior(**inputs))

    start = datetime.now(timezone.utc)
    opens = [start + timedelta(milliseconds=200 * index) for index in range(20)]
    print("scanner_burst", detect_scanner_burst(opens))


if __name__ == "__main__":
    main()
