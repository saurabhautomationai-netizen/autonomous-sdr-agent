import json
import logging
import re

from openai import OpenAI

from app.config import OPENAI_API_KEY, OPENAI_MODEL
from app.logging_utils import log_event


logger = logging.getLogger(__name__)

# Maximum deterministic score = 90
#
# Title / seniority       = 30
# Bio authority evidence  = 25
# Company / ICP fit       = 25
# Email quality           = 10
# -----------------------------
# Deterministic total     = 90
#
# LLM contextual score    = 10  (added later)
# Final total             = 100


DECISION_MAKER_TITLES = {
    "ceo": 30,
    "founder": 30,
    "co-founder": 30,
    "chief revenue officer": 30,
    "cro": 30,
    "chief sales officer": 30,
    "vp of sales": 28,
    "vice president of sales": 28,
    "vp sales": 28,
    "head of sales": 26,
    "sales director": 24,
    "director of sales": 24,
    "sales manager": 16,
    "marketing manager": 12,
    "sales coordinator": 4,
    "assistant": 2,
    "intern": 0,
}


AUTHORITY_KEYWORDS = {
    "owns revenue": 8,
    "revenue responsibility": 8,
    "decision maker": 8,
    "budget": 5,
    "procurement": 5,
    "manages team": 5,
    "leads team": 5,
    "go-to-market": 4,
    "gtm": 4,
    "strategy": 3,
}


GENERIC_BUZZWORDS = {
    "innovative",
    "transformation",
    "collaboration",
    "customer success",
    "growth mindset",
    "results-driven",
    "dynamic leader",
}


def score_title(title: str) -> int:
    """
    Score lead seniority / decision-making authority.

    Maximum: 30 points.
    """

    title_lower = re.sub(r"\s+", " ", (title or "").lower().strip())

    if re.search(r"\b(?:assistant|intern)\s+to\b", title_lower):
        return 2 if title_lower.startswith("assistant") else 0

    for key, score in DECISION_MAKER_TITLES.items():
        if re.search(rf"(?<!\w){re.escape(key)}(?!\w)", title_lower):
            return score

    return 5


def score_bio_keywords(bio: str) -> tuple[int, list[str]]:
    """
    Score explicit evidence of decision-making authority.

    Generic corporate buzzwords do not earn points.

    Maximum: 25 points.
    """

    bio_lower = (bio or "").lower()

    score = 0
    matched = []

    for keyword, points in AUTHORITY_KEYWORDS.items():
        if re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", bio_lower):
            score += points
            matched.append(keyword)

    # Detect buzzword-heavy bios with no real authority evidence.
    buzzword_count = sum(
        1
        for buzzword in GENERIC_BUZZWORDS
        if re.search(rf"(?<!\w){re.escape(buzzword)}(?!\w)", bio_lower)
    )

    if buzzword_count >= 3 and not matched:
        score = 0

    return min(score, 25), matched


def score_company_fit(
    employee_count: int | None,
    industry: str | None,
) -> int:
    """
    Score Ideal Customer Profile (ICP) fit.

    Company size: maximum 15
    Industry:     maximum 10

    Total maximum: 25.
    """

    size_score = 0
    industry_score = 0

    if employee_count is not None:
        if 50 <= employee_count <= 500:
            size_score = 15
        elif 10 <= employee_count < 50:
            size_score = 10
        elif 500 < employee_count <= 2000:
            size_score = 8

    if industry:
        industry_lower = industry.lower()

        if any(
            keyword in industry_lower
            for keyword in (
                "software",
                "saas",
                "technology",
                "ai",
                "automation",
            )
        ):
            industry_score = 10

    return min(size_score + industry_score, 25)


def score_email_quality(
    email_confidence: float | None,
) -> int:
    """
    Score email quality.

    Maximum: 10 points.

    This input is provider verification confidence only. Internal candidate
    ranking is separate and must not be presented as provider verification.
    """

    if email_confidence is None:
        return 0

    if email_confidence >= 90:
        return 10

    if email_confidence >= 75:
        return 7

    if email_confidence >= 50:
        return 4

    return 1


