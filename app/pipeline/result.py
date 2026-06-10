"""
PipelineResult — the single object that flows through the full pipeline.

Version 0.4.0 additions:
  - doc_extractions   : extracted data from uploaded documents
  - validation_issues : cross-document consistency issues
  - unified_view      : merged form + document data
  - visibility        : which fields were visible (conditional logic)
  - review_status     : pending_review | approved | rejected
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.pipeline.validator import ValidationIssue


@dataclass
class PipelineResult:

    # ── Meta ──────────────────────────────────────────────────────────────────
    submission_id: str = "unknown"
    form_id:       str = ""
    form_title:    str = ""
    service_name:  str = "unknown"
    received_at:   str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # ── Business data (written by service) ────────────────────────────────────
    parsed:        dict[str, Any] = field(default_factory=dict)   # semantic section-keyed fields
    summary:       dict[str, Any] = field(default_factory=dict)   # Hebrew business summary
    missing:       dict[str, Any] = field(default_factory=dict)   # {is_complete, missing_info, missing_docs}
    email:         dict[str, str] | None = None                   # draft email (subject + body)
    business_data: dict[str, Any] = field(default_factory=dict)   # BusinessSubmission.to_dict()

    # ── Conditional logic ─────────────────────────────────────────────────────
    visibility: dict[str, bool] = field(default_factory=dict)
    # field_label → True/False (False = hidden by JotForm, must not be flagged missing)

    # ── Document extraction ───────────────────────────────────────────────────
    doc_extractions: dict[str, Any] = field(default_factory=dict)
    # label → BaseExtraction.to_dict() for each uploaded doc

    # ── Cross-document validation ─────────────────────────────────────────────
    validation_issues: list["ValidationIssue"] = field(default_factory=list)
    # ordered: errors → warnings → info

    # ── Unified view ──────────────────────────────────────────────────────────
    unified_view: dict[str, Any] = field(default_factory=dict)
    # merged form data + document facts, used by validator

    # ── Review workflow ───────────────────────────────────────────────────────
    review_status: str = "pending_review"

    # ── Raw data (debug / AI) ─────────────────────────────────────────────────
    raw_fields:   dict[str, Any] = field(default_factory=dict)
    raw_request:  dict[str, Any] = field(default_factory=dict)
    headers:      dict[str, str] = field(default_factory=dict)
    content_type: str = ""

    # ── Convenience properties ────────────────────────────────────────────────

    @property
    def is_complete(self) -> bool:
        return self.missing.get("is_complete", False)

    @property
    def missing_info_labels(self) -> list[str]:
        return [i["label"] for i in self.missing.get("missing_info", [])]

    @property
    def missing_doc_labels(self) -> list[str]:
        return [i["label"] for i in self.missing.get("missing_docs", [])]

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.validation_issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.validation_issues if i.severity == "warning")

    # ── Output formats ────────────────────────────────────────────────────────

    def to_business_dict(self) -> dict[str, Any]:
        """Operator-facing output. No JotForm IDs, no base64, no technical fields."""
        d: dict[str, Any] = {
            "מזהה":              self.submission_id,
            "שירות":             self.form_title or self.service_name,
            "התקבל":             self.received_at,
            "סטטוס_בדיקה":       self.review_status,
            "סיכום":             self.summary,
            "חסר_מידע":          self.missing.get("missing_info", []),
            "חסר_מסמכים":        self.missing.get("missing_docs", []),
            "הושלם":             self.is_complete,
            "בעיות_עקביות":      [i.to_dict() for i in self.validation_issues],
            "מסמכים_שנותחו":     self.doc_extractions,
            "שדות_מוסתרים":      [k for k, v in self.visibility.items() if not v],
            "טיוטת_מייל":        self.email,
        }
        if self.business_data:
            d["business_data"] = self.business_data
        return d

    def to_raw_dict(self) -> dict[str, Any]:
        """Full technical dump for debugging and future AI use."""
        # Exclude _business key from parsed dump (it's already in business_data)
        parsed_clean = {k: v for k, v in self.parsed.items() if k != "_business"}
        return {
            "submission_id":    self.submission_id,
            "form_id":          self.form_id,
            "form_title":       self.form_title,
            "service_name":     self.service_name,
            "received_at":      self.received_at,
            "review_status":    self.review_status,
            "content_type":     self.content_type,
            "_parsed":          parsed_clean,
            "_business":        self.business_data,
            "_summary":         self.summary,
            "_missing":         self.missing,
            "_visibility":      self.visibility,
            "_validation_issues": [i.to_dict() for i in self.validation_issues],
            "_doc_extractions": self.doc_extractions,
            "_unified_view":    self.unified_view,
            "_raw_fields":      self.raw_fields,
            "_raw_request":     self.raw_request,
        }
