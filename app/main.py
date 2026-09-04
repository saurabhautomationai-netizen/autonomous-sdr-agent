import logging
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from app.repositories.lead_repository import update_lead_enrichment, update_lead_score
from app.services.enrichment import enrich_lead
from app.services.lead_extractor import UnsafeExtractionURL, extract_lead_from_url
from app.services.lead_scoring import calculate_lead_score
from app.repositories.event_repository import create_event
from app.services.behavior_engine import contains_opt_out
from app.services.behavior_orchestrator import process_lead_behavior
from app.services.resend_webhook import process_resend_event, verify_resend_webhook
from app.services.scanner_filter import record_open_event
from app.services.initial_outreach import execute_initial_outreach
from app.logging_utils import configure_logging, log_event

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Autonomous SDR Agent",
    description="Agentic lead enrichment, scoring and email outreach PoC",
    version="0.1.0",
)


class LeadExtractionRequest(BaseModel):
    url: str


class LeadEnrichmentRequest(BaseModel):
    name: str
    company: str
    domain: str

class PersistedLeadEnrichmentRequest(BaseModel):
    name: str
    company: str
    domain: str

class LeadScoringRequest(BaseModel):
    name: str
    title: str
    company: str
    bio: str
    employee_count: int | None = None
    industry: str | None = None
    email_confidence: float | None = None

class OpenEventRequest(BaseModel):
    lead_id: UUID
    email_log_id: UUID | None = None


class ClickEventRequest(BaseModel):
    lead_id: UUID
    email_log_id: UUID | None = None
    clicked_url: str


class ReplyEventRequest(BaseModel):
    lead_id: UUID
    email_log_id: UUID | None = None
    reply_text: str


class BehaviorRequest(BaseModel):
    lead_status: str
    seconds_since_sent: int


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "autonomous-sdr-agent",
    }


@app.post("/leads/extract")
def extract_lead_endpoint(request: LeadExtractionRequest):
    log_event(logger, "extraction_started", source_url_provided=bool(request.url))
    try:
        result = extract_lead_from_url(request.url)
    except UnsafeExtractionURL as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    log_event(logger, "extraction_completed")
    return result


@app.post("/leads/enrich")
def enrich_lead_endpoint(request: LeadEnrichmentRequest):
    log_event(logger, "enrichment_started", domain=request.domain)
    result = enrich_lead(
        name=request.name,
        company=request.company,
        domain=request.domain,
    )
    log_event(logger, "enrichment_completed", domain=request.domain)
    return result


@app.post("/leads/{lead_id}/enrich")
def enrich_and_save_lead(
    lead_id: UUID,
    request: PersistedLeadEnrichmentRequest,
):
    enrichment = enrich_lead(
        name=request.name,
        company=request.company,
        domain=request.domain,
    )

    primary = enrichment.get("primary_email")

    if not primary:
        raise HTTPException(
            status_code=422,
            detail="No suitable email candidate found",
        )

    updated_lead = update_lead_enrichment(
        lead_id=lead_id,
        email=primary["email"],
        email_confidence=primary["provider_verification_confidence"],
        candidate_score=primary["candidate_score"],
        provider_source=primary["source"],
        verification_status=primary["provider_verification_status"],
        enrichment_metadata={
            "waterfall_steps": enrichment["waterfall_steps"],
            "selected_provider_metadata": primary["provider_metadata"],
        },
    )

    if not updated_lead:
        raise HTTPException(
            status_code=404,
            detail="Lead not found",
        )

    return {
        "enrichment": enrichment,
        "database_record": updated_lead,
    }

@app.post("/leads/score")
def score_lead_endpoint(request: LeadScoringRequest):
    result = calculate_lead_score(
        name=request.name,
        title=request.title,
        company=request.company,
        bio=request.bio,
        employee_count=request.employee_count,
        industry=request.industry,
        email_confidence=request.email_confidence,
    )
    log_event(
        logger, "scoring_completed", company=request.company,
        final_score=result["final_score"], classification=result["classification"],
    )
    return result

@app.post("/events/open")
def create_open_event(request: OpenEventRequest):
    return record_open_event(
        lead_id=request.lead_id,
        email_log_id=request.email_log_id,
        metadata={},
    )


@app.post("/events/click")
def create_click_event(request: ClickEventRequest):
    return create_event(
        lead_id=request.lead_id,
        email_log_id=request.email_log_id,
        event_type="click",
        metadata={
            "clicked_url": request.clicked_url,
        },
    )


@app.post("/events/reply")
def create_reply_event(request: ReplyEventRequest):
    reply_text = request.reply_text.strip()

    is_opt_out = contains_opt_out(reply_text)

    event_type = "unsubscribe" if is_opt_out else "reply"

    return create_event(
        lead_id=request.lead_id,
        email_log_id=request.email_log_id,
        event_type=event_type,
        metadata={
            "reply_text": reply_text,
            "is_opt_out": is_opt_out,
        },
    )


@app.post("/leads/{lead_id}/score")
def score_and_save_lead(lead_id: UUID, request: LeadScoringRequest):
    scoring = score_lead_endpoint(request)
    updated = update_lead_score(
        lead_id=lead_id,
        score=scoring["final_score"],
        classification=scoring["classification"],
        score_reason=scoring["score_reason"],
        score_metadata={
            "rule_score": scoring["rule_score"],
            "llm_score": scoring["llm_score"],
            "rule_breakdown": scoring["rule_breakdown"],
            "authority_matches": scoring["authority_matches"],
        },
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"scoring": scoring, "database_record": updated}


@app.post("/leads/{lead_id}/behavior")
def run_behavior(lead_id: UUID, request: BehaviorRequest):
    return process_lead_behavior(
        lead_id=lead_id,
        lead_status=request.lead_status,
        seconds_since_sent=request.seconds_since_sent,
    )


@app.post("/leads/{lead_id}/initial-outreach")
def initial_outreach(lead_id: UUID):
    try:
        return execute_initial_outreach(lead_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/webhooks/resend")
async def resend_webhook(request: Request):
    required_headers = ("svix-id", "svix-timestamp", "svix-signature")
    if any(not request.headers.get(header) for header in required_headers):
        raise HTTPException(status_code=400, detail="Missing required webhook headers")
    payload = await request.body()
    try:
        event = verify_resend_webhook(payload, dict(request.headers))
    except (ValueError, RuntimeError, UnicodeDecodeError) as error:
        raise HTTPException(status_code=400, detail="Invalid webhook") from error
    return process_resend_event(event, request.headers.get("svix-id"))
