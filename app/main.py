"""
FastAPI — v0.4.0

Routes:
  Webhook:    POST /webhook
  Health:     GET  /  |  GET /health
  Review:     GET  /review  |  GET /review/{id}  |  POST /review/{id}/approve  etc.
  Inspection: GET  /submissions  |  GET /submissions/{id}  |  GET /submissions/{id}/email
  Debug:      GET  /discover/{id}
"""
import json
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from app.config import settings
from app.logger import setup_logger
from app.routes.webhook import router as webhook_router
from app.routes.review  import router as review_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger = setup_logger(log_dir=settings.logs_dir)
    logger.info("=" * 55)
    logger.info("Starting %s v%s", settings.app_name, settings.app_version)
    logger.info("Submissions  : %s", settings.submissions_dir.resolve())
    logger.info("Processed    : %s", settings.processed_dir.resolve())
    logger.info("Review queue : %s", settings.review_dir.resolve())
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
        "Hebrew email draft → human review."
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


# ── Health ────────────────────────────────────────────────────────────────────

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


# ── Submission inspection ─────────────────────────────────────────────────────

@app.get("/submissions", tags=["inspection"])
def list_submissions(limit: int = 20):
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
def get_submission(submission_id: str):
    matches = list(settings.processed_dir.glob(f"*_{submission_id}_business.json"))
    if not matches:
        raise HTTPException(status_code=404, detail=f"Submission {submission_id} not found.")
    return JSONResponse(content=json.loads(matches[0].read_text(encoding="utf-8")))


@app.get("/submissions/{submission_id}/email", tags=["inspection"])
def get_email_draft(submission_id: str):
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


# ── Field discovery ───────────────────────────────────────────────────────────

@app.get("/discover/{submission_id}", tags=["debug"])
def discover_fields(submission_id: str):
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
        "tip": "Match field IDs to labels, then update app/services/{service}/field_map.py",
    }


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
