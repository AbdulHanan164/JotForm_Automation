"""
Review queue — file-based storage.

Each review item lives in:  data/review_queue/{submission_id}.json

Simple JSON files chosen deliberately:
  - Zero infrastructure (no database, no Redis)
  - Human-readable (operator can open and read)
  - Easy to backup / migrate later
  - Can be replaced with a real DB later without changing the API

When submissions grow large, replace load_all() with a proper index.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.review.models import ReviewItem, ReviewStatus

logger = logging.getLogger("webhook")


def _queue_dir() -> Path:
    from app.config import settings
    return settings.review_dir


def save(item: ReviewItem) -> Path:
    """Save or update a review item."""
    path = _queue_dir() / f"{item.submission_id}.json"
    path.write_text(
        json.dumps(item.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Review item saved: %s (status=%s)", path.name, item.status.value)
    return path


def load(submission_id: str) -> ReviewItem | None:
    """Load a review item by submission ID."""
    path = _queue_dir() / f"{submission_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ReviewItem.from_dict(data)
    except Exception as exc:
        logger.error("Failed to load review item %s: %s", submission_id, exc)
        return None


def load_all(
    status: ReviewStatus | None = None,
    limit: int = 50,
) -> list[ReviewItem]:
    """
    Load all review items, optionally filtered by status.
    Returns sorted newest-first.
    """
    items: list[ReviewItem] = []
    for path in sorted(
        _queue_dir().glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:limit * 3]:  # over-fetch to allow status filter
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            item = ReviewItem.from_dict(data)
            if status is None or item.status == status:
                items.append(item)
        except Exception as exc:
            logger.warning("Skipping corrupt review file %s: %s", path.name, exc)

    return items[:limit]


def update_status(
    submission_id: str,
    new_status:    ReviewStatus,
    notes:         str = "",
    reviewed_by:   str = "operator",
    final_email:   dict[str, str] | None = None,
) -> ReviewItem | None:
    """Update the status of an existing review item."""
    item = load(submission_id)
    if item is None:
        logger.warning("update_status: submission %s not found", submission_id)
        return None

    item.status      = new_status
    item.reviewed_at = datetime.now(timezone.utc).isoformat()
    item.reviewed_by = reviewed_by
    if notes:
        item.review_notes = notes
    if final_email is not None:
        item.final_email = final_email

    save(item)
    return item


def build_from_pipeline(result: Any) -> ReviewItem:
    """
    Build a ReviewItem from a PipelineResult.
    Called by the orchestrator after the pipeline completes.
    """
    summary  = result.summary or {}
    customer = summary.get("דייר_נכנס", {})
    prop     = summary.get("פרטי_נכס", {})
    system   = summary.get("מידע_פנימי", {})
    txn      = summary.get("סוג_עסקה", {})

    return ReviewItem(
        submission_id     = result.submission_id,
        service_name      = result.service_name,
        form_title        = result.form_title,
        received_at       = result.received_at,
        customer_name     = customer.get("שם", ""),
        customer_phone    = customer.get("טלפון", ""),
        customer_email    = customer.get("אימייל", ""),
        property_address  = prop.get("כתובת", ""),
        services          = txn.get("שירות", ""),
        mzk_ref           = system.get("מספר_פנייה", ""),
        status            = ReviewStatus.PENDING_REVIEW,
        summary           = summary,
        missing_info      = result.missing.get("missing_info", []),
        missing_docs      = result.missing.get("missing_docs", []),
        validation_issues = [i.to_dict() for i in result.validation_issues],
        doc_extractions   = result.doc_extractions,
        draft_email       = result.email,
        final_email       = None,  # operator sets this on approval
    )
