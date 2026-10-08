"""
Scheduler worker — keeps the radar warm and delivers the daily digest.

Run standalone (this is what the docker-compose `worker` service executes):

    python -m watch.scheduler          # run forever
    python -m watch.scheduler --once   # one ingest+score+digest cycle, then exit

Jobs:
- every `schedule_interval_minutes`: ingest new items, then score the unscored
- daily at `digest_hour`: build + persist + deliver the digest

Every cycle writes a row into the `jobs` table, so the run history is visible
from the API/UI even when the worker runs in a separate container.
"""

from __future__ import annotations

import argparse
import logging
import threading
import time
import traceback
from datetime import UTC, datetime

from store import db
from utils.config import settings

logger = logging.getLogger(__name__)


def run_cycle(*, include_digest: bool = True, progress=None) -> dict:
    """
    One full maintenance cycle: ingest → score → (optional) digest.

    This is also the body of the manual "Refresh" button in the UI, kept in one
    place so scheduled and manual runs behave identically.
    """
    from watch.digest import build_digest
    from watch.ingest import run_ingest
    from watch.ranker import score_unscored

    started = time.time()
    result: dict = {"ingest": {}, "scoring": {}, "digest_id": ""}

    def emit(stage: str, detail: dict | None = None):
        if progress:
            try:
                progress(stage, detail or {})
            except Exception as exc:  # noqa: BLE001 — progress hooks are best-effort
                logger.debug("scheduler progress hook failed: %s", exc)

    emit("ingest", {})
    result["ingest"] = run_ingest(progress=progress)
    emit("scoring", {})
    result["scoring"] = score_unscored(progress=progress)

    if include_digest:
        emit("digest", {})
        digest = build_digest(persist=True)
        result["digest_id"] = digest["id"]
        result["digest_stories"] = len(digest["items"])

    result["duration_s"] = round(time.time() - started, 1)
    return result


def _as_job_record(cycle: dict, status: str = "done", error: str | None = None) -> None:
    db.create_job(
        "scheduled_cycle",
        {
            **cycle,
            "error": error,
            "ran_at": datetime.now(UTC).isoformat(),
            "status": status,
        },
    )


def _safe_cycle(include_digest: bool) -> None:
    """Run one cycle, recording success or failure as a job row."""
    try:
        cycle = run_cycle(include_digest=include_digest)
        _as_job_record(cycle)
        logger.info(
            "Scheduled cycle done: %s new / %s dupes, digest=%s (%.0fs)",
            cycle["ingest"].get("new"),
            cycle["ingest"].get("duplicates"),
            cycle.get("digest_id") or "-",
            cycle["duration_s"],
        )
    except Exception as exc:  # noqa: BLE001 — the worker must survive any cycle
        logger.error("Scheduled cycle failed: %s\n%s", exc, traceback.format_exc())
        _as_job_record({"ingest": {}, "scoring": {}}, status="error", error=str(exc))


def build_scheduler():
    """Create the APScheduler instance (factored out for tests)."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    scheduler = BlockingScheduler(timezone=str(datetime.now().astimezone().tzinfo))
    scheduler.add_job(
        lambda: _safe_cycle(include_digest=False),
        IntervalTrigger(minutes=settings.schedule_interval_minutes),
        id="ingest_score",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        lambda: _safe_cycle(include_digest=True),
        CronTrigger(hour=settings.digest_hour, minute=15),
        id="daily_digest",
        max_instances=1,
        coalesce=True,
    )
    return scheduler


def main() -> int:
    parser = argparse.ArgumentParser(description="CortexResearch scheduler worker")
    parser.add_argument("--once", action="store_true", help="Run one full cycle and exit")
    parser.add_argument(
        "--no-digest", action="store_true", help="Skip the digest step (with --once)"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )

    if args.once:
        _safe_cycle(include_digest=not args.no_digest)
        return 0

    scheduler = build_scheduler()
    logger.info(
        "Scheduler starting: ingest every %d min, digest daily at %02d:15",
        settings.schedule_interval_minutes,
        settings.digest_hour,
    )
    # Kick off one cycle in the background so a fresh deploy has data immediately.
    threading.Thread(target=_safe_cycle, kwargs={"include_digest": True}, daemon=True).start()
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
