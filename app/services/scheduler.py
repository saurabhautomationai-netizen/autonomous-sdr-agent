import asyncio
import logging

from app.config import NO_OPEN_THRESHOLD_SECONDS, SCHEDULER_POLL_INTERVAL_SECONDS
from app.logging_utils import log_event
from app.repositories.scheduler_repository import get_due_no_open_leads
from app.services.behavior_orchestrator import process_lead_behavior


logger = logging.getLogger(__name__)


def run_scheduler_once() -> list[dict]:
    due = get_due_no_open_leads(NO_OPEN_THRESHOLD_SECONDS)
    log_event(logger, "scheduler_poll", due_count=len(due))
    results = []
    for lead in due:
        try:
            result = process_lead_behavior(
                lead_id=lead["lead_id"],
                lead_status=lead["lead_status"],
                seconds_since_sent=lead["seconds_since_sent"],
                execute_actions=True,
            )
            results.append(result)
            log_event(
                logger, "scheduler_evaluation_complete",
                lead_id=lead["lead_id"], action=result["decision"]["action"],
                execution_status=(result.get("execution") or {}).get("status"),
            )
        except Exception as error:
            logger.exception(
                "scheduler evaluation failed lead_id=%s error_type=%s",
                lead["lead_id"], type(error).__name__,
            )
    return results


async def run_scheduler(stop_event: asyncio.Event) -> None:
    """Poll until shutdown; Event-based waiting makes shutdown immediate and safe."""
    log_event(
        logger, "scheduler_started",
        poll_interval_seconds=SCHEDULER_POLL_INTERVAL_SECONDS,
        no_open_threshold_seconds=NO_OPEN_THRESHOLD_SECONDS,
    )
    try:
        while not stop_event.is_set():
            await asyncio.to_thread(run_scheduler_once)
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=SCHEDULER_POLL_INTERVAL_SECONDS
                )
            except asyncio.TimeoutError:
                pass
    finally:
        log_event(logger, "scheduler_stopped")
