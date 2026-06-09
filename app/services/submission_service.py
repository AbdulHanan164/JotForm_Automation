"""
Submission persistence.

Saves two files per submission:
  data/submissions/{ts}_{id}_raw.json      — full technical dump (debug, AI)
  data/processed/{ts}_{id}_business.json  — clean business summary (operator-facing)

The business JSON is what operators read — Hebrew, no JotForm IDs.
The raw JSON is kept for debugging, AI enrichment, and field discovery.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.pipeline.result import PipelineResult

logger = logging.getLogger("webhook")


def _write(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    logger.info("Saved → %s (%d bytes)", path, path.stat().st_size)


def save_raw(result: PipelineResult, submissions_dir: Path) -> Path:
    """Save the full technical dump including all raw fields."""
    ts   = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = submissions_dir / f"{ts}_{result.submission_id}_raw.json"
    _write(path, result.to_raw_dict())
    return path


def save_business(result: PipelineResult, processed_dir: Path) -> Path:
    """Save the clean operator-facing business summary (Hebrew, no noise)."""
    ts   = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = processed_dir / f"{ts}_{result.submission_id}_business.json"
    _write(path, result.to_business_dict())
    return path


# ── Future integration stubs ──────────────────────────────────────────────────

def push_to_hubspot(result: PipelineResult) -> None:
    """Phase 5: Create/update a HubSpot contact + deal."""
    raise NotImplementedError("HubSpot integration not yet configured.")


def enrich_with_ai(result: PipelineResult) -> dict[str, Any]:
    """Phase 6: Send summary to OpenAI/NVIDIA for enrichment or classification."""
    raise NotImplementedError("AI enrichment not yet configured.")


def upload_to_google_drive(filepath: Path) -> None:
    """Phase 5: Upload the business summary to Google Drive."""
    raise NotImplementedError("Google Drive integration not yet configured.")
