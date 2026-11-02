"""Standalone worker: runs the poller and scheduler with no HTTP server.

Used for multi-process / Kubernetes deployments where a single dedicated
worker does the SNMP polling and background jobs while the API replicas serve
requests (RACKMON_POLLER_ENABLED=false on the API). Run with:

    python -m app.worker
"""
from __future__ import annotations

import asyncio
import logging

from .config import get_settings
from .database import init_db
from .services.poller import run_poller
from .services.scheduler import run_scheduler

log = logging.getLogger("rackmon.worker")


async def _run() -> None:
    settings = get_settings()
    init_db()
    stop = asyncio.Event()
    log.info("RackMon worker starting (poller + scheduler, env=%s)", settings.environment)
    tasks = [
        asyncio.create_task(run_poller(stop)),
        asyncio.create_task(run_scheduler(stop)),
    ]
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:  # pragma: no cover
        stop.set()
        raise


def main() -> None:  # pragma: no cover - process entrypoint
    logging.basicConfig(
        level=logging.INFO,
        format='{"level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
    )
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":  # pragma: no cover
    main()
