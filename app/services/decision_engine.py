from typing import Literal


DecisionAction = Literal[
    "send_outreach",
    "needs_review",
    "skip_lead",
]


def decide_lead_action(
    final_score: int,
    classification: str,
) -> dict:
    """
    Convert a scored lead into an SDR action.

    Rules:
    75-100  -> send_outreach
    45-74   -> needs_review
    0-44    -> skip_lead
    """

    if not 0 <= final_score <= 100:
        raise ValueError("final_score must be between 0 and 100")

    classification = (classification or "").lower().strip()

    if final_score >= 75:
        action: DecisionAction = "send_outreach"
        reason = (
            "Lead passed the outreach threshold and is considered "
            "a strong fit based on authority, ICP fit, and contextual scoring."
        )

    elif final_score >= 45:
        action = "needs_review"
        reason = (
            "Lead shows moderate fit but does not meet the automatic "
            "outreach threshold. Additional qualification is recommended."
        )

    else:
        action = "skip_lead"
        reason = (
            "Lead score is below the minimum qualification threshold "
            "and should not receive automated outreach."
        )

    return {
        "final_score": final_score,
        "classification": classification,
        "action": action,
        "reason": reason,
        "outreach_allowed": action == "send_outreach",
    }