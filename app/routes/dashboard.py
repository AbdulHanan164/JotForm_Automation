"""
Operator dashboard — server-rendered HTML (Jinja2) at /dashboard.

Design constraints honored:
  - No separate frontend project. Jinja2 templates served by FastAPI.
  - Reuses the existing review queue (app.review.queue) and models — it does
    NOT touch the webhook or document pipeline.
  - Auth reuses OPERATOR_API_KEY: the operator logs in once with the same key,
    which is stored in an HttpOnly cookie and checked on every page. The JSON
    API (X-API-Key) is unchanged and continues to work in parallel.

Pages:
  GET  /dashboard                      list with status tabs + search
  GET  /dashboard/review/{id}          detail (customer, property, missing,
                                       email preview, documents, actions)
  POST /dashboard/review/{id}/approve  | reject | needs_info   (form actions)
  GET  /dashboard/documents/{id}/{f}   serve a downloaded document (preview/dl)
  GET/POST /dashboard/login            cookie login (same OPERATOR_API_KEY)
  GET  /dashboard/logout
"""
from __future__ import annotations

import logging
import secrets
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.review import queue as Q
from app.review.models import ReviewStatus

logger = logging.getLogger("webhook")


def _settings():
    # Lazy — mirrors app.auth so config reloads (tests) are always picked up.
    from app.config import settings
    return settings


router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

_COOKIE = "dash_key"
_LANG_COOKIE = "dash_lang"

# Badge color class per status (labels are translated via _T[lang]["status"]).
STATUS_META: dict[str, dict[str, str]] = {
    "pending_review": {"cls": "badge-pending"},
    "needs_info":     {"cls": "badge-info"},
    "approved":       {"cls": "badge-approved"},
    "rejected":       {"cls": "badge-rejected"},
    "sent":           {"cls": "badge-sent"},
}

# Status tabs on the list page, in order (labels resolved per language).
TAB_KEYS = ["all", "pending_review", "needs_info", "approved", "rejected", "sent"]

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}

