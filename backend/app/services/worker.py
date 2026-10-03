"""Background worker that ingests documents waiting to be processed."""

from __future__ import annotations

import threading

from app.core.logging import get_logger
from app.services.ingestion import IngestionService

logger = get_logger(__name__)


class IngestionWorker:
    """Polls for documents awaiting ingestion and processes them.

    This is the local stand-in for the queue and consumer that drive ingestion in the
    AWS deployment, and it is deliberately not a request background task. FastAPI runs
    a response's background tasks *before* it exits the request's dependency
    generators, so a task scheduled from a handler would run while the row it was
    meant to process was still uncommitted: it would not see the document, and its
    writes would contend with the request's still-open transaction. A worker that owns
    its own sessions has neither problem.

    It assumes a single process. Two uvicorn workers would both poll the same
    documents, which is why claiming work atomically is the queue's job in AWS.
    """

    def __init__(self, ingestion: IngestionService, *, poll_seconds: float) -> None:
        self._ingestion = ingestion
        self._poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        """Whether the worker thread is alive."""
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Start the worker thread, if it is not already running."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="ingestion-worker", daemon=True)
        self._thread.start()
        logger.info("ingestion_worker_started", poll_seconds=self._poll_seconds)

    def stop(self, timeout: float = 5.0) -> None:
        """Ask the worker to finish and wait for the current cycle."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
            logger.info("ingestion_worker_stopped")

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                processed = self._ingestion.run_pending()
            except Exception:
                # A failed cycle must not kill the thread, so it is logged and the loop
                # carries on. Whatever went wrong is already recorded on the document.
                logger.exception("ingestion_worker_cycle_failed")
                processed = 0

            if processed == 0:
                # Waiting between empty cycles keeps the worker from spinning while
                # still picking up new work promptly.
                self._stop.wait(self._poll_seconds)
