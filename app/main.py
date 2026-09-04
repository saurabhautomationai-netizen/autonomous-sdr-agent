from fastapi import FastAPI
from pydantic import BaseModel

from app.services.lead_extractor import extract_lead_from_url


app = FastAPI(
    title="Autonomous SDR Agent",
    description="Agentic lead enrichment, scoring and email outreach PoC",
    version="0.1.0",
)


class LeadExtractionRequest(BaseModel):
    url: str


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "autonomous-sdr-agent",
    }


@app.post("/leads/extract")
def extract_lead_endpoint(request: LeadExtractionRequest):
    return extract_lead_from_url(request.url)