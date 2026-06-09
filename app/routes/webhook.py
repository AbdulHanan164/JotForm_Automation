"""
POST /webhook — JotForm webhook receiver — v0.4.0

10-stage pipeline:
  parse → conditional logic → doc extraction → summary
  → missing detection → cross-doc validation → draft email
  → review queue (human approval before any email is sent)
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.config import settings
from app.pipeline.orchestrator import run_pipeline
from app.services.submission_service import save_raw, save_business, save_for_review

router = APIRouter(prefix="/webhook", tags=["webhook"])
logger = logging.getLogger("webhook")


@router.post("", status_code=status.HTTP_200_OK)
async def receive_webhook(request: Request) -> JSONResponse:
    try:
        content_type: str = request.headers.get("content-type", "").lower()
        raw_body: bytes   = await request.body()

        # ── Parse multipart (JotForm default) ────────────────────────────────
        if "multipart/form-data" in content_type:
            form = await request.form()
            fields: dict[str, Any] = {k: v for k, v in form.items()}
        else:
            import json as _json, urllib.parse as _up
            body_str = raw_body.decode("utf-8", errors="replace")
            try:
                decoded = _up.parse_qs(body_str, keep_blank_values=True)
                fields = {k: (v[0] if len(v) == 1 else v) for k, v in decoded.items()}
                if not fields:
                    fields = _json.loads(body_str)
            except Exception:
                fields = {"_raw_text": body_str}

        logger.info("=" * 60)
        logger.info("WEBHOOK  type=%s  size=%d bytes", content_type, len(raw_body))

        # ── Run 10-stage pipeline ─────────────────────────────────────────────
        result = run_pipeline(
            raw_fields   = fields,
            content_type = content_type,
            headers      = dict(request.headers),
        )

        # ── Persist all three outputs ─────────────────────────────────────────
        raw_path      = save_raw(result, settings.submissions_dir)
        business_path = save_business(result, settings.processed_dir)
        review_path   = save_for_review(result)

        # ── Log summary ───────────────────────────────────────────────────────
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
        logger.info("Review queue : %s", review_path)
        logger.info("=" * 60)

        return JSONResponse(content={
            "status":            "received",
            "submission_id":     result.submission_id,
            "service":           result.service_name,
            "is_complete":       result.is_complete,
            "missing_info":      result.missing_info_labels,
            "missing_docs":      result.missing_doc_labels,
            "validation_errors": result.error_count,
            "validation_warnings": result.warning_count,
            "hidden_fields":     [k for k, v in result.visibility.items() if not v],
            "email_draft_ready": result.email is not None,
            "review_status":     "pending_review",
            "next_step":         "Operator review required at GET /review",
        })

    except Exception as exc:
        logger.exception("Webhook failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