# ── i18n — UI chrome only (submission data stays in its original language) ─────
_T: dict[str, dict] = {
    "he": {
        "brand": "מה זה קל · לוח בקרה למפעיל", "nav_submissions": "פניות",
        "logout": "התנתקות", "toggle": "English",
        "login_title": "כניסת מפעיל",
        "login_hint": "הזן את מפתח המפעיל (OPERATOR_API_KEY) כדי להיכנס.",
        "login_key_ph": "מפתח מפעיל", "login_btn": "כניסה", "login_err": "מפתח שגוי. נסה שוב.",
        "list_title": "פניות לבדיקה", "tab_all": "הכל",
        "search_ph": "חיפוש: שם לקוח, MZK, כתובת, טלפון, מספר הגשה…",
        "search_btn": "חיפוש", "clear_btn": "נקה",
        "th_mzk": "MZK", "th_customer": "לקוח", "th_phone": "טלפון", "th_address": "כתובת",
        "th_service": "שירות", "th_missing": "חסר", "th_status": "סטטוס", "th_received": "התקבל",
        "info_word": "מידע", "docs_word": "מסמכים", "no_rows": "אין פניות התואמות את הסינון.",
        "back": "← חזרה לרשימה", "sec_customer": "פרטי לקוח",
        "lbl_fullname": "שם מלא", "lbl_phone": "טלפון", "lbl_email": "אימייל", "lbl_id": "תעודת זהות",
        "sec_property": "פרטי נכס", "lbl_address": "כתובת", "lbl_city": "עיר",
        "lbl_movein": "תאריך כניסה", "lbl_leaseend": "סיום חוזה",
        "sec_missing_info": "מידע חסר", "none_missing_info": "אין מידע חסר.",
        "sec_missing_docs": "מסמכים חסרים", "none_missing_docs": "אין מסמכים חסרים.",
        "sec_validation": "בדיקות עקביות", "sec_documents": "מסמכים שהורדו",
        "no_documents": "לא הורדו מסמכים עבור הגשה זו.", "download": "הורדה",
        "sec_email": "תצוגת מייל מוצע", "email_subject": "נושא:",
        "no_email": "אין טיוטת מייל (ההגשה מלאה).", "sec_actions": "פעולות",
        "override_label": "אשר למרות שגיאות עקביות",
        "override_ph": "הסבר (חובה באישור עם שגיאות)",
        "approve_btn": "✓ אשר", "needsinfo_ph": "מה חסר / נדרש מהלקוח?",
        "needsinfo_btn": "↻ נדרש מידע", "reject_ph": "סיבת דחייה (חובה)", "reject_btn": "✕ דחה",
        "handled": "הפנייה כבר טופלה. סטטוס:", "review_notes": "הערות בדיקה",
        "confirm_approve": "לאשר את הפנייה? המייל יישלח ידנית לאחר מכן.",
        "confirm_reject": "לדחות את הפנייה?",
        "status": {"pending_review": "ממתין לבדיקה", "needs_info": "נדרש מידע",
                   "approved": "אושר", "rejected": "נדחה", "sent": "נשלח"},
        "flash": {"approved": "הפנייה אושרה. שלח את המייל ללקוח באופן ידני.",
                  "rejected": "הפנייה נדחתה.", "needs_info": "הפנייה סומנה כ'נדרש מידע'.",
                  "already_handled": "הפנייה כבר טופלה.",
                  "override_needed": "הפנייה מכילה שגיאות. סמן 'אשר למרות שגיאות' עם הסבר.",
                  "need_reason": "חובה לציין סיבת דחייה.", "need_notes": "חובה לציין הערה."},
    },
    "en": {
        "brand": "Mazeh Kal · Operator Dashboard", "nav_submissions": "Submissions",
        "logout": "Logout", "toggle": "עברית",
        "login_title": "Operator Login",
        "login_hint": "Enter the operator key (OPERATOR_API_KEY) to sign in.",
        "login_key_ph": "Operator key", "login_btn": "Sign in", "login_err": "Wrong key. Try again.",
        "list_title": "Submissions for review", "tab_all": "All",
        "search_ph": "Search: customer, MZK, address, phone, submission id…",
        "search_btn": "Search", "clear_btn": "Clear",
        "th_mzk": "MZK", "th_customer": "Customer", "th_phone": "Phone", "th_address": "Address",
        "th_service": "Service", "th_missing": "Missing", "th_status": "Status", "th_received": "Received",
        "info_word": "info", "docs_word": "docs", "no_rows": "No submissions match the filter.",
        "back": "← Back to list", "sec_customer": "Customer details",
        "lbl_fullname": "Full name", "lbl_phone": "Phone", "lbl_email": "Email", "lbl_id": "ID number",
        "sec_property": "Property details", "lbl_address": "Address", "lbl_city": "City",
        "lbl_movein": "Move-in date", "lbl_leaseend": "Lease end",
        "sec_missing_info": "Missing information", "none_missing_info": "No missing information.",
        "sec_missing_docs": "Missing documents", "none_missing_docs": "No missing documents.",
        "sec_validation": "Consistency checks", "sec_documents": "Downloaded documents",
        "no_documents": "No documents downloaded for this submission.", "download": "Download",
        "sec_email": "Draft email preview", "email_subject": "Subject:",
        "no_email": "No draft email (submission complete).", "sec_actions": "Actions",
        "override_label": "Approve despite consistency errors",
        "override_ph": "Explanation (required when overriding errors)",
        "approve_btn": "✓ Approve", "needsinfo_ph": "What is missing / needed from the customer?",
        "needsinfo_btn": "↻ Needs info", "reject_ph": "Rejection reason (required)", "reject_btn": "✕ Reject",
        "handled": "Already handled. Status:", "review_notes": "Review notes",
        "confirm_approve": "Approve this submission? The email is sent manually afterward.",
        "confirm_reject": "Reject this submission?",
        "status": {"pending_review": "Pending review", "needs_info": "Needs info",
                   "approved": "Approved", "rejected": "Rejected", "sent": "Sent"},
        "flash": {"approved": "Submission approved. Send the email to the customer manually.",
                  "rejected": "Submission rejected.", "needs_info": "Submission flagged as 'needs info'.",
                  "already_handled": "Submission already handled.",
                  "override_needed": "Submission has errors. Tick 'approve despite errors' with a note.",
                  "need_reason": "A rejection reason is required.", "need_notes": "A note is required."},
    },
}


def _i18n(request: Request) -> dict:
    """Context fragment: current language, text direction, and string table."""
    lang = request.cookies.get(_LANG_COOKIE, "he")
    if lang not in ("he", "en"):
        lang = "he"
    return {
        "lang": lang,
        "dir": "rtl" if lang == "he" else "ltr",
        "t": _T[lang],
        "status_meta": STATUS_META,
    }


