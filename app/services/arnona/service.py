"""
Arnona transfer service — implements BaseService for form 251955479892982.

This is the concrete handler for "העברת חשבון ארנונה".
The orchestrator calls these methods without knowing implementation details.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.base.service import BaseService
from app.services.arnona import field_map as fm
from app.services.arnona import summary as sm
from app.services.arnona import rules as rl
from app.services.arnona.email_templates import draft_missing_info_email

logger = logging.getLogger("webhook")

FORM_ID = "251955479892982"


class ArnonaService(BaseService):

    @property
    def form_id(self) -> str:
        return FORM_ID

    @property
    def service_name(self) -> str:
        return "arnona_transfer"

    # ── Step 1: parse fields ──────────────────────────────────────────────────
    def parse_fields(self, raw_fields: dict[str, Any]) -> dict[str, Any]:
        """
        Map JotForm field IDs → section-keyed semantic labels.
        Removes base64, skips unknown fields (stores them in _unmapped).
        """
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
            "_unmapped":   {},
        }

        for field_id, value in raw_fields.items():
            mapping = fm.FIELD_MAP.get(field_id)
            if mapping is None:
                # Keep unmapped for field discovery
                if isinstance(value, str) and len(value) < 500:
                    parsed["_unmapped"][field_id] = value
                continue

            section = mapping["section"]
            label   = mapping["label"]
            ftype   = mapping["type"]
            cleaned = self._coerce(value, ftype)

            if section in parsed:
                parsed[section][label] = cleaned
            else:
                parsed["_unmapped"][field_id] = value

        return parsed

    # ── Step 2: build summary ─────────────────────────────────────────────────
    def build_summary(self, parsed: dict[str, Any]) -> dict[str, Any]:
        return sm.build(parsed)

    # ── Step 3: detect missing ────────────────────────────────────────────────
    def detect_missing(
        self, parsed: dict[str, Any], summary: dict[str, Any]
    ) -> dict[str, Any]:
        missing_info: list[dict] = []
        missing_docs: list[dict] = []

        for rule in rl.INFO_RULES:
            if not rule["required"](parsed):
                continue
            if not rule["check"](parsed):
                missing_info.append({
                    "id":     rule["id"],
                    "label":  rule["label"],
                    "reason": rule["reason"](parsed),
                })

        for rule in rl.DOC_RULES:
            if not rule["required"](parsed):
                continue
            if not rule["check"](parsed):
                missing_docs.append({
                    "id":     rule["id"],
                    "label":  rule["label"],
                    "reason": rule["reason"](parsed),
                })

        is_complete = (len(missing_info) == 0 and len(missing_docs) == 0)

        return {
            "is_complete":  is_complete,
            "missing_info": missing_info,
            "missing_docs": missing_docs,
        }

    # ── Step 4: draft email ───────────────────────────────────────────────────
    def draft_email(
        self,
        summary: dict[str, Any],
        missing: dict[str, Any],
    ) -> dict[str, str] | None:
        missing_info = missing.get("missing_info", [])
        missing_docs = missing.get("missing_docs", [])
        return draft_missing_info_email(summary, missing_info, missing_docs)

    # ── Value coercion by field type ──────────────────────────────────────────
    @staticmethod
    def _coerce(value: Any, ftype: str) -> Any:
        """Normalise a raw JotForm value based on its declared type."""
        from app.utils.hebrew import clean_text, format_date, is_base64_image, safe_str

        if ftype == "date":
            return format_date(value)

        if ftype in ("file", "signature"):
            sv = safe_str(value)
            if is_base64_image(sv):
                # Never store raw base64 — store a presence flag
                return {"present": True, "url": ""}
            if sv.startswith("http"):
                return {"present": True, "url": sv}
            if sv:
                return {"present": True, "url": sv}
            return {"present": False, "url": ""}

        if ftype == "bool":
            sv = safe_str(value).lower()
            return sv in ("accepted", "הוסכם", "true", "1", "yes", "כן")

        if ftype == "multi":
            if isinstance(value, list):
                return [clean_text(str(v)) for v in value if v]
            return [s.strip() for s in safe_str(value).split(",") if s.strip()]

        # text / phone / email / id_num / select
        return clean_text(safe_str(value))
