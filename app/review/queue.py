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

    Quick-view fields (name, phone, address, services) prefer the business_data
    model when available; fall back to the Hebrew summary dict for compatibility.
    """
    summary  = result.summary or {}
    bd       = result.business_data or {}

    # Quick-view: prefer business_data (strongly-typed), fall back to summary
    incoming = bd.get("incoming_tenant") or {}
    outgoing = bd.get("outgoing_tenant") or {}
    prop_bd  = bd.get("property") or {}
    txn_bd   = bd.get("submission") or {}

    customer_name  = (
        incoming.get("full_name")
        or outgoing.get("full_name")
        or summary.get("דייר_נכנס", {}).get("שם", "")
    )
    customer_phone = (
        incoming.get("phone")
        or outgoing.get("phone")
        or summary.get("דייר_נכנס", {}).get("טלפון", "")
    )
    customer_email = (
        incoming.get("email")
        or outgoing.get("email")
        or summary.get("דייר_נכנס", {}).get("אימייל", "")
    )
    property_address = (
        prop_bd.get("full_address")
        or summary.get("פרטי_נכס", {}).get("כתובת", "")
    )
    txn_summary = summary.get("סוג_עסקה", {})
    services = (
        txn_bd.get("transfer_to")
        or txn_bd.get("package_description")
        or txn_summary.get("לאן_מעבירים")
        or txn_summary.get("שירותים")
        or txn_summary.get("שירות")
        or ""
    )
    if services == "לא סופק":
        services = ""
    mzk_ref = summary.get("מידע_פנימי", {}).get("מספר_פנייה", "")
    # BusinessSubmission.to_summary_dict() has no MZK field and emits the
    # "לא סופק" placeholder — fall back to the parsed system section.
    if not mzk_ref or mzk_ref == "לא סופק":
        mzk_ref = (result.parsed or {}).get("system", {}).get("מזהה_מזכ", "")

    return ReviewItem(
        submission_id     = result.submission_id,
        service_name      = result.service_name,
        form_title        = result.form_title,
        received_at       = result.received_at,
        customer_name     = customer_name,
        customer_phone    = customer_phone,
        customer_email    = customer_email,
        property_address  = property_address,
        services          = services,
        mzk_ref           = mzk_ref,
        status            = ReviewStatus.PENDING_REVIEW,
        summary           = summary,
        business_data     = bd,
        missing_info      = result.missing.get("missing_info", []),
        missing_docs      = result.missing.get("missing_docs", []),
        validation_issues = [i.to_dict() for i in result.validation_issues],
        doc_extractions   = result.doc_extractions,
        draft_email       = result.email,
        final_email       = None,  # operator sets this on approval
    )