# ── Auth (reuses OPERATOR_API_KEY via cookie) ─────────────────────────────────

def _expected_key() -> str:
    return _settings().operator_api_key.strip()


def _is_authed(request: Request) -> bool:
    expected = _expected_key()
    if not expected:
        return True  # auth disabled (dev) — mirrors require_operator behavior
    provided = request.cookies.get(_COOKIE, "")
    return bool(provided) and secrets.compare_digest(provided, expected)


def _redirect_login() -> RedirectResponse:
    return RedirectResponse("/dashboard/login", status_code=303)


# ── Login / logout ────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, error: str = ""):
    if _is_authed(request):
        return RedirectResponse("/dashboard", status_code=303)
    return _TEMPLATES.TemplateResponse(
        request, "dashboard/login.html", {**_i18n(request), "error": error}
    )


@router.post("/login")
def login_submit(request: Request, api_key: str = Form(...)):
    expected = _expected_key()
    if expected and not secrets.compare_digest(api_key.strip(), expected):
        ctx = _i18n(request)
        return _TEMPLATES.TemplateResponse(
            request, "dashboard/login.html",
            {**ctx, "error": ctx["t"]["login_err"]},
            status_code=401,
        )
    resp = RedirectResponse("/dashboard", status_code=303)
    resp.set_cookie(
        _COOKIE,
        api_key.strip(),
        httponly=True,
        samesite="lax",
        secure=(request.url.scheme == "https"),
        max_age=60 * 60 * 12,  # 12h session
    )
    return resp


@router.get("/logout")
def logout():
    resp = RedirectResponse("/dashboard/login", status_code=303)
    resp.delete_cookie(_COOKIE)
    return resp


@router.get("/lang/{code}")
def set_language(request: Request, code: str):
    """Switch UI language (he/en) and return to the page the operator was on."""
    nxt = request.headers.get("referer") or "/dashboard"
    resp = RedirectResponse(nxt, status_code=303)
    resp.set_cookie(
        _LANG_COOKIE, "en" if code == "en" else "he",
        samesite="lax", max_age=60 * 60 * 24 * 30,
    )
    return resp


# ── List page ───────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
def dashboard_home(request: Request, status: str = "all", q: str = ""):
    if not _is_authed(request):
        return _redirect_login()

    items = Q.load_all(status=None, limit=200)

    counts = {key: 0 for key in TAB_KEYS}
    counts["all"] = len(items)
    for it in items:
        counts[it.status.value] = counts.get(it.status.value, 0) + 1

    if status != "all":
        items = [it for it in items if it.status.value == status]

    ql = q.strip().lower()
    if ql:
        def _match(it):
            hay = " ".join([
                it.customer_name or "", it.mzk_ref or "", it.property_address or "",
                it.customer_phone or "", it.submission_id or "", it.services or "",
            ]).lower()
            return ql in hay
        items = [it for it in items if _match(it)]

    rows = [{
        "submission_id": it.submission_id,
        "mzk_ref":       it.mzk_ref or "—",
        "received_at":   (it.received_at or "")[:16].replace("T", " "),
        "customer":      it.customer_name or "—",
        "phone":         it.customer_phone or "",
        "address":       it.property_address or "—",
        "service":       it.services or "—",
        "status":        it.status.value,
        "missing_info":  len(it.missing_info),
        "missing_docs":  len(it.missing_docs),
        "has_errors":    it.has_errors,
    } for it in items]

    return _TEMPLATES.TemplateResponse(request, "dashboard/list.html", {
        **_i18n(request),
        "rows": rows, "counts": counts,
        "tabs": TAB_KEYS, "active": status, "q": q,
    })


# ── Detail page ───────────────────────────────────────────────────────────────

@router.get("/review/{submission_id}", response_class=HTMLResponse)
def review_detail(request: Request, submission_id: str, msg: str = "", err: str = ""):
    if not _is_authed(request):
        return _redirect_login()

    item = Q.load(submission_id)
    if item is None:
        raise HTTPException(status_code=404, detail="הפנייה לא נמצאה")

    bd = item.business_data or {}
    incoming = bd.get("incoming_tenant") or {}
    prop     = bd.get("property") or {}
    dates    = bd.get("dates") or {}

    documents = _list_documents(submission_id)

    return _TEMPLATES.TemplateResponse(request, "dashboard/detail.html", {
        **_i18n(request),
        "item":         item.to_dict(),
        "incoming":     incoming,
        "property":     prop,
        "dates":        dates,
        "missing_info": item.missing_info or [],
        "missing_docs": item.missing_docs or [],
        "validation":   item.validation_issues or [],
        "email":        item.final_email or item.draft_email,
        "documents":    documents,
        "actionable":   item.is_actionable,
        "has_errors":   item.has_errors,
        "msg":          msg,
        "err":          err,
    })


