"""
Human review API.

Operators use these endpoints to review, approve, reject, or flag submissions.
Email is NEVER sent automatically — only after explicit approval here.

Endpoints:
  GET  /review                    — list pending reviews (newest first)
  GET  /review/all                — list all reviews regardless of status
  GET  /review/{id}               — full review item
  GET  /review/{id}/email         — the draft email (plain text, RTL Hebrew)
  POST /review/{id}/approve       — approve and return final email for sending
  POST /review/{id}/reject        — reject with a reason
  POST /review/{id}/needs_info    — flag for follow-up
  PUT  /review/{id}/email         — operator edits the draft email before approving
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import JSONResponse, PlainTextResponse

from app.review import queue as Q
from app.review.models import ReviewStatus

router = APIRouter(prefix="/review", tags=["review"])
logger = logging.getLogger("webhook")


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("", summary="List pending reviews")
def list_pending(limit: int = Query(50, ge=1, le=200)):
    """List submissions waiting for operator review."""
    items = Q.load_all(status=ReviewStatus.PENDING_REVIEW, limit=limit)
    return _summary_list(items)


@router.get("/all", summary="List all reviews")
def list_all(
    status: str | None = Query(None, description="Filter by status"),
    limit:  int        = Query(50, ge=1, le=200),
):
    """List all reviews, optionally filtered by status."""
    s = ReviewStatus(status) if status else None
    items = Q.load_all(status=s, limit=limit)
    return _summary_list(items)


def _summary_list(items):
    rows = []
    for item in items:
        rows.append({
            "submission_id":    item.submission_id,
            "mzk_ref":         item.mzk_ref,
            "received_at":      item.received_at,
            "service":          item.services,
            "customer":         item.customer_name,
            "phone":            item.customer_phone,
            "address":          item.property_address,
            "status":           item.status.value,
            "has_errors":       item.has_errors,
            "has_warnings":     item.has_warnings,
            "missing_info":     [i["label"] for i in item.missing_info],
            "missing_docs":     [i["label"] for i in item.missing_docs],
            "validation_count": len(item.validation_issues),
            "email_ready":      item.draft_email is not None,
        })
    return {"count": len(rows), "items": rows}


# ── Detail ────────────────────────────────────────────────────────────────────

@router.get("/{submission_id}", summary="Full review item")
def get_review(submission_id: str):
    """Return the full review item for an operator."""
    item = _get_or_404(submission_id)
    return JSONResponse(content=item.to_dict())


@router.get("/{submission_id}/email", summary="Draft email (plain text)")
def get_email(submission_id: str):
    """Return the draft email as plain RTL Hebrew text."""
    item = _get_or_404(submission_id)
    email = item.final_email or item.draft_email
    if not email:
        return PlainTextResponse(
            "אין טיוטת מייל לפנייה זו — כל הפרטים מולאו.",
            media_type="text/plain; charset=utf-8",
        )
    subject = email.get("subject", "")
    body    = email.get("body", "")
    return PlainTextResponse(
        f"Subject: {subject}\n\n{body}",
        media_type="text/plain; charset=utf-8",
    )


# ── Actions ───────────────────────────────────────────────────────────────────

@router.post("/{submission_id}/approve", summary="Approve and get email to send")
def approve(
    submission_id: str,
    notes:       str = Body("", embed=True),
    reviewed_by: str = Body("operator", embed=True),
):
    """
    Mark as approved.
    Returns the final email for the operator to send manually via Gmail.
    Email is NOT sent automatically.
    """
    item = _get_or_404(submission_id)
    if not item.is_actionable:
        raise HTTPException(
            status_code=409,
            detail=f"הפנייה כבר טופלה (status={item.status.value})",
        )

    updated = Q.update_status(
        submission_id = submission_id,
        new_status    = ReviewStatus.APPROVED,
        notes         = notes,
        reviewed_by   = reviewed_by,
        final_email   = item.final_email or item.draft_email,
    )

    logger.info("Submission %s APPROVED by %s", submission_id, reviewed_by)

    email = updated.final_email or updated.draft_email
    return {
        "status":       "approved",
        "submission_id": submission_id,
        "email_to_send": email,
        "message": (
            "הפנייה אושרה. שלח את המייל הבא ללקוח באופן ידני דרך Gmail."
            if email else
            "הפנייה אושרה. אין מייל לשליחה — ההגשה מלאה."
        ),
    }


@router.post("/{submission_id}/reject", summary="Reject a submission")
def reject(
    submission_id: str,
    reason:      str = Body(..., embed=True),
    reviewed_by: str = Body("operator", embed=True),
):
    """Reject a submission with a mandatory reason."""
    item = _get_or_404(submission_id)
    if not item.is_actionable:
        raise HTTPException(
            status_code=409,
            detail=f"הפנייה כבר טופלה (status={item.status.value})",
        )

    Q.update_status(
        submission_id = submission_id,
        new_status    = ReviewStatus.REJECTED,
        notes         = reason,
        reviewed_by   = reviewed_by,
    )
    logger.info("Submission %s REJECTED by %s: %s", submission_id, reviewed_by, reason)
    return {"status": "rejected", "submission_id": submission_id, "reason": reason}


@router.post("/{submission_id}/needs_info", summary="Flag for more information")
def needs_info(
    submission_id: str,
    notes:       str = Body(..., embed=True),
    reviewed_by: str = Body("operator", embed=True),
):
    """Flag a submission as needing more information before approval."""
    item = _get_or_404(submission_id)
    Q.update_status(
        submission_id = submission_id,
        new_status    = ReviewStatus.NEEDS_INFO,
        notes         = notes,
        reviewed_by   = reviewed_by,
    )
    return {"status": "needs_info", "submission_id": submission_id, "notes": notes}


@router.put("/{submission_id}/email", summary="Edit draft email")
def edit_email(
    submission_id: str,
    subject: str = Body(..., embed=True),
    body:    str = Body(..., embed=True),
):
    """Operator edits the draft email before approving."""
    item = _get_or_404(submission_id)
    Q.update_status(
        submission_id = submission_id,
        new_status    = item.status,  # keep current status
        final_email   = {"subject": subject, "body": body},
    )
    return {
        "status":  "email_updated",
        "message": "הטיוטה עודכנה. עכשיו ניתן לאשר את הפנייה."
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_or_404(submission_id: str):
    item = Q.load(submission_id)
    if item is None:
        raise HTTPException(
            status_code=404,
            detail=f"פנייה {submission_id} לא נמצאה",
        )
    return item
