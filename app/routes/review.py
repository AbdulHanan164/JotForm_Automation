"""
Human review API — v0.6.0.

v0.6 CHANGE: All endpoints now require X-API-Key authentication.
Email is NEVER sent automatically — only after explicit operator approval.

Endpoints:
  GET  /review                    — list pending reviews (newest first)
  GET  /review/all                — list all reviews regardless of status
  GET  /review/{id}               — full review item
  GET  /review/{id}/email         — the draft email (plain text, RTL Hebrew)
  POST /review/{id}/approve       — approve and return final email for sending
  POST /review/{id}/reject        — reject with a reason
  POST /review/{id}/needs_info    — flag for follow-up
  POST /review/{id}/sent          — mark email as actually sent (NEW in v0.6)
  PUT  /review/{id}/email         — operator edits the draft email before approving
"""
from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, PlainTextResponse

from app.auth import require_operator
from app.review import queue as Q
from app.review.models import ReviewStatus

router = APIRouter(prefix="/review", tags=["review"])
logger = logging.getLogger("webhook")

# Type alias for the auth dependency
_Auth = Annotated[str, Depends(require_operator)]


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("", summary="List pending reviews")
def list_pending(
    limit: int = Query(50, ge=1, le=200),
    _op: _Auth = None,
):
    """List submissions waiting for operator review."""
    items = Q.load_all(status=ReviewStatus.PENDING_REVIEW, limit=limit)
    return _summary_list(items)


@router.get("/all", summary="List all reviews")
def list_all(
    status: str | None = Query(None, description="Filter by status"),
    limit:  int        = Query(50, ge=1, le=200),
    _op: _Auth = None,
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
            "mzk_ref":          item.mzk_ref,
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
def get_review(submission_id: str, _op: _Auth = None):
    """
    Return the full review item for an operator.

    Response includes two extra fields computed lazily here (not in the pipeline):
      operator_summary — Layer A: 30-second triage view with inline ⚠️ and recommendation.
      detail_record    — Layer B: full archive with account numbers and internal refs.
    """
    item = _get_or_404(submission_id)
    payload = item.to_dict()

    # Compute Layer A + B from the stored pieces (business_data + pipeline outputs).
    # This is intentionally lazy — Stage 7 runs before missing/validation detection,
    # so we can only build the complete inline-warning view here at read time.
    operator_summary: Any = None
    detail_record:    Any = None

    bd = item.business_data
    if bd:
        try:
            from app.mappers.models import BusinessSubmission
            from app.services.arnona.summary import build_layer_a, build_layer_b

            bs = BusinessSubmission.from_dict(bd)

            operator_summary = build_layer_a(
                bs,
                missing_info       = item.missing_info       or [],
                missing_docs       = item.missing_docs       or [],
                validation_issues  = [
                    vi if isinstance(vi, dict) else vi.__dict__
                    for vi in (item.validation_issues or [])
                ],
            )

            detail_record = build_layer_b(
                bs,
                mzk_ref      = item.mzk_ref      or "",
                refund_id    = (item.summary or {}).get("מידע_פנימי", {}).get("מזהה_החזר", ""),
                submitted_at = item.received_at   or "",
            )
        except Exception as exc:
            logger.warning("Layer A/B build failed for %s: %s", submission_id, exc)

    payload["operator_summary"] = operator_summary
    payload["detail_record"]    = detail_record

    return JSONResponse(content=payload)


@router.get("/{submission_id}/email", summary="Draft email (plain text)")
def get_email(submission_id: str, _op: _Auth = None):
    """Return the draft email as plain RTL Hebrew text."""
    item  = _get_or_404(submission_id)
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
    notes:              str  = Body("", embed=True),
    reviewed_by:        str  = Body("operator", embed=True),
    override_errors:    bool = Body(False, embed=True),
    _op: _Auth = None,
):
    """
    Mark as approved.
    Returns the final email for the operator to send manually via Gmail.
    Email is NOT sent automatically.

    If validation errors exist, set override_errors=true with a reason in notes.
    """
    item = _get_or_404(submission_id)
    if not item.is_actionable:
        raise HTTPException(
            status_code=409,
            detail=f"הפנייה כבר טופלה (status={item.status.value})",
        )

    # Block approval on errors unless explicitly overridden
    if item.has_errors and not override_errors:
        raise HTTPException(
            status_code=422,
            detail=(
                "הפנייה מכילה שגיאות. "
                "כדי לאשר בכל זאת, שלח override_errors=true עם הסבר ב-notes."
            ),
        )

    if item.has_errors and override_errors and not notes:
        raise HTTPException(
            status_code=422,
            detail="override_errors=true מחייב הסבר ב-notes.",
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
    _op: _Auth = None,
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
    _op: _Auth = None,
):
    """Flag a submission as needing more information before approval."""
    _get_or_404(submission_id)
    Q.update_status(
        submission_id = submission_id,
        new_status    = ReviewStatus.NEEDS_INFO,
        notes         = notes,
        reviewed_by   = reviewed_by,
    )
    return {"status": "needs_info", "submission_id": submission_id, "notes": notes}


@router.post("/{submission_id}/sent", summary="Mark email as sent")
def mark_sent(
    submission_id: str,
    reviewed_by: str = Body("operator", embed=True),
    _op: _Auth = None,
):
    """
    Mark that the approved email has been sent manually.
    Transitions status from 'approved' to 'sent'.
    This is the final workflow step.
    """
    item = _get_or_404(submission_id)
    if item.status != ReviewStatus.APPROVED:
        raise HTTPException(
            status_code=409,
            detail=f"ניתן לסמן כנשלח רק פניות מאושרות (status={item.status.value})",
        )
    Q.update_status(
        submission_id = submission_id,
        new_status    = ReviewStatus.SENT,
        reviewed_by   = reviewed_by,
    )
    logger.info("Submission %s marked SENT by %s", submission_id, reviewed_by)
    return {"status": "sent", "submission_id": submission_id}


@router.put("/{submission_id}/email", summary="Edit draft email")
def edit_email(
    submission_id: str,
    subject: str = Body(..., embed=True),
    body:    str = Body(..., embed=True),
    _op: _Auth = None,
):
    """Operator edits the draft email before approving."""
    item = _get_or_404(submission_id)
    Q.update_status(
        submission_id = submission_id,
        new_status    = item.status,
        final_email   = {"subject": subject, "body": body},
    )
    return {
        "status":  "email_updated",
        "message": "הטיוטה עודכנה. עכשיו ניתן לאשר את הפנייה."
    }


# ── Helper ────────────────────────────────────────────────────────────────────

def _get_or_404(submission_id: str):
    item = Q.load(submission_id)
    if item is None:
        raise HTTPException(
            status_code=404,
            detail=f"פנייה {submission_id} לא נמצאה",
        )
    return item
