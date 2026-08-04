"""
FastAPI — v0.6.0

v0.6 CHANGES:
  - All protected routes require X-API-Key authentication.
  - /submissions, /submissions/{id}*, /discover/{id} now require auth.
  - Startup: logs auth config status and documents_dir.
  - Version bumped to 0.6.0.

Routes:
  Webhook:    POST /webhook?token=<WEBHOOK_SECRET>
  Health:     GET  /  |  GET /health             (public — no auth)
  Review:     GET  /review  |  GET /review/{id}  |  POST /review/{id}/approve  etc.
  Inspection: GET  /submissions  |  GET /submissions/{id}  |  GET /submissions/{id}/email
  Debug:      GET  /discover/{id}
  Admin:      POST /admin/sync/{form_id}  |  GET /admin/forms  |  GET /admin/services
              GET  /admin/fieldmap/arnona/status
"""
import json
from contextlib import asynccontextmanager
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from app.auth import require_operator, warn_if_insecure
from app.config import settings
from app.logger import setup_logger
from app.routes.webhook import router as webhook_router
from app.routes.review  import router as review_router
from app.routes.admin   import router as admin_router
from app.routes.dashboard import router as dashboard_router

# Type alias for the auth dependency (used in routes defined in main.py)
_Auth = Annotated[str, Depends(require_operator)]


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger = setup_logger(log_dir=settings.logs_dir)
    logger.info("=" * 55)
    logger.info("Starting %s v%s", settings.app_name, settings.app_version)
    logger.info("Submissions  : %s", settings.submissions_dir.resolve())
    logger.info("Processed    : %s", settings.processed_dir.resolve())
    logger.info("Review queue : %s", settings.review_dir.resolve())
    logger.info("Documents    : %s", settings.documents_dir.resolve())

    # Warn if security keys are not configured
    warn_if_insecure()

    # Warn about unverified arnona field IDs
    try:
        from app.services.arnona.field_map import check_field_map_status
        fm = check_field_map_status()
        # Field map vs live JotForm schema — a drift is reported, never silent.
        try:
            from app.core.fieldmap_validation import validate_arnona, log_summary
            log_summary(validate_arnona())
        except Exception as _exc:
            logger.warning("Field-map validation skipped: %s", _exc)
        if fm["status"] != "ok":
            logger.warning(
                "Field map: %d/%d arnona field IDs are unverified placeholders. "
                "Run GET /admin/fieldmap/arnona/status for details.",
                fm["unverified"], fm["total"],
            )
        else:
            logger.info("Field map: all %d arnona field IDs verified ✓", fm["total"])
    except Exception as exc:
        logger.warning("Could not check field map status: %s", exc)

    # Background JotForm sync (non-blocking)
    if settings.jotform_api_key:
        try:
            from app.integrations.jotform.client import JotFormClient
            from app.integrations.jotform.sync import FormSync
            from app.routes.admin import _KNOWN_FORM_IDS
            client  = JotFormClient(settings.jotform_api_key)
            sync    = FormSync(client)
            results = sync.sync_all(_KNOWN_FORM_IDS, force=False)
            ok = sum(1 for r in results if r.success)
            logger.info("JotForm sync: %d/%d forms up to date", ok, len(_KNOWN_FORM_IDS))
        except Exception as exc:
            logger.warning("JotForm startup sync failed (non-fatal): %s", exc)
    else:
        logger.info("JotForm sync: JOTFORM_API_KEY not set — skipping")

    # Reconcile incomplete document jobs (Group B — feature-flagged, off by default)
    if settings.enable_document_jobs:
        try:
            from app.documents.jobs import reconcile
            from app.integrations.jotform.client import get_client
            client = get_client()
            source = client.get_submission_files if client else (lambda _sid: [])
            summary = reconcile(source)
            if summary["rerun"] or summary["exhausted"]:
                logger.info("Document jobs reconciled: %s", summary)
            else:
                logger.info("Document jobs: none pending")
        except Exception as exc:
            logger.warning("Document job reconcile failed (non-fatal): %s", exc)
    else:
        logger.info("Document jobs: disabled (enable_document_jobs=false)")

    logger.info("=" * 55)
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title       = settings.app_name,
    version     = settings.app_version,
    description = (
        "JotForm Webhook — multi-service pipeline: "
        "parse → conditional logic → doc extraction → "
        "summary → missing detection → cross-doc validation → "
        "Hebrew email draft → human review. "
        "Email is NEVER sent automatically — always requires human approval."
    ),
    lifespan = lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins  = ["*"],
    allow_methods  = ["*"],
    allow_headers  = ["*"],
)

app.include_router(webhook_router)
app.include_router(review_router)
app.include_router(admin_router)
app.include_router(dashboard_router)


# ── Health (public — intentionally no auth) ───────────────────────────────────

@app.get("/", tags=["health"])
def root():
    return {
        "status":  "ok",
        "app":     settings.app_name,
        "version": settings.app_version,
        "review_queue": str(settings.review_dir.resolve()),
    }


