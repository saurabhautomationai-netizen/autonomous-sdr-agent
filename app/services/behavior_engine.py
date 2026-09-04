OPT_OUT_PHRASES = {
    "not interested",
    "unsubscribe",
    "remove me",
    "stop emailing",
    "do not contact",
    "don't contact me",
    "stop",
}


def contains_opt_out(reply_text: str | None) -> bool:
    """
    Detect explicit opt-out / negative-interest intent.
    """

    if not reply_text:
        return False

    text = reply_text.lower().strip()

    return any(
        phrase in text
        for phrase in OPT_OUT_PHRASES
    )


def evaluate_behavior(
    *,
    lead_status: str,
    seconds_since_sent: int,
    valid_open_count: int = 0,
    click_count: int = 0,
    last_clicked_url: str | None = None,
    latest_reply_text: str | None = None,
    no_open_threshold_seconds: int = 60,
) -> dict:
    """
    Decide the next autonomous SDR action.

    Scenario A:
        No valid open/click after threshold
        -> send restructured-subject follow-up.

    Scenario B:
        Link clicked OR multiple valid opens
        -> send high-context follow-up.

    Scenario C:
        Opt-out / "Not interested"
        -> halt all future outreach.

    The 60-second threshold is for demo/testing.
    Production would normally use hours/days.
    """

    normalized_status = (lead_status or "").lower().strip()

    # --------------------------------------------------
    # HARD SAFETY GATE
    # --------------------------------------------------

    if normalized_status in {"unsubscribed", "dead"}:
        return {
            "action": "stop_outreach",
            "scenario": "C",
            "reason": (
                "Lead is already marked as unsubscribed/dead. "
                "No further outreach is permitted."
            ),
            "halt_outreach": True,
            "follow_up_type": None,
            "clicked_url": None,
        }

    # --------------------------------------------------
    # SCENARIO C — explicit opt-out
    # --------------------------------------------------

    if contains_opt_out(latest_reply_text):
        return {
            "action": "unsubscribe_lead",
            "scenario": "C",
            "reason": (
                "Lead explicitly opted out or indicated no interest. "
                "Future automated outreach must stop."
            ),
            "halt_outreach": True,
            "follow_up_type": None,
            "clicked_url": None,
        }

    # --------------------------------------------------
    # SCENARIO B — strong engagement
    # --------------------------------------------------

    if click_count > 0:
        return {
            "action": "send_contextual_followup",
            "scenario": "B",
            "reason": (
                "Lead clicked a tracked link, which is treated "
                "as a strong engagement signal."
            ),
            "halt_outreach": False,
            "follow_up_type": "clicked_link",
            "clicked_url": last_clicked_url,
        }

    if valid_open_count >= 2:
        return {
            "action": "send_contextual_followup",
            "scenario": "B",
            "reason": (
                "Lead generated multiple valid open events, "
                "indicating elevated engagement."
            ),
            "halt_outreach": False,
            "follow_up_type": "multiple_opens",
            "clicked_url": None,
        }

    # --------------------------------------------------
    # SCENARIO A — no engagement
    # --------------------------------------------------

    if (
        seconds_since_sent >= no_open_threshold_seconds
        and valid_open_count == 0
        and click_count == 0
    ):
        return {
            "action": "send_no_open_followup",
            "scenario": "A",
            "reason": (
                "No valid engagement was detected within "
                "the configured follow-up window."
            ),
            "halt_outreach": False,
            "follow_up_type": "restructured_subject",
            "clicked_url": None,
        }

    # --------------------------------------------------
    # Nothing should happen yet
    # --------------------------------------------------

    return {
        "action": "wait",
        "scenario": None,
        "reason": (
            "No behavioral condition currently requires "
            "an autonomous action."
        ),
        "halt_outreach": False,
        "follow_up_type": None,
        "clicked_url": None,
    }