# ── Actions (form POST → update queue → redirect back) ────────────────────────

@router.post("/review/{submission_id}/approve")
def do_approve(request: Request, submission_id: str,
               notes: str = Form(""), override_errors: str = Form("")):
    if not _is_authed(request):
        return _redirect_login()
    item = Q.load(submission_id)
    if item is None:
        raise HTTPException(status_code=404, detail="הפנייה לא נמצאה")
    if not item.is_actionable:
        return _back(submission_id, err="already_handled")
    if item.has_errors and not override_errors:
        return _back(submission_id, err="override_needed")
    Q.update_status(
        submission_id, ReviewStatus.APPROVED,
        notes=notes, reviewed_by="operator",
        final_email=item.final_email or item.draft_email,
    )
    logger.info("Dashboard: %s APPROVED", submission_id)
    return _back(submission_id, msg="approved")


@router.post("/review/{submission_id}/reject")
def do_reject(request: Request, submission_id: str, reason: str = Form(...)):
    if not _is_authed(request):
        return _redirect_login()
    item = Q.load(submission_id)
    if item is None:
        raise HTTPException(status_code=404, detail="הפנייה לא נמצאה")
    if not item.is_actionable:
        return _back(submission_id, err="already_handled")
    if not reason.strip():
        return _back(submission_id, err="need_reason")
    Q.update_status(submission_id, ReviewStatus.REJECTED, notes=reason, reviewed_by="operator")
    logger.info("Dashboard: %s REJECTED", submission_id)
    return _back(submission_id, msg="rejected")


@router.post("/review/{submission_id}/needs_info")
def do_needs_info(request: Request, submission_id: str, notes: str = Form(...)):
    if not _is_authed(request):
        return _redirect_login()
    item = Q.load(submission_id)
    if item is None:
        raise HTTPException(status_code=404, detail="הפנייה לא נמצאה")
    if not notes.strip():
        return _back(submission_id, err="need_notes")
    Q.update_status(submission_id, ReviewStatus.NEEDS_INFO, notes=notes, reviewed_by="operator")
    logger.info("Dashboard: %s NEEDS_INFO", submission_id)
    return _back(submission_id, msg="needs_info")


# ── Document serving (preview / download) ─────────────────────────────────────

@router.get("/documents/{submission_id}/{filename:path}")
def serve_document(request: Request, submission_id: str, filename: str):
    if not _is_authed(request):
        return _redirect_login()
    base = (_settings().documents_dir / submission_id).resolve()
    target = (base / filename).resolve()
    # Path-traversal guard: target must stay inside the submission's folder.
    if not str(target).startswith(str(base)) or not target.is_file():
        raise HTTPException(status_code=404, detail="המסמך לא נמצא")
    return FileResponse(target)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _back(submission_id: str, msg: str = "", err: str = "") -> RedirectResponse:
    from urllib.parse import urlencode
    qs = urlencode({k: v for k, v in (("msg", msg), ("err", err)) if v})
    url = f"/dashboard/review/{submission_id}"
    if qs:
        url += f"?{qs}"
    return RedirectResponse(url, status_code=303)


def _list_documents(submission_id: str) -> list[dict]:
    d = _settings().documents_dir / submission_id
    if not d.is_dir():
        return []
    docs: list[dict] = []
    for p in sorted(d.rglob("*")):
        if not p.is_file() or p.name == "_manifest.json":
            continue
        rel = p.relative_to(d).as_posix()
        ext = p.suffix.lower()
        try:
            size_kb = round(p.stat().st_size / 1024, 1)
        except OSError:
            size_kb = 0
        docs.append({
            "name":     p.name,
            "rel":      rel,
            "url":      f"/dashboard/documents/{submission_id}/{rel}",
            "is_image": ext in _IMAGE_EXTS,
            "size_kb":  size_kb,
        })
    return docs
