"""
POST /webhook  — JotForm webhook receiver.

New pipeline (v0.3.0):
  multipart form
    → orchestrator.run_pipeline()
        → service.parse_fields()
        → service.build_summary()
        → service.detect_missing()
        → service.draft_email()
    → save_raw() + save_business()
    → return clean JSON response
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.config import settings
from app.pipeline.orchestrator import run_pipeline
from app.services.submission_service import save_raw, save_business

router = APIRouter(prefix="/webhook", tags=["webhook"])
logger = logging.getLogger("webhook")


@router.post("", status_code=status.HTTP_200_OK)
async def receive_webhook(request: Request) -> JSONResponse:
    """Receive a JotForm submission, run the full pipeline, persist results."""
    try:
        content_type: str = request.headers.get("content-type", "").lower()
        raw_body: bytes   = await request.body()

        # ── 1. Parse multipart (JotForm sends multipart/form-data) ────────────
        if "multipart/form-data" in content_type:
            form = await request.form()
            fields: dict[str, Any] = {k: v for k, v in form.items()}
        else:
            # Fallback for test payloads (url-encoded or JSON)
            import json as _json
            import urllib.parse as _up
            body_str = raw_body.decode("utf-8", errors="replace")
            try:
                decoded = _up.parse_qs(body_str, keep_blank_values=True)
                fields = {k: (v[0] if len(v) == 1 else v) for k, v in decoded.items()}
                if not fields:
                    fields = _json.loads(body_str)
            except Exception:
                fields = {"_raw_text": body_str}

        logger.info("=" * 60)
        logger.info(
            "WEBHOOK  content-type=%s  size=%d bytes",
            content_type, len(raw_body),
        )

        # ── 2. Run full pipeline ──────────────────────────────────────────────
        result = run_pipeline(
            raw_fields   = fields,
            content_type = content_type,
            headers      = dict(request.headers),
        )

        # ── 3. Persist ────────────────────────────────────────────────────────
        raw_path      = save_raw(result, settings.submissions_dir)
        business_path = save_business(result, settings.processed_dir)

        # ── 4. Log summary ────────────────────────────────────────────────────
        logger.info("Submission   : %s", result.submission_id)
        logger.info("Service      : %s", result.service_name)
        logger.info("Complete     : %s", result.is_complete)
        if result.missing_info_labels:
            logger.info("Missing info : %s", result.missing_info_labels)
        if result.missing_doc_labels:
            logger.info("Missing docs : %s", result.missing_doc_labels)
        logger.info("Raw          : %s", raw_path)
        logger.info("Business     : %s", business_path)
        logger.info("=" * 60)

        # ── 5. Response ───────────────────────────────────────────────────────
        return JSONResponse(content={
            "status":        "success",
            "submission_id": result.submission_id,
            "service":       result.service_name,
            "is_complete":   result.is_complete,
            "missing_info":  result.missing_info_labels,
            "missing_docs":  result.missing_doc_labels,
            "email_ready":   result.email is not None,
            "business_file": str(business_path),
        })

    except Exception as exc:
        logger.exception("Webhook processing failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Processing error: {exc}",
        ) from exc
