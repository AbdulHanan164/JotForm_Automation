"""
Pipeline orchestrator — v0.5.0

8-stage pipeline:
  1. Envelope extraction      — submission ID, form ID, form title
  2. Service routing          — match form_id to registered service
  3. Conditional logic        — evaluate which fields were visible/hidden
  4. Field parsing            — map field IDs → semantic labels (visibility-aware)
  5. Document extraction      — extract structured data from uploaded files
  6. Business summary         — build clean Hebrew operator summary
  7. Missing detection        — what's required but absent (respects hidden fields)
  8. Cross-doc validation     — consistency checks across form + documents
  9. Draft email              — RTL Hebrew email (queued for human approval)
 10. Review queue             — save to pending_review (NO email sent yet)

To add a new service (v0.5+ approach):
  OPTION A — YAML-driven (no code required):
    1. Create config/services/new_service.yaml with form_id filled in
    2. Restart — automatically registered via config_service.loader

  OPTION B — Python-coded (for complex validation logic):
    1. Create app/services/{name}/ implementing BaseService
    2. Add to _PYTHON_SERVICES list below
    3. Python services take priority over YAML services for the same form_id
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.pipeline.result import PipelineResult
from app.services.arnona.service import ArnonaService

logger = logging.getLogger("webhook")

# ── Service registry ──────────────────────────────────────────────────────────

_SERVICES: dict[str, Any] = {}


def _register():
    """
    Build service registry:
    1. Load YAML-driven services from config/services/*.yaml
    2. Register hardcoded Python services (these override YAML for same form_id)
    """
    try:
        from app.config_service.loader import register_yaml_services
        yaml_services = register_yaml_services({})
        _SERVICES.update(yaml_services)
        if yaml_services:
            logger.info("Loaded %d YAML-driven service(s)", len(yaml_services))
    except Exception as exc:
        logger.warning("YAML service loader error (non-fatal): %s", exc)

    # Python-coded services — override YAML for same form_id
    _PYTHON_SERVICES = [
        ArnonaService(),
        # ElectricityService(),  ← uncomment when field map is ready
        # WaterService(),        ← uncomment when field map is ready
    ]
    for svc in _PYTHON_SERVICES:
        _SERVICES[svc.form_id] = svc
        logger.debug("Registered Python service '%s' for form %s", svc.service_name, svc.form_id)

    logger.info("Service registry: %d service(s) registered", len(_SERVICES))


_register()

# ── Envelope helpers ──────────────────────────────────────────────────────────

_ENVELOPE_KEYS = {
    "submissionID", "formID", "formTitle", "username", "ip", "type", "action"
}


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


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run_pipeline(
    raw_fields:   dict[str, Any],
    content_type: str,
    headers:      dict[str, str],
) -> PipelineResult:
    """
    Run the full 10-stage pipeline.
    Returns a PipelineResult regardless of outcome — never raises.
    Errors are captured inside the result.
    """
    result = PipelineResult()
    result.raw_fields    = raw_fields
    result.content_type  = content_type
    result.headers       = {k: str(v) for k, v in headers.items()}

    # ── Stage 1: Envelope ─────────────────────────────────────────────────────
    envelope             = _extract_envelope(raw_fields)
    result.submission_id = envelope.get("submissionID") or "unknown"
    result.form_id       = envelope.get("formID", "")
    result.form_title    = envelope.get("formTitle", "")
    result.raw_request   = _decode_raw_request(raw_fields)

    # ── Stage 2: Route to service ─────────────────────────────────────────────
    service = _SERVICES.get(result.form_id)
    if service is None:
        logger.warning(
            "No service for form_id=%s — raw-only save", result.form_id
        )
        result.service_name = "unknown_form"
        result.summary = {"שגיאה": f"טופס {result.form_id} לא מוגדר"}
        result.missing = {"is_complete": False, "missing_info": [], "missing_docs": []}
        result.review_status = "pending_review"
        return result

    result.service_name = service.service_name
    logger.info("→ Service: %s  (form %s)", service.service_name, result.form_id)

    # Merge envelope + rawRequest for service
    merged = {**result.raw_request, **{k: v for k, v in raw_fields.items()}}

    # ── Stage 3: Conditional logic ────────────────────────────────────────────
    pre_parsed = None
    _evaluator_used = False
    try:
        from app.pipeline.schema_loader import get_schema
        from app.pipeline.evaluator import (
            JotFormConditionEvaluator,
            build_label_visibility,
            build_explanations,
        )
        from app.services.arnona.field_map import FIELD_MAP

        schema = get_schema(result.form_id)
        if schema is None:
            raise FileNotFoundError(f"No cached schema for form {result.form_id}")

        evaluator    = JotFormConditionEvaluator(schema)
        eval_out     = evaluator.evaluate(merged)
        flat_answers = eval_out["flat_answers"]

        label_vis, active_qids, audit_records = build_label_visibility(
            eval_out["visibility_map"], FIELD_MAP, flat_answers
        )
        explanations = build_explanations(
            evaluator.conditions, flat_answers, eval_out["visibility_map"], evaluator
        )

        result.visibility = label_vis
        result.evaluator_result = {
            "engine":           "JotFormConditionEvaluator",
            "form_id":          result.form_id,
            "submission_id":    result.submission_id,
            "visibility_map":   eval_out["visibility_map"],
            "required_map":     eval_out["required_map"],
            "visible_fields":   eval_out["visible_fields"],
            "hidden_fields":    eval_out["hidden_fields"],
            "required_fields":  eval_out["required_fields"],
            "required_documents": eval_out["required_documents"],
            "label_visibility": label_vis,
            "active_qids":      active_qids,
            "explanations":     explanations,
            "label_visibility_audit": audit_records,
        }
        _evaluator_used = True
        logger.info(
            "JotFormConditionEvaluator: %d hidden QIDs, %d hidden labels",
            len(eval_out["hidden_fields"]),
            sum(1 for v in label_vis.values() if not v),
        )

    except Exception as exc:
        logger.warning(
            "JotFormConditionEvaluator failed — falling back to legacy engine: %s", exc
        )
        result.evaluator_result = {"engine": "legacy_fallback", "error": str(exc)}

    # ── Legacy fallback ───────────────────────────────────────────────
    if not _evaluator_used:
        logic_engine = service.get_conditional_logic_engine()
        if logic_engine:
            # We need a pre-parse to evaluate conditions (basic fields only)
            pre_parsed = service.parse_fields(merged)
            result.visibility = logic_engine.evaluate(pre_parsed)
            logger.info(
                "Legacy conditional logic fallback: %d fields hidden",
                sum(1 for v in result.visibility.values() if not v),
            )
        else:
            pre_parsed = None
            result.visibility = {}

    # ── Stage 4: Parse fields ─────────────────────────────────────────────────
    # Reuse pre_parsed if we already did it, otherwise parse now
    result.parsed = pre_parsed if pre_parsed is not None else service.parse_fields(merged)

    # ── Stage 4.5: Extract business data ──────────────────────────────────────
    # parse_fields() attaches _business (BusinessSubmission.to_dict()) to parsed.
    # Promote it to result.business_data so it's accessible without going through parsed.
    result.business_data = result.parsed.get("_business", {})

    # ── Stage 4.8: Local Missing Documents Reconciliation ─────────────────────
    if result.submission_id != "unknown" and result.form_id == "250201745267957":
        try:
            from app.pipeline.reconciliation_merge import reconcile_and_merge_for_original
            reconcile_and_merge_for_original(result.submission_id, result.parsed)
            result.business_data = result.parsed.get("_business", {})
        except Exception as exc:
            logger.warning("Missing documents reconciliation merge error: %s", exc)

    # ── Stage 5: Document extraction ──────────────────────────────────────────
    try:
        from app.documents.extractor import extract_all
        docs_section = result.parsed.get("documents", {})
        result.doc_extractions = extract_all(docs_section, result.parsed)
        logger.info(
            "Documents extracted: %d", len(result.doc_extractions)
        )
    except Exception as exc:
        logger.warning("Document extraction error: %s", exc)
        result.doc_extractions = {}

    # ── Stage 6: Unified view ─────────────────────────────────────────────────
    result.unified_view = {
        "form": result.parsed,
        "docs": result.doc_extractions,
    }

    # ── Stage 7: Business summary ─────────────────────────────────────────────
    result.summary = service.build_summary(result.parsed)

    # ── Stage 8: Missing detection (visibility-aware) ─────────────────────────
    result.missing = service.detect_missing(
        result.parsed, result.summary, result.visibility
    )

    # ── Stage 9: Cross-document validation ────────────────────────────────────
    try:
        result.validation_issues = service.validate(
            result.parsed, result.doc_extractions
        )
        logger.info(
            "Validation: %d errors, %d warnings, %d info",
            result.error_count, result.warning_count,
            len(result.validation_issues) - result.error_count - result.warning_count,
        )
    except Exception as exc:
        logger.warning("Validation error: %s", exc)
        result.validation_issues = []

    # ── Stage 10: Draft email ─────────────────────────────────────────────────
    result.email = service.draft_email(result.summary, result.missing)

    # ── Final state ───────────────────────────────────────────────────────────
    result.review_status = "pending_review"

    logger.info(
        "Pipeline done | id=%s | complete=%s | "
        "missing_info=%d | missing_docs=%d | "
        "errors=%d | warnings=%d | email=%s",
        result.submission_id,
        result.is_complete,
        len(result.missing_info_labels),
        len(result.missing_doc_labels),
        result.error_count,
        result.warning_count,
        "yes" if result.email else "no",
    )
    return result
