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

# Hebrew status metadata (label + badge color class) — drives badges everywhere.
STATUS_META: dict[str, dict[str, str]] = {
    "pending_review": {"label": "ממתין לבדיקה", "cls": "badge-pending"},
    "needs_info":     {"label": "נדרש מידע",     "cls": "badge-info"},
    "approved":       {"label": "אושר",          "cls": "badge-approved"},
    "rejected":       {"label": "נדחה",          "cls": "badge-rejected"},
    "sent":           {"label": "נשלח",          "cls": "badge-sent"},
}

# Tabs shown on the list page, in order.
TABS = [
    ("all",            "הכל"),
    ("pending_review", "ממתין לבדיקה"),
    ("needs_info",     "נדרש מידע"),
    ("approved",       "אושר"),
    ("rejected",       "נדחה"),
    ("sent",           "נשלח"),
]

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


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
    return _TEMPLATES.TemplateResponse(request, "dashboard/login.html", {"error": error})


@router.post("/login")
def login_submit(request: Request, api_key: str = Form(...)):
    expected = _expected_key()
    if expected and not secrets.compare_digest(api_key.strip(), expected):
        return _TEMPLATES.TemplateResponse(
            request, "dashboard/login.html",
            {"error": "מפתח שגוי. נסה שוב."},
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


# ── List page ───────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
def dashboard_home(request: Request, status: str = "all", q: str = ""):
    if not _is_authed(request):
        return _redirect_login()

    items = Q.load_all(status=None, limit=200)

    counts = {key: 0 for key, _ in TABS}
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
        "rows": rows, "counts": counts,
        "tabs": TABS, "active": status, "q": q, "status_meta": STATUS_META,
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
        "item":         item.to_dict(),
        "incoming":     incoming,
        "property":     prop,
        "dates":        dates,
        "missing_info": item.missing_info or [],
        "missing_docs": item.missing_docs or [],
        "validation":   item.validation_issues or [],
        "email":        item.final_email or item.draft_email,
        "documents":    documents,
        "status_meta":  STATUS_META,
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
        return _back(submission_id, err=f"הפנייה כבר טופלה ({item.status.value})")
    if item.has_errors and not override_errors:
        return _back(submission_id, err="הפנייה מכילה שגיאות. סמן 'אשר למרות שגיאות' עם הסבר.")
    Q.update_status(
        submission_id, ReviewStatus.APPROVED,
        notes=notes, reviewed_by="operator",
        final_email=item.final_email or item.draft_email,
    )
    logger.info("Dashboard: %s APPROVED", submission_id)
    return _back(submission_id, msg="הפנייה אושרה. שלח את המייל ללקוח באופן ידני.")


@router.post("/review/{submission_id}/reject")
def do_reject(request: Request, submission_id: str, reason: str = Form(...)):
    if not _is_authed(request):
        return _redirect_login()
    item = Q.load(submission_id)
    if item is None:
        raise HTTPException(status_code=404, detail="הפנייה לא נמצאה")
    if not item.is_actionable:
        return _back(submission_id, err=f"הפנייה כבר טופלה ({item.status.value})")
    if not reason.strip():
        return _back(submission_id, err="חובה לציין סיבת דחייה.")
    Q.update_status(submission_id, ReviewStatus.REJECTED, notes=reason, reviewed_by="operator")
    logger.info("Dashboard: %s REJECTED", submission_id)
    return _back(submission_id, msg="הפנייה נדחתה.")


@router.post("/review/{submission_id}/needs_info")
def do_needs_info(request: Request, submission_id: str, notes: str = Form(...)):
    if not _is_authed(request):
        return _redirect_login()
    item = Q.load(submission_id)
    if item is None:
        raise HTTPException(status_code=404, detail="הפנייה לא נמצאה")
    if not notes.strip():
        return _back(submission_id, err="חובה לציין הערה.")
    Q.update_status(submission_id, ReviewStatus.NEEDS_INFO, notes=notes, reviewed_by="operator")
    logger.info("Dashboard: %s NEEDS_INFO", submission_id)
    return _back(submission_id, msg="הפנייה סומנה כ'נדרש מידע'.")


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
