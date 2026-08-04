"""
Arnona transfer service — implements BaseService for the production
MAIN FORM 250201745267957 ("NEW MAIN FORM - 3.1 - Step 1 of 7").
Field IDs live in config/field_maps/arnona.yaml.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.base.service import BaseService
from app.services.arnona import field_map as fm
from app.services.arnona import summary as sm
from app.services.arnona.email_templates import draft_missing_info_email
from app.services.arnona.conditional_logic import arnona_logic_engine
from app.services.arnona.validators import ARNONA_VALIDATION_RULES
from app.mappers.business_validators import BUSINESS_VALIDATION_RULES
from app.pipeline.validator import ValidationEngine, ValidationIssue

logger = logging.getLogger("webhook")

FORM_ID = "250201745267957"

_validation_engine          = ValidationEngine(ARNONA_VALIDATION_RULES)
_business_validation_engine = ValidationEngine(BUSINESS_VALIDATION_RULES)


_JOTFORM_HOST = "https://www.jotform.com/"


def _resolve_pending_upload(path: str) -> str:
    """Turn a transient pending-submissions reference into its finalized URL.

    A LIVE webhook delivers an uploaded file as a relative reference:
        uploads/<acct>/pending-submissions/<form>/<sub>/<file>.png
    while the JotForm API reports the very same file as:
        https://www.jotform.com/uploads/<acct>/<form>/<sub>/<file>.png
    i.e. the finalized URL is the same path with the "pending-submissions/"
    segment removed. Verified byte-identical against the API for live
    submissions (7316-byte PNG, image/png) — without this the signature was
    never downloaded because the value did not start with "http".

    Replayed submissions already carry an absolute https URL and never reach
    this function. Returns "" for an unrecognised shape so the caller keeps
    the previous behaviour rather than inventing a URL.
    """
    s = (path or "").strip()
    if not s or "pending-submissions/" not in s:
        return ""
    s = s.replace("pending-submissions/", "", 1).lstrip("/")
    if s.startswith("http"):
        return s
    if not s.startswith("uploads/"):
        return ""
    return _JOTFORM_HOST + s


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
        parsed[fm.S_SYSTEM]["submission_id"] = raw_fields.get("submissionID") or ""

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
                # A value with real content always wins; an empty/placeholder
                # value only fills a label that is unset or itself empty — it
                # never clobbers content. Two fields can share the same label
                # (different flow paths, e.g. q104 for "מתחיל שכירות" and q214
                # for "בעל בית" both map to partner[שם_פרטי]; file uploads arrive
                # under both q34_input34 and the bare input34). The one carrying
                # real content wins regardless of arrival order.
                existing = parsed[section].get(label)
                if (label not in parsed[section]
                        or self._field_has_content(cleaned)
                        or not self._field_has_content(existing)):
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

    # ── Step 3: detect missing (canonical engine — app/rules/requirements) ───

    def detect_missing(
        self,
        parsed:     dict[str, Any],
        summary:    dict[str, Any],
        visibility: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        if visibility is None:
            visibility = arnona_logic_engine.evaluate(parsed)

        from app.mappers.models import BusinessSubmission
        from app.rules.requirements import detect_missing as _detect

        try:
            bd = parsed.get("_business")
            if bd:
                bs = BusinessSubmission.from_dict(bd)
            else:
                # Mapper didn't run in parse_fields (exception was logged
                # there) — build directly; build_from_parsed is defensive and
                # works on any section-keyed dict.
                from app.mappers.business_mapper import build_from_parsed
                bs = build_from_parsed(parsed)
            return _detect(bs, visibility)
        except Exception as exc:
            # No divergent fallback rule set anymore (v0.7): a failure here is
            # a bug to fix, not something to paper over with different rules.
            # Surface it loudly and mark the submission incomplete so it lands
            # in the operator queue instead of silently passing as complete.
            logger.error("Missing-detection engine failed for %s: %s",
                         parsed.get("system", {}).get("submission_id", "?"), exc)
            return {
                "is_complete":  False,
                "missing_info": [],
                "missing_docs": [],
                "engine_error": str(exc),
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
    def _field_has_content(value: Any) -> bool:
        """
        True if a coerced value carries real information (vs empty/placeholder).
        File/signature fields coerce to a dict that is ALWAYS truthy, so a plain
        `if value:` test wrongly treats an absent upload as content. Here a file
        dict counts only when it was detected present or captured a URL.
        """
        if value is None:
            return False
        if isinstance(value, dict):
            return bool(value.get("present") or value.get("url"))
        if isinstance(value, (list, tuple)):
            return len(value) > 0
        if isinstance(value, bool):
            return value
        return bool(str(value).strip())

    @staticmethod
    def _coerce(value: Any, ftype: str) -> Any:
        from app.utils.hebrew import clean_text, format_date, is_base64_image, safe_str

        if ftype == "date":
            return format_date(value)
        if ftype in ("file", "signature"):
            # Multi-file upload: JotForm sends a LIST of URLs. safe_str() joins
            # a list with ", ", producing one comma-separated string that is not
            # a valid URL — the downloader then requested "url1, url2" and lost
            # BOTH files. Keep every URL: "url" stays the first one so all
            # existing single-file consumers are unchanged, and "urls" carries
            # the full list for the downloader.
            if isinstance(value, (list, tuple)):
                _urls = [safe_str(v).strip() for v in value]
                _urls = [u for u in _urls if u.startswith("http")]
                if _urls:
                    return {"present": True, "url": _urls[0], "urls": _urls}
            sv = safe_str(value)
            if is_base64_image(sv):
                return {"present": True, "url": ""}
            if sv.startswith("http"):
                return {"present": True, "url": sv}
            if "pending-submissions" in sv:
                # Resolved to the finalized URL below (FIX 1); the raw path is
                # kept for traceability.
                # JotForm delivers a finalized upload via a transient
                # "uploads/.../pending-submissions/..." reference in the webhook
                # body. The file IS real — the JotForm API exposes its final URL
                # once the submission completes (verified 11/11 signatures:
                # every pending-submissions path resolved to a finalized URL).
                # Treat as present; keep the path for later API-based resolution.
                return {"present": True,
                        "url": _resolve_pending_upload(sv),
                        "pending_path": sv}
            # Empty value or a widget button label (e.g. "להעלות קובץ") — the
            # field carries no upload, so it is genuinely absent.
            return {"present": False, "url": "", "pending_path": sv}
        if ftype == "bool":
            return safe_str(value).lower() in ("accepted", "הוסכם", "true", "1", "yes", "כן")
        if ftype == "multi":
            if isinstance(value, list):
                return [clean_text(str(v)) for v in value if v]
            return [s.strip() for s in safe_str(value).split(",") if s.strip()]
        return clean_text(safe_str(value))
