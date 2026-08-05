"""
Operator insights — READ-ONLY routes.

New surface, added alongside the dashboard rather than inside it, so no
existing route, template or workflow is touched:

  GET /insights             advisory overview of the queue (display only)
  GET /insights/{sid}       all advisory signals for one case
  GET /insights/json/{sid}  the same payload as JSON (operator API key)

These endpoints only READ stored review items and document manifests. They
never approve, send, merge, re-classify or write anything, and they do not
change the real review queue or its ordering.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.auth import require_operator
from app.review import queue as Q
from app.review.insights import build, build_queue

# Reused read-only from the dashboard module: template engine, i18n, cookie auth.
from app.routes.dashboard import (
    _TEMPLATES,
    _i18n,
    _is_authed,
    _redirect_login,
    STATUS_META,
)

router = APIRouter(prefix="/insights", tags=["insights"])

# Labels for this view only — the dashboard's own i18n table is untouched.
_L = {
    "he": {
        "title": "תובנות למפעיל",
        "subtitle": "מידע מסייע בלבד — אינו משנה נתונים, אינו מאשר ואינו שולח",
        "th_mzk": "MZK", "th_customer": "לקוח", "th_type": "סוג בקשה",
        "th_priority": "דחיפות", "th_conf": "ביטחון", "th_rec": "המלצה",
        "th_risk": "סימני סיכון", "th_dup": "כפילויות", "th_missing": "חסר",
        "th_age": "ימים", "th_status": "סטטוס",
        "sec_summary": "סיכום המקרה", "sec_conf": "ציון ביטחון",
        "sec_risk": "סימני סיכון", "sec_cons": "בדיקת עקביות",
        "sec_docs": "איכות מסמכים", "sec_dup": "כפילויות אפשריות",
        "sec_tips": "המלצות למפעיל", "sec_prio": "דחיפות",
        "back_queue": "חזרה לרשימה", "open_case": "פתיחת המקרה",
        "advisory": "תצוגה בלבד — לא מתבצעת שום פעולה אוטומטית",
        "none": "אין", "no_dup": "לא נמצאו כפילויות",
    },
    "en": {
        "title": "Operator insights",
        "subtitle": "Advisory only — changes no data, approves nothing, sends nothing",
        "th_mzk": "MZK", "th_customer": "Customer", "th_type": "Request type",
        "th_priority": "Priority", "th_conf": "Confidence", "th_rec": "Recommendation",
        "th_risk": "Risk flags", "th_dup": "Duplicates", "th_missing": "Missing",
        "th_age": "Days", "th_status": "Status",
        "sec_summary": "Case summary", "sec_conf": "Confidence score",
        "sec_risk": "Risk indicators", "sec_cons": "Consistency check",
        "sec_docs": "Document quality", "sec_dup": "Possible duplicates",
        "sec_tips": "Operator insights", "sec_prio": "Priority",
        "back_queue": "Back to list", "open_case": "Open the case",
        "advisory": "Display only — no automatic action is taken",
        "none": "none", "no_dup": "no possible duplicates found",
    },
}


def _ins(request: Request) -> dict:
    ctx = _i18n(request)
    ctx["ins"] = _L.get(ctx.get("lang", "he"), _L["he"])
    return ctx


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def insights_overview(request: Request):
    """Advisory overview. Does not alter the review queue or its ordering."""
    if not _is_authed(request):
        return _redirect_login()
    items = Q.load_all(status=None, limit=500)
    rows = build_queue(items)
    ctx = _ins(request)
    return _TEMPLATES.TemplateResponse(request, "dashboard/insights.html", {
        **ctx,
        "rows": rows,
        "status_meta": STATUS_META,
        "total": len(rows),
    })


@router.get("/{submission_id}", response_class=HTMLResponse)
def insights_case(request: Request, submission_id: str):
    """All nine advisory signals for one case."""
    if not _is_authed(request):
        return _redirect_login()
    item = Q.load(submission_id)
    if item is None:
        return HTMLResponse("<p>not found</p>", status_code=404)
    others = Q.load_all(status=None, limit=500)
    counts: dict[str, int] = {}
    for it in others:
        bd = getattr(it, "business_data", None) or {}
        t = (bd.get("submission") or {}).get("transaction_type") or ""
        counts[t] = counts.get(t, 0) + 1
    data = build(item, others=others, type_counts=counts)
    ctx = _ins(request)
    return _TEMPLATES.TemplateResponse(request, "dashboard/insights_case.html", {
        **ctx,
        "d": data,
        "item": item.to_dict(),
        "status_meta": STATUS_META,
    })


@router.get("/json/{submission_id}")
def insights_case_json(submission_id: str, _op: str = Depends(require_operator)):
    """Machine-readable copy of the same advisory payload."""
    item = Q.load(submission_id)
    if item is None:
        return JSONResponse({"detail": "not found"}, status_code=404)
    others = Q.load_all(status=None, limit=500)
    counts: dict[str, int] = {}
    for it in others:
        bd = getattr(it, "business_data", None) or {}
        t = (bd.get("submission") or {}).get("transaction_type") or ""
        counts[t] = counts.get(t, 0) + 1
    return build(item, others=others, type_counts=counts)
