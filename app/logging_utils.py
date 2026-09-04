import json
import logging
from typing import Any


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    """Emit compact structured JSON; callers must never pass credentials."""
    logger.info(json.dumps({"event": event, **fields}, default=str, sort_keys=True))
