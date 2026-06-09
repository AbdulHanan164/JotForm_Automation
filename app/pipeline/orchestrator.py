"""
Pipeline orchestrator.

Receives raw multipart fields from the webhook, routes to the correct
service by form_id, runs the 4-step pipeline, and returns a PipelineResult.

To add a new service:
  1. Create app/services/{name}/ with a class implementing BaseService
  2. Import it here and add its form_id to SERVICES
  3. Done — the webhook route needs no changes.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.pipeline.result import PipelineResult
from app.services.arnona.service import ArnonaService

logger = logging.getLogger("webhook")

# ── Service registry: form_id → service instance ──────────────────────────────
# Add new services here.
_SERVICES: dict[str, Any] = {}

def _register():
    for svc in [ArnonaService()]:
        _SERVICES[svc.form_id] = svc
        logger.debug("Registered service '%s' for form %s", svc.service_name, svc.form_id)

_register()

UNKNOWN_SERVICE_NAME = "unknown_form"


# ── Envelope helpers ──────────────────────────────────────────────────────────

_ENVELOPE_KEYS = {"submissionID", "formID", "formTitle", "username", "ip", "type", "action"}

def _extract_envelope(fields: dict[str, Any]) -> dict[str, str]:
    return {k: str(fields.get(k, "")) for k in _ENVELOPE_KEYS}

def _decode_raw_request(fields: dict[str, Any]) -> dict[str, Any]:
    raw = fields.get("rawRequest", "{}")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("rawRequest JSON decode failed")
            return {}
    if isinstance(raw, dict):
        return raw
    return {}


# ── Public entry point ────────────────────────────────────────────────────────

def run_pipeline(
    raw_fields:   dict[str, Any],
    content_type: str,
    headers:      dict[str, str],
) -> PipelineResult:
    """
    Full pipeline run.  Returns a PipelineResult regardless of outcome.
    Raises only on unexpected exceptions.
    """
    result = PipelineResult()
    result.raw_fields   = raw_fields
    result.content_type = content_type
    result.headers      = {k: str(v) for k, v in headers.items()}

    # ── 1. Envelope ───────────────────────────────────────────────────────────
    envelope            = _extract_envelope(raw_fields)
    result.submission_id = envelope.get("submissionID") or "unknown"
    result.form_id       = envelope.get("formID", "")
    result.form_title    = envelope.get("formTitle", "")
    result.raw_request   = _decode_raw_request(raw_fields)

    # ── 2. Route to service ───────────────────────────────────────────────────
    service = _SERVICES.get(result.form_id)
    if service is None:
        logger.warning("No service registered for form_id=%s — saving raw only", result.form_id)
        result.service_name = UNKNOWN_SERVICE_NAME
        result.summary = {
            "שגיאה": f"אין שירות מוגדר עבור טופס {result.form_id}",
            "form_id": result.form_id,
        }
        result.missing = {"is_complete": False, "missing_info": [], "missing_docs": []}
        return result

    result.service_name = service.service_name
    logger.info("Routing to service '%s' (form %s)", service.service_name, result.form_id)

    # ── 3. Parse fields ───────────────────────────────────────────────────────
    # Merge envelope fields + rawRequest so the service sees everything
    merged = {**result.raw_request, **{k: v for k, v in raw_fields.items()}}
    result.parsed = service.parse_fields(merged)

    # ── 4. Build summary ──────────────────────────────────────────────────────
    result.summary = service.build_summary(result.parsed)

    # ── 5. Detect missing ─────────────────────────────────────────────────────
    result.missing = service.detect_missing(result.parsed, result.summary)

    # ── 6. Draft email ────────────────────────────────────────────────────────
    result.email = service.draft_email(result.summary, result.missing)

    logger.info(
        "Pipeline complete | id=%s | complete=%s | missing_info=%d | missing_docs=%d",
        result.submission_id,
        result.is_complete,
        len(result.missing_info_labels),
        len(result.missing_doc_labels),
    )
    return result