@app.get("/health", tags=["health"])
def health():
    return {"status": "healthy"}


# ── Submission inspection (requires auth) ─────────────────────────────────────

@app.get("/submissions", tags=["inspection"])
def list_submissions(
    limit: int = 20,
    _op:   _Auth = None,
):
    """List recent business summaries from data/processed/."""
    files = sorted(
        settings.processed_dir.glob("*_business.json"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )[:limit]

    results = []
    for f in files:
        try:
            data     = json.loads(f.read_text(encoding="utf-8"))
            summary  = data.get("סיכום", {})
            customer = summary.get("דייר_נכנס", {})
            issues   = data.get("בעיות_עקביות", [])
            results.append({
                "file":           f.name,
                "submission_id":  data.get("מזהה"),
                "received_at":    data.get("התקבל"),
                "service":        data.get("שירות"),
                "review_status":  data.get("סטטוס_בדיקה"),
                "customer":       customer.get("שם"),
                "phone":          customer.get("טלפון"),
                "is_complete":    data.get("הושלם"),
                "missing_info":   [i["label"] for i in data.get("חסר_מידע", [])],
                "missing_docs":   [i["label"] for i in data.get("חסר_מסמכים", [])],
                "errors":         sum(1 for i in issues if i.get("severity") == "error"),
                "warnings":       sum(1 for i in issues if i.get("severity") == "warning"),
                "email_ready":    data.get("טיוטת_מייל") is not None,
            })
        except Exception as exc:
            results.append({"file": f.name, "error": str(exc)})

    return {"count": len(results), "submissions": results}


@app.get("/submissions/{submission_id}", tags=["inspection"])
def get_submission(submission_id: str, _op: _Auth = None):
    matches = list(settings.processed_dir.glob(f"*_{submission_id}_business.json"))
    if not matches:
        raise HTTPException(status_code=404, detail=f"Submission {submission_id} not found.")
    return JSONResponse(content=json.loads(matches[0].read_text(encoding="utf-8")))


@app.get("/submissions/{submission_id}/email", tags=["inspection"])
def get_email_draft(submission_id: str, _op: _Auth = None):
    matches = list(settings.processed_dir.glob(f"*_{submission_id}_business.json"))
    if not matches:
        raise HTTPException(status_code=404, detail=f"Submission {submission_id} not found.")
    data  = json.loads(matches[0].read_text(encoding="utf-8"))
    email = data.get("טיוטת_מייל")
    if not email:
        return PlainTextResponse("אין פרטים חסרים.", media_type="text/plain; charset=utf-8")
    return PlainTextResponse(
        f"Subject: {email.get('subject', '')}\n\n{email.get('body', '')}",
        media_type="text/plain; charset=utf-8",
    )


# ── Field discovery (requires auth) ──────────────────────────────────────────

@app.get("/discover/{submission_id}", tags=["debug"])
def discover_fields(submission_id: str, _op: _Auth = None):
    """
    Show all raw JotForm field IDs for a submission.
    Use this to build / verify service field maps.
    """
    matches = list(settings.submissions_dir.glob(f"*_{submission_id}_raw.json"))
    if not matches:
        raise HTTPException(status_code=404, detail=f"Submission {submission_id} not found.")

    data        = json.loads(matches[0].read_text(encoding="utf-8"))
    raw_request = data.get("_raw_request", {})
    raw_fields  = data.get("_raw_fields", {})

    combined = {}
    for field_id, value in {**raw_fields, **raw_request}.items():
        sv = str(value)
        combined[field_id] = (
            f"[{len(sv)} chars — possibly base64 image]"
            if len(sv) > 500 else value
        )

    return {
        "submission_id": submission_id,
        "form_id":       data.get("form_id"),
        "form_title":    data.get("form_title"),
        "field_count":   len(combined),
        "fields":        combined,
        "tip": (
            "Match field IDs to labels, then update "
            "config/field_maps/arnona.yaml and set verified: true"
        ),
    }


# ── Document jobs (requires auth) — Group B operator controls ─────────────────

@app.get("/admin/documents/{submission_id}", tags=["admin"])
def get_document_job(submission_id: str, _op: _Auth = None):
    """Return the document-acquisition job record for a submission."""
    from app.documents.jobs import load_job
    job = load_job(submission_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No document job for {submission_id}")
    return JSONResponse(content=job.to_dict())


@app.post("/admin/documents/retry/{submission_id}", tags=["admin"])
def retry_document_job(submission_id: str, _op: _Auth = None):
    """Manually re-run document acquisition for a submission.

    Works whether or not auto-jobs are enabled — uses the JotForm API adapter
    when a key is configured, otherwise records a retryable no-op.
    """
    from app.documents.jobs import retry
    from app.integrations.jotform.client import get_client
    client = get_client()
    source = client.get_submission_files if client else (lambda _sid: [])
    job = retry(submission_id, source)
    return JSONResponse(content=job.to_dict())


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
