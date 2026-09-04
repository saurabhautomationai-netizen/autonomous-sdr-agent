import logging
import re

from app.services.enrichment_providers import (
    apollo_people_match,
    hunter_email_finder,
)
from app.logging_utils import log_event


logger = logging.getLogger(__name__)


ROLE_PREFIXES = {
    "info",
    "hello",
    "sales",
    "support",
    "contact",
    "admin",
    "team",
}


def normalize_name(name: str) -> tuple[str, str]:
    parts = [
        re.sub(r"[^a-zA-Z]", "", part).lower()
        for part in name.split()
        if part.strip()
    ]

    if not parts:
        return "", ""

    first = parts[0]
    last = parts[-1] if len(parts) > 1 else ""

    return first, last


def generate_email_candidates(name: str, domain: str) -> list[str]:
    first, last = normalize_name(name)

    if not first or not domain:
        return []

    candidates = set()

    if last:
        candidates.update(
            {
                f"{first}.{last}@{domain}",
                f"{first}{last}@{domain}",
                f"{first[0]}{last}@{domain}",
                f"{first}@{domain}",
            }
        )
    else:
        candidates.add(f"{first}@{domain}")

    return sorted(candidates)


def is_valid_email_format(email: str) -> bool:
    pattern = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"
    return bool(re.match(pattern, email))


def score_email_candidate(
    email: str,
    name: str,
    domain: str,
    provider_confidence: float | None = None,
    provider_verification_status: str | None = None,
) -> float:
    score = 0.0

    if not is_valid_email_format(email):
        return 0.0

    local_part, email_domain = email.split("@", 1)

    if email_domain.lower() == domain.lower():
        score += 40

    first, last = normalize_name(name)

    if local_part in ROLE_PREFIXES:
        score -= 30

    if first and last:
        if local_part == f"{first}.{last}":
            score += 35
        elif local_part == f"{first}{last}":
            score += 30
        elif local_part == f"{first[0]}{last}":
            score += 25
        elif local_part == first:
            score += 15

    elif first and local_part == first:
        score += 25

    if provider_confidence is not None:
        score += min(max(provider_confidence, 0), 100) * 0.25

    verification_bonus = {
        "valid": 15,
        "verified": 15,
        "accept_all": 5,
        "extrapolated": 3,
    }
    score += verification_bonus.get(
        (provider_verification_status or "").lower().strip(), 0
    )

    return round(max(score, 0), 2)


def rank_email_candidates(
    name: str,
    domain: str,
    provider_results: list[dict] | None = None,
) -> list[dict]:
    candidates = {}

    for email in generate_email_candidates(name, domain):
        candidates[email] = {
            "email": email,
            "source": "generated_pattern",
            "provider_confidence": None,
            "verification_status": None,
            "provider_metadata": {},
        }

    if provider_results:
        for result in provider_results:
            email = result.get("email")

            if not email:
                continue

            normalized = {
                "email": email,
                "source": result.get("source", "provider"),
                "provider_confidence": result.get("confidence"),
                "verification_status": result.get("verification_status"),
                "provider_metadata": result.get("provider_metadata") or {},
            }
            existing = candidates.get(email)
            if not existing or _candidate_evidence_rank(normalized) > _candidate_evidence_rank(existing):
                candidates[email] = normalized

    ranked = []

    for candidate in candidates.values():
        candidate["candidate_score"] = score_email_candidate(
            email=candidate["email"],
            name=name,
            domain=domain,
            provider_confidence=candidate["provider_confidence"],
            provider_verification_status=candidate["verification_status"],
        )

        candidate["score"] = candidate["candidate_score"]  # compatibility alias
        candidate["provider_verification_confidence"] = candidate.pop(
            "provider_confidence"
        )
        candidate["provider_verification_status"] = candidate.pop(
            "verification_status"
        )
        ranked.append(candidate)

    source_priority = {"hunter": 2, "apollo": 1, "generated_pattern": 0}
    ranked.sort(key=lambda item: (
        -item["candidate_score"],
        -source_priority.get(item["source"], 0),
        item["email"].lower(),
    ))

    return ranked


def select_primary_email(
    name: str,
    domain: str,
    provider_results: list[dict] | None = None,
) -> dict | None:
    ranked = rank_email_candidates(
        name=name,
        domain=domain,
        provider_results=provider_results,
    )

    if not ranked:
        return None

    return ranked[0]

def _candidate_evidence_rank(candidate: dict) -> tuple:
    status_priority = {"valid": 3, "verified": 3, "accept_all": 2, "extrapolated": 1}
    return (
        candidate.get("provider_confidence") is not None,
        candidate.get("provider_confidence") or -1,
        status_priority.get((candidate.get("verification_status") or "").lower(), 0),
    )


def primary_enrichment_provider(
    name: str,
    company: str,
    domain: str,
) -> list[dict]:
    """Backward-compatible primary-provider wrapper (Hunter)."""
    return hunter_email_finder(name=name, company=company, domain=domain)[0]


def fallback_enrichment_provider(
    name: str,
    company: str,
    domain: str,
) -> list[dict]:
    """Backward-compatible secondary-provider wrapper (Apollo)."""
    return apollo_people_match(name=name, company=company, domain=domain)[0]

def enrich_lead(
    name: str,
    company: str,
    domain: str,
) -> dict:
    """
    Execute waterfall enrichment and deterministically
    select the best recipient.
    """

    enrichment_steps = []

    # Step 1: Hunter (primary)
    primary_results, hunter_step = hunter_email_finder(
        name=name,
        company=company,
        domain=domain,
    )

    enrichment_steps.append(hunter_step)
    log_event(logger, "enrichment_provider_result", **hunter_step)

    provider_results = list(primary_results)

    # Step 2: Apollo only if Hunter misses or is unavailable.
    if not primary_results:
        fallback_results, apollo_step = apollo_people_match(
            name=name,
            company=company,
            domain=domain,
        )

        enrichment_steps.append(apollo_step)
        log_event(logger, "enrichment_provider_result", **apollo_step)

        provider_results.extend(fallback_results)

    # Local patterns always remain available and are ranked deterministically.
    enrichment_steps.append({
        "provider": "local_pattern", "status": "success",
        "results_found": len(generate_email_candidates(name, domain)), "error": None,
    })

    # Step 3: deterministic ranking
    ranked_candidates = rank_email_candidates(
        name=name,
        domain=domain,
        provider_results=provider_results,
    )

    primary_email = ranked_candidates[0] if ranked_candidates else None
    log_event(
        logger, "enrichment_ranked", domain=domain,
        candidate_count=len(ranked_candidates),
        selected_source=(primary_email or {}).get("source"),
    )

    return {
        "name": name,
        "company": company,
        "domain": domain,
        "primary_email": primary_email,
        "candidates": ranked_candidates,
        "waterfall_steps": enrichment_steps,
    }
