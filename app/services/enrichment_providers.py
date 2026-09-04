import requests

from app.config import (
    APOLLO_API_KEY,
    ENRICHMENT_PROVIDER_TIMEOUT_SECONDS,
    HUNTER_API_KEY,
)


HUNTER_EMAIL_FINDER_URL = "https://api.hunter.io/v2/email-finder"
APOLLO_PEOPLE_MATCH_URL = "https://api.apollo.io/api/v1/people/match"


def _split_name(name: str) -> tuple[str, str]:
    parts = name.strip().split()
    return (parts[0], parts[-1] if len(parts) > 1 else "") if parts else ("", "")


def _error_status(provider: str, error: Exception) -> dict:
    """Return a useful, secret-free provider step result."""
    response = getattr(error, "response", None)
    status_code = getattr(response, "status_code", None)
    if isinstance(error, requests.Timeout):
        code = "timeout"
    elif status_code == 429:
        code = "quota_or_rate_limited"
    elif status_code in {401, 403}:
        code = "authentication_or_plan_restricted"
    elif status_code:
        code = f"http_{status_code}"
    else:
        code = "unavailable"
    return {"provider": provider, "status": "error", "results_found": 0, "error": code}


def hunter_email_finder(
    *, name: str, company: str, domain: str,
    timeout: float = ENRICHMENT_PROVIDER_TIMEOUT_SECONDS,
) -> tuple[list[dict], dict]:
    if not HUNTER_API_KEY:
        return [], {"provider": "hunter", "status": "not_configured", "results_found": 0}
    first, last = _split_name(name)
    hunter_params = {"domain": domain}
    if last:
        hunter_params.update({"first_name": first, "last_name": last})
    else:
        hunter_params["full_name"] = name.strip()
    try:
        response = requests.get(
            HUNTER_EMAIL_FINDER_URL,
            params=hunter_params,
            headers={"X-API-KEY": HUNTER_API_KEY, "Accept": "application/json"},
            timeout=timeout,
        )
        response.raise_for_status()
        data = (response.json() or {}).get("data") or {}
    except (requests.RequestException, ValueError, TypeError, AttributeError) as error:
        return [], _error_status("hunter", error)

    email = data.get("email")
    candidates = []
    if email:
        verification = data.get("verification") or {}
        candidates.append({
            "email": email,
            "source": "hunter",
            "confidence": data.get("score"),
            "verification_status": verification.get("status"),
            "provider_metadata": {
                "accept_all": data.get("accept_all"),
                "verification_date": verification.get("date"),
            },
        })
    return candidates, {
        "provider": "hunter", "status": "success" if candidates else "miss",
        "results_found": len(candidates), "error": None,
    }


def apollo_people_match(
    *, name: str, company: str, domain: str,
    timeout: float = ENRICHMENT_PROVIDER_TIMEOUT_SECONDS,
) -> tuple[list[dict], dict]:
    if not APOLLO_API_KEY:
        return [], {"provider": "apollo", "status": "not_configured", "results_found": 0}
    first, last = _split_name(name)
    try:
        response = requests.post(
            APOLLO_PEOPLE_MATCH_URL,
            headers={
                "x-api-key": APOLLO_API_KEY, "Content-Type": "application/json",
                "Accept": "application/json", "Cache-Control": "no-cache",
            },
            json={
                "first_name": first, "last_name": last,
                "organization_name": company, "domain": domain,
                "reveal_personal_emails": False, "reveal_phone_number": False,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json() or {}
        if not isinstance(payload, dict):
            raise TypeError("malformed provider response")
        person = payload.get("person") or {}
        provider_error = payload.get("error") or payload.get("errors")
        if not person and (provider_error or payload.get("message")):
            text = str(provider_error or payload.get("message")).lower()
            if "rate" in text or "quota" in text:
                code = "quota_or_rate_limited"
            elif "auth" in text or "api key" in text or "permission" in text:
                code = "authentication_or_plan_restricted"
            elif "plan" in text or "credit" in text:
                code = "authentication_or_plan_restricted"
            else:
                code = "provider_error"
            return [], {
                "provider": "apollo", "status": "error",
                "results_found": 0, "error": code,
            }
    except (requests.RequestException, ValueError, TypeError, AttributeError) as error:
        return [], _error_status("apollo", error)

    email = person.get("email")
    # Apollo documents a bracketed placeholder for unrevealed addresses.
    if email and email.strip().startswith("["):
        email = None
    candidates = []
    if email:
        candidates.append({
            "email": email,
            "source": "apollo",
            "confidence": None,
            "verification_status": person.get("email_status"),
            "provider_metadata": {"person_id": person.get("id")},
        })
    return candidates, {
        "provider": "apollo", "status": "success" if candidates else "miss",
        "results_found": len(candidates), "error": None,
    }
