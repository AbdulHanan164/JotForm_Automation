"""
Arnona transfer service — implements BaseService for form 251955479892982.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.base.service import BaseService
from app.services.arnona import field_map as fm
from app.services.arnona import summary as sm
from app.services.arnona import rules as rl
from app.services.arnona.email_templates import draft_missing_info_email
from app.services.arnona.conditional_logic import arnona_logic_engine
from app.services.arnona.validators import ARNONA_VALIDATION_RULES
from app.mappers.business_validators import BUSINESS_VALIDATION_RULES
from app.pipeline.validator import ValidationEngine, ValidationIssue

logger = logging.getLogger("webhook")

FORM_ID = "251955479892982"

_validation_engine          = ValidationEngine(ARNONA_VALIDATION_RULES)
_business_validation_engine = ValidationEngine(BUSINESS_VALIDATION_RULES)


class ArnonaService(BaseService):

    @property
    def form_id(self) -> str:
        return FORM_ID

    @property
    def service_name(self) -> str:
        return "arnona_transfer"

    def get_conditional_logic_engine(self):
        return arnona_logic_engine

    def get_validation_engine(self):
        return _validation_engine

    def get_document_types(self) -> list[str]:
        return ["חוזה_שכירות", "תעודת_זהות", "חשבון_ארנונה", "חתימה"]

    # ── Step 1: parse fields ──────────────────────────────────────────────────

    def parse_fields(self, raw_fields: dict[str, Any]) -> dict[str, Any]:
        parsed: dict[str, dict] = {
            fm.S_BASIC:    {},
            fm.S_CUSTOMER: {},
            fm.S_PARTNER:  {},
            fm.S_OUTGOING: {},
            fm.S_LANDLORD: {},
            fm.S_PROPERTY: {},
            fm.S_ARNONA:   {},
            fm.S_WATER:    {},
            fm.S_DOCS:     {},
            fm.S_PAYMENT:  {},
            fm.S_SYSTEM:   {},
            fm.S_FHS:      {},
            "_unmapped":   {},
        }

        for field_id, value in raw_fields.items():
            mapping = fm.FIELD_MAP.get(field_id)
            if mapping is None:
                if isinstance(value, str) and len(value) < 500:
                    parsed["_unmapped"][field_id] = value
                continue

            section = mapping["section"]
            label   = mapping["label"]
            ftype   = mapping["type"]
            cleaned = self._coerce(value, ftype)

            if section in parsed:
                parsed[section][label] = cleaned

        # Apply auto-fills from conditional logic
        autofills = arnona_logic_engine.get_autofills(parsed)
        for target_label, source_label in autofills.items():
            # Find source value across all sections
            for section_data in parsed.values():
                if isinstance(section_data, dict) and source_label in section_data:
                    parsed["arnona"][target_label] = section_data[source_label]
                    break

        # Build BusinessSubmission and attach as JSON-safe dict.
        # Downstream stages (build_summary, detect_missing) use this.
        try:
            from app.mappers.business_mapper import build_from_parsed
            parsed["_business"] = build_from_parsed(parsed).to_dict()
        except Exception as exc:
            logger.warning("BusinessMapper failed (non-fatal): %s", exc)

        return parsed

    # ── Step 2: build summary ─────────────────────────────────────────────────

    def build_summary(self, parsed: dict[str, Any]) -> dict[str, Any]:
        bd = parsed.get("_business")
        if bd:
            try:
                from app.mappers.models import BusinessSubmission
                return BusinessSubmission.from_dict(bd).to_summary_dict()
            except Exception as exc:
                logger.warning("BusinessSubmission.to_summary_dict() failed: %s", exc)
        return sm.build(parsed)

    # ── Step 3: detect missing (BusinessSubmission-first, raw fallback) ──────

    def detect_missing(
        self,
        parsed:     dict[str, Any],
        summary:    dict[str, Any],
        visibility: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        if visibility is None:
            visibility = arnona_logic_engine.evaluate(parsed)

        bd = parsed.get("_business")
        if bd:
            try:
                from app.mappers.models import BusinessSubmission
                from app.mappers.missing_detector import detect_missing as _biz_detect
                bs = BusinessSubmission.from_dict(bd)
                return _biz_detect(bs, visibility)
            except Exception as exc:
                logger.warning("BusinessSubmission missing-detect failed, using raw fallback: %s", exc)

        # ── Raw fallback (YAML-driven services / mapper failure) ──────────────
        missing_info: list[dict] = []
        missing_docs: list[dict] = []

        for rule in rl.INFO_RULES:
            if not rule["required"](parsed):
                continue
            field_label = rule.get("label", "")
            if visibility.get(field_label) is False:
                continue
            if not rule["check"](parsed):
                missing_info.append({
                    "id":                 rule["id"],
                    "label":              rule["label"],
                    "reason":             rule["reason"](parsed),
                    "rule_triggered":     rule["id"],
                    "was_field_visible":  visibility.get(field_label, True),
                })

        for rule in rl.DOC_RULES:
            if not rule["required"](parsed):
                continue
            if not rule["check"](parsed):
                missing_docs.append({
                    "id":             rule["id"],
                    "label":          rule["label"],
                    "reason":         rule["reason"](parsed),
                    "rule_triggered": rule["id"],
                })

        return {
            "is_complete":  (not missing_info and not missing_docs),
            "missing_info": missing_info,
            "missing_docs": missing_docs,
        }

    # ── Step 4: cross-document validation (BusinessSubmission-first) ──────────

    def validate(
        self,
        parsed:          dict[str, Any],
        doc_extractions: dict[str, Any],
    ) -> list[ValidationIssue]:
        if parsed.get("_business"):
            return _business_validation_engine.validate(parsed, doc_extractions)
        return _validation_engine.validate(parsed, doc_extractions)

    # ── Step 5: draft email ───────────────────────────────────────────────────

    def draft_email(
        self,
        summary: dict[str, Any],
        missing: dict[str, Any],
    ) -> dict[str, str] | None:
        return draft_missing_info_email(
            summary,
            missing.get("missing_info", []),
            missing.get("missing_docs", []),
        )

    # ── Coercion ──────────────────────────────────────────────────────────────

    @staticmethod
    def _coerce(value: Any, ftype: str) -> Any:
        from app.utils.hebrew import clean_text, format_date, is_base64_image, safe_str

        if ftype == "date":
            return format_date(value)
        if ftype in ("file", "signature"):
            sv = safe_str(value)
            if is_base64_image(sv):
                return {"present": True, "url": ""}
            if sv.startswith("http"):
                return {"present": True, "url": sv}
            return {"present": bool(sv), "url": sv}
        if ftype == "bool":
            return safe_str(value).lower() in ("accepted", "הוסכם", "true", "1", "yes", "כן")
        if ftype == "multi":
            if isinstance(value, list):
                return [clean_text(str(v)) for v in value if v]
            return [s.strip() for s in safe_str(value).split(",") if s.strip()]
        return clean_text(safe_str(value))
