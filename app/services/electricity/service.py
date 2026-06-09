"""
Electricity account transfer service — STUB.

To implement:
  1. Get the JotForm form ID for the electricity form
  2. Paste real field IDs into field_map.py (use GET /discover/{id})
  3. Define business rules in rules.py
  4. Define conditional logic in conditional_logic.py
  5. Add email templates in email_templates.py
  6. Register the form ID in app/pipeline/orchestrator.py

The structure mirrors app/services/arnona/ exactly.
"""
from __future__ import annotations

from typing import Any
from app.services.base.service import BaseService
from app.pipeline.validator import ValidationIssue

FORM_ID = "ELECTRICITY_FORM_ID_HERE"   # ← replace with real form ID


class ElectricityService(BaseService):

    @property
    def form_id(self) -> str:
        return FORM_ID

    @property
    def service_name(self) -> str:
        return "electricity_transfer"

    def parse_fields(self, raw_fields: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Electricity field map not yet configured")

    def build_summary(self, parsed: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Electricity summary not yet configured")

    def detect_missing(self, parsed, summary, visibility=None) -> dict[str, Any]:
        raise NotImplementedError("Electricity rules not yet configured")

    def validate(self, parsed, doc_extractions) -> list[ValidationIssue]:
        return []   # no validators yet

    def draft_email(self, summary, missing) -> dict[str, str] | None:
        raise NotImplementedError("Electricity email template not yet configured")

    def get_document_types(self) -> list[str]:
        return ["חוזה_שכירות", "תעודת_זהות", "חשבון_חשמל", "חתימה"]
