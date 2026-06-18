"""
POST /webhook — JotForm webhook receiver — v0.6.0.

v0.6 CHANGES:
  1. Webhook secret token verification (FIX: was completely open)
  2. Idempotency: duplicate submissions return cached result (FIX: retries caused duplicates)
  3. Google Sheets sync moved to BackgroundTask (FIX: was blocking the response)
  4. Document download immediately after pipeline (FIX: JotForm URLs expire)

JOTFORM SETUP:
  In JotForm: Settings → Integrations → Webhook
  URL: https://yourserver.com/webhook?token=<WEBHOOK_SECRET>
  The ?token= query param is how we verify the request came from JotForm.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from app.auth import verify_webhook_token
from app.config import settings
from app.pipeline.orchestrator import run_pipeline
from app.services.submission_service import save_raw, save_business, save_for_review

router = APIRouter(prefix="/webhook", tags=["webhook"])
logger = logging.getLogger("webhook")


@router.post("", status_code=status.HTTP_200_OK)
async def receive_webhook(
    request:          Request,
    background_tasks: BackgroundTasks,
    token:            str | None = Query(default=None, description="Webhook secret token"),
) -> JSONResponse:
    """
    Receive a JotForm webhook.

    JotForm webhook URL must include ?token=<WEBHOOK_SECRET>.
    Returns 200 immediately. Google Sheets sync runs in background.
    """

    # ── Step 1: Verify webhook token ──────────────────────────────────────────
    verify_webhook_token(token)

    # ── Step 2: Parse body ────────────────────────────────────────────────────
    content_type: str = request.headers.get("content-type", "").lower()
    raw_body: bytes   = await request.body()

    if "multipart/form-data" in content_type:
        form   = await request.form()
        fields: dict[str, Any] = {k: v for k, v in form.items()}
    else:
        import json as _json, urllib.parse as _up
        body_str = raw_body.decode("utf-8", errors="replace")
        try:
            decoded = _up.parse_qs(body_str, keep_blank_values=True)
            fields  = {k: (v[0] if len(v) == 1 else v) for k, v in decoded.items()}
            if not fields:
                fields = _json.loads(body_str)
        except Exception:
            fields = {"_raw_text": body_str}

    logger.info("=" * 60)
    logger.info("WEBHOOK  type=%s  size=%d bytes", content_type, len(raw_body))

    # ── Step 3: Extract submission ID early (for idempotency check) ───────────
    import json as _json_mod
    raw_req = fields.get("rawRequest", "{}")
    if isinstance(raw_req, str):
        try:
            rr = _json_mod.loads(raw_req)
        except Exception:
            rr = {}
    elif isinstance(raw_req, dict):
        rr = raw_req
    else:
        rr = {}

    submission_id = (
        fields.get("submissionID") or
        rr.get("submissionID") or
        "unknown"
    )

    # ── Step 4: Idempotency — check for duplicate ─────────────────────────────
    if submission_id != "unknown":
        duplicate = _check_duplicate(submission_id)
        if duplicate is not None:
            logger.info(
                "IDEMPOTENT replay: submission %s already in queue (status=%s)",
                submission_id, duplicate.get("status"),
            )
            return JSONResponse(
                content={
                    "status":            "received",
                    "idempotent_replay": True,
                    "submission_id":     submission_id,
                    "service":           duplicate.get("service_name", ""),
                    "review_status":     duplicate.get("status", "pending_review"),
                    "message":           "Submission already processed. Returning cached result.",
                },
                headers={"X-Idempotent-Replay": "true"},
            )

    # ── Step 5: Run pipeline ──────────────────────────────────────────────────
    result = run_pipeline(
        raw_fields   = fields,
        content_type = content_type,
        headers      = dict(request.headers),
    )

    # ── Step 6: Document acquisition ──────────────────────────────────────────
    # LEGACY (flag OFF, default): inline download — UNCHANGED production behavior.
    # GROUP B (flag ON): handled by a non-blocking durable job enqueued in Step 8.
    if not settings.enable_document_jobs:
        if result.parsed and result.submission_id != "unknown":
            try:
                from app.documents.downloader import download_submission_documents
                result.parsed, _manifest = download_submission_documents(
                    result.parsed, result.submission_id
                )
            except Exception as exc:
                logger.warning("Document download error (non-fatal): %s", exc)

    # ── Step 7: Persist all three outputs ─────────────────────────────────────
    save_raw(result, settings.submissions_dir)
    save_business(result, settings.processed_dir)
    save_for_review(result)

    # ── Step 8: Document job (Group B — feature-flagged, non-blocking) ────────
    # Enqueued AFTER save so the review item exists for the job to upgrade.
    # Does NOT block the response: the actual fetch+download runs in background.
    if settings.enable_document_jobs and result.submission_id != "unknown":
        try:
            from app.documents.jobs import enqueue
            enqueue(result.submission_id)
            background_tasks.add_task(_run_document_job_bg, result.submission_id)
        except Exception as exc:
            logger.warning("Could not enqueue document job (non-fatal): %s", exc)

    # ── Step 9: Google Sheets sync (background — does NOT block response) ─────
    background_tasks.add_task(_sync_to_sheets_bg, result)

    # ── Step 9: Log and return ────────────────────────────────────────────────
    logger.info("ID           : %s", result.submission_id)
    logger.info("Service      : %s", result.service_name)
    logger.info("Complete     : %s", result.is_complete)
    logger.info("Hidden fields: %d", sum(1 for v in result.visibility.values() if not v))
    if result.missing_info_labels:
        logger.info("Missing info : %s", result.missing_info_labels)
    if result.missing_doc_labels:
        logger.info("Missing docs : %s", result.missing_doc_labels)
    if result.error_count:
        logger.warning("Validation errors  : %d", result.error_count)
    if result.warning_count:
        logger.info("Validation warnings: %d", result.warning_count)
    logger.info("=" * 60)

    return JSONResponse(content={
        "status":              "received",
        "idempotent_replay":   False,
        "submission_id":       result.submission_id,
        "service":             result.service_name,
        "is_complete":         result.is_complete,
        "missing_info":        result.missing_info_labels,
        "missing_docs":        result.missing_doc_labels,
        "validation_errors":   result.error_count,
        "validation_warnings": result.warning_count,
        "hidden_fields":       [k for k, v in result.visibility.items() if not v],
        "email_draft_ready":   result.email is not None,
        "review_status":       "pending_review",
        "next_step":           "Operator review at GET /review",
    })


# ── Idempotency helper ────────────────────────────────────────────────────────

def _check_duplicate(submission_id: str) -> dict | None:
    """
    Check if this submission has already been processed.
    Returns the review item dict if found, None if new.
    """
    try:
        from app.review import queue as Q
        item = Q.load(submission_id)
        if item is not None:
            return {"status": item.status.value, "service_name": item.service_name}
    except Exception as exc:
        logger.warning("Idempotency check failed (non-fatal): %s", exc)
    return None


# ── Background document job (Group B — only runs when flag is ON) ────────────

def _run_document_job_bg(submission_id: str) -> None:
    """Fetch finalized file URLs from the JotForm API and download them.

    Runs AFTER the webhook response is sent. The file source is the JotForm API
    adapter; if no API key is configured the job is recorded (retryable) with no
    downloads, so it can be retried later once the key is set.
    """
    try:
        from app.documents.jobs import run_job
        from app.integrations.jotform.client import get_client
        client = get_client()
        if client is None:
            run_job(submission_id, lambda _sid: [])
            return
        run_job(submission_id, client.get_submission_files)
    except Exception as exc:
        logger.error("Document job background error for %s: %s", submission_id, exc)


# ── Background Sheets sync ────────────────────────────────────────────────────

def _sync_to_sheets_bg(result) -> None:
    """
    Background task: write submission to Google Sheets.
    Runs AFTER the webhook response is sent.
    Any failure here is logged but does not affect the submission.
    """
    try:
        from app.config_service.loader import load_yaml_services
        from app.integrations.google_sheets.client import write_submission_to_sheets

        yaml_services = load_yaml_services()
        yaml_cfg = yaml_services.get(result.form_id)
        if yaml_cfg is None:
            return

        sheets_cfg    = yaml_cfg._config.get("google_sheets", {})
        sheet_id      = sheets_cfg.get("sheet_id", "")
        tab_name      = sheets_cfg.get("tab_name", "הגשות")
        column_config = sheets_cfg.get("columns", [])

        if not sheet_id:
            return

        success = write_submission_to_sheets(result, sheet_id, tab_name, column_config)
        if success:
            logger.info(
                "Sheets: wrote %s to %s/%s", result.submission_id, sheet_id, tab_name
            )
        else:
            logger.warning(
                "Sheets: write failed for %s (check credentials)", result.submission_id
            )
    except Exception as exc:
        # Never raise from background task — it would silently swallow unhandled
        # exceptions. Log explicitly.
        logger.error("Sheets background sync error: %s", exc)