def calculate_rule_score(
    title: str,
    bio: str,
    employee_count: int | None,
    industry: str | None,
    email_confidence: float | None,
) -> dict:
    """
    Calculate deterministic lead score.

    Maximum deterministic score: 90.
    """

    title_score = score_title(title)

    bio_score, authority_matches = score_bio_keywords(bio)

    company_score = score_company_fit(
        employee_count=employee_count,
        industry=industry,
    )

    email_score = score_email_quality(email_confidence)

    total = (
        title_score
        + bio_score
        + company_score
        + email_score
    )

    # Defensive guard. Under the defined weights this should never exceed 90.
    total = min(total, 90)

    return {
        "score": total,
        "max_score": 90,
        "breakdown": {
            "title_score": title_score,
            "bio_authority_score": bio_score,
            "company_fit_score": company_score,
            "email_quality_score": email_score,
        },
        "authority_matches": authority_matches,
    }

def calculate_llm_score(
    name: str,
    title: str,
    company: str,
    bio: str,
    industry: str | None,
) -> dict:
    """
    Contextual LLM evaluation.

    Maximum: 10 points.

    The LLM supplements deterministic rules rather than
    controlling the overall lead score.
    """

    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")

    client = OpenAI(api_key=OPENAI_API_KEY)

    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {
                "role": "system",
                "content": (
                    "You evaluate B2B sales leads for an autonomous SDR system. "
                    "Evaluate whether the person appears to have meaningful "
                    "decision-making authority and relevance to a B2B technology "
                    "or automation offering. "
                    "Do not reward generic corporate buzzwords unless the bio "
                    "contains concrete evidence of authority, ownership, budget, "
                    "team leadership, revenue responsibility, procurement, or "
                    "go-to-market responsibility."
                ),
            },
            {
                "role": "user",
                "content": f"""
Evaluate this lead.

Name: {name}
Title: {title}
Company: {company}
Industry: {industry}
Bio: {bio}

Give a contextual fit score from 0 to 10.

0 = clearly poor prospect
5 = moderate / uncertain prospect
10 = exceptionally strong decision-maker and relevant prospect
""",
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "lead_context_score",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "score": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 10,
                        },
                        "reason": {
                            "type": "string",
                        },
                    },
                    "required": ["score", "reason"],
                    "additionalProperties": False,
                },
            }
        },
    )

    return json.loads(response.output_text)

def calculate_lead_score(
    name: str,
    title: str,
    company: str,
    bio: str,
    employee_count: int | None,
    industry: str | None,
    email_confidence: float | None,
) -> dict:
    """
    Calculate final hybrid lead score out of 100.

    Deterministic rules: maximum 90
    LLM contextual evaluation: maximum 10
    """

    rule_result = calculate_rule_score(
        title=title,
        bio=bio,
        employee_count=employee_count,
        industry=industry,
        email_confidence=email_confidence,
    )

    llm_result = calculate_llm_score(
        name=name,
        title=title,
        company=company,
        bio=bio,
        industry=industry,
    )

    final_score = min(
        rule_result["score"] + llm_result["score"],
        100,
    )

    if final_score >= 75:
        classification = "high"
    elif final_score >= 45:
        classification = "medium"
    else:
        classification = "poor"

    log_event(
        logger, "lead_scored", company=company, final_score=final_score,
        classification=classification, rule_score=rule_result["score"],
        llm_score=llm_result["score"],
    )

    return {
        "final_score": final_score,
        "classification": classification,
        "rule_score": rule_result["score"],
        "llm_score": llm_result["score"],
        "score_reason": llm_result["reason"],
        "rule_breakdown": rule_result["breakdown"],
        "authority_matches": rule_result["authority_matches"],
    }
