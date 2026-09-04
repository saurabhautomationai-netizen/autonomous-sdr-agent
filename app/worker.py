import asyncio
import signal

from app.logging_utils import configure_logging
from app.services.scheduler import run_scheduler


async def _main() -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_shutdown(*_args) -> None:
        loop.call_soon_threadsafe(stop_event.set)

    for signal_name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_name, request_shutdown)
        except (NotImplementedError, RuntimeError):
            signal.signal(signal_name, request_shutdown)

    await run_scheduler(stop_event)


if __name__ == "__main__":
    configure_logging()
    asyncio.run(_main())
