"""
Submission persistence — v0.6.0.

Three files per submission:
  data/submissions/{ts}_{id}_raw.json      — full technical dump (debug / AI)
  data/processed/{ts}_{id}_business.json  — clean business summary (operators)
  data/review_queue/{id}.json              — review workflow item (mutable)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.pipeline.result import PipelineResult

logger = logging.getLogger("webhook")


def _write(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    logger.info("Saved → %s (%d bytes)", path, path.stat().st_size)


def save_raw(result: PipelineResult, submissions_dir: Path) -> Path:
    """Save full technical dump."""
    ts   = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = submissions_dir / f"{ts}_{result.submission_id}_raw.json"
    _write(path, result.to_raw_dict())
    return path


def save_business(result: PipelineResult, processed_dir: Path) -> Path:
    """Save clean operator-facing business summary."""
    ts   = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = processed_dir / f"{ts}_{result.submission_id}_business.json"
    _write(path, result.to_business_dict())
    return path


def save_for_review(result: PipelineResult) -> Path:
    """Save to the review queue for human approval."""
    from app.review.queue import build_from_pipeline, save
    item = build_from_pipeline(result)
    return save(item)

