"""
Water account transfer service — STUB.
Same implementation pattern as electricity and arnona.
"""
from __future__ import annotations

from typing import Any
from app.services.base.service import BaseService
from app.pipeline.validator import ValidationIssue

FORM_ID = "WATER_FORM_ID_HERE"   # ← replace with real form ID


class WaterService(BaseService):

    @property
    def form_id(self) -> str:
        return FORM_ID

    @property
    def service_name(self) -> str:
        return "water_transfer"

    def parse_fields(self, raw_fields: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Water field map not yet configured")

    def build_summary(self, parsed: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Water summary not yet configured")

    def detect_missing(self, parsed, summary, visibility=None) -> dict[str, Any]:
        raise NotImplementedError("Water rules not yet configured")

    def validate(self, parsed, doc_extractions) -> list[ValidationIssue]:
        return []

    def draft_email(self, summary, missing) -> dict[str, str] | None:
        raise NotImplementedError("Water email template not yet configured")

    def get_document_types(self) -> list[str]:
        return ["חוזה_שכירות", "תעודת_זהות", "חשבון_מים", "חתימה"]
