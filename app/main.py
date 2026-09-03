from fastapi import FastAPI

app = FastAPI(
    title="Autonomous SDR Agent",
    description="Agentic lead enrichment, scoring and email outreach PoC",
    version="0.1.0",
)


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "autonomous-sdr-agent"
    }