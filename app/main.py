"""
FastAPI application entry point — v0.3.0

Routes:
  GET  /              — health check
  GET  /health        — health check
  POST /webhook       — JotForm webhook receiver

  GET  /submissions           — list recent business summaries
  GET  /submissions/{id}      — get business summary for a submission
  GET  /submissions/{id}/email — preview the draft email for a submission
  GET  /discover/{id}         — show all raw field IDs (for building field maps)
"""

import json
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from app.config import settings
from app.logger import setup_logger
from app.routes.webhook import router as webhook_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger = setup_logger(log_dir=settings.logs_dir)
    logger.info("=" * 50)
    logger.info("Starting %s v%s", settings.app_name, settings.app_version)
    logger.info("Submissions : %s", settings.submissions_dir.resolve())
    logger.info("Processed   : %s", settings.processed_dir.resolve())
    logger.info("=" * 50)
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "JotForm Webhook — multi-service pipeline: "
        "parse → summarise → detect missing → draft email."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook_router)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/", tags=["health"])
def root():
    return {"status": "ok", "app": settings.app_name, "version": settings.app_version}


@app.get("/health", tags=["health"])
def health():
    return {"status": "healthy"}


# ── Inspection endpoints ──────────────────────────────────────────────────────

@app.get("/submissions", tags=["inspection"])
def list_submissions(limit: int = 20):
    """List the most recent business summaries."""
    files = sorted(
        settings.processed_dir.glob("*_business.json"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )[:limit]

    results = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            summary = data.get("סיכום", {})
            customer = summary.get("דייר_נכנס", {})
            missing_info = data.get("חסר_מידע", [])
            missing_docs = data.get("חסר_מסמכים", [])
            results.append({
                "file":            f.name,
                "submission_id":   data.get("מזהה"),
                "received_at":     data.get("התקבל"),
                "service":         data.get("שירות"),
                "customer":        customer.get("שם"),
                "phone":           customer.get("טלפון"),
                "is_complete":     data.get("הושלם"),
                "missing_info":    [i["label"] for i in missing_info],
                "missing_docs":    [i["label"] for i in missing_docs],
                "email_ready":     data.get("טיוטת_מייל") is not None,
            })
        except Exception as exc:
            results.append({"file": f.name, "error": str(exc)})

    return {"count": len(results), "submissions": results}


@app.get("/submissions/{submission_id}", tags=["inspection"])
def get_submission(submission_id: str):
    """Return the full business summary for a specific submission."""
    matches = list(settings.processed_dir.glob(f"*_{submission_id}_business.json"))
    if not matches:
        raise HTTPException(status_code=404, detail=f"Submission {submission_id} not found.")
    return JSONResponse(content=json.loads(matches[0].read_text(encoding="utf-8")))


@app.get("/submissions/{submission_id}/email", tags=["inspection"])
def get_email_draft(submission_id: str):
    """Return the draft email for a specific submission (plain text, RTL Hebrew)."""
    matches = list(settings.processed_dir.glob(f"*_{submission_id}_business.json"))
    if not matches:
        raise HTTPException(status_code=404, detail=f"Submission {submission_id} not found.")
    data  = json.loads(matches[0].read_text(encoding="utf-8"))
    email = data.get("טיוטת_מייל")
    if not email:
        return PlainTextResponse("אין פרטים חסרים — לא נוצרה טיוטת מייל.")
    subject = email.get("subject", "")
    body    = email.get("body", "")
    return PlainTextResponse(f"Subject: {subject}\n\n{body}", media_type="text/plain; charset=utf-8")


@app.get("/discover/{submission_id}", tags=["debug"])
def discover_fields(submission_id: str):
    """
    Show all raw JotForm field IDs and values for a submission.
    Use this to identify which field ID maps to which label
    when building or updating a service field map.
    """
    matches = list(settings.submissions_dir.glob(f"*_{submission_id}_raw.json"))
    if not matches:
        raise HTTPException(status_code=404, detail=f"Submission {submission_id} not found in raw storage.")

    data = json.loads(matches[0].read_text(encoding="utf-8"))
    raw_request = data.get("_raw_request", {})
    raw_fields  = data.get("_raw_fields", {})

    # Combine and filter out base64 images
    combined = {}
    for field_id, value in {**raw_fields, **raw_request}.items():
        sv = str(value)
        if len(sv) > 1000:
            combined[field_id] = f"[LONG VALUE — {len(sv)} chars, possibly base64]"
        else:
            combined[field_id] = value

    return {
        "submission_id": submission_id,
        "form_id":       data.get("form_id"),
        "form_title":    data.get("form_title"),
        "field_count":   len(combined),
        "fields":        combined,
        "tip": (
            "Copy field IDs from 'fields' above and add them to "
            "app/services/{service}/field_map.py"
        ),
    }


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
