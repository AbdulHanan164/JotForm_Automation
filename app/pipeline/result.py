"""
PipelineResult — the single object that flows through the pipeline
and is eventually saved to disk and returned to JotForm.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class PipelineResult:
    # Meta
    submission_id: str = "unknown"
    form_id:       str = ""
    form_title:    str = ""
    service_name:  str = "unknown"
    received_at:   str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # Business data (written by service)
    parsed:  dict[str, Any] = field(default_factory=dict)   # semantic fields
    summary: dict[str, Any] = field(default_factory=dict)   # business summary
    missing: dict[str, Any] = field(default_factory=dict)   # missing info/docs
    email:   dict[str, str] | None = None                   # draft email

    # Raw data (saved to raw JSON, never shown in business outputs)
    raw_fields:  dict[str, Any] = field(default_factory=dict)
    raw_request: dict[str, Any] = field(default_factory=dict)
    headers:     dict[str, str] = field(default_factory=dict)
    content_type: str = ""

    # Convenience
    @property
    def is_complete(self) -> bool:
        return self.missing.get("is_complete", False)

    @property
    def missing_info_labels(self) -> list[str]:
        return [item["label"] for item in self.missing.get("missing_info", [])]

    @property
    def missing_doc_labels(self) -> list[str]:
        return [item["label"] for item in self.missing.get("missing_docs", [])]

    def to_business_dict(self) -> dict[str, Any]:
        """The clean, operator-facing JSON.  No technical fields."""
        return {
            "מזהה":        self.submission_id,
            "שירות":       self.form_title or self.service_name,
            "התקבל":       self.received_at,
            "סיכום":       self.summary,
            "חסר_מידע":    self.missing.get("missing_info", []),
            "חסר_מסמכים":  self.missing.get("missing_docs", []),
            "הושלם":       self.is_complete,
            "טיוטת_מייל":  self.email,
        }

    def to_raw_dict(self) -> dict[str, Any]:
        """Full technical dump for debugging and future AI."""
        return {
            "submission_id": self.submission_id,
            "form_id":       self.form_id,
            "form_title":    self.form_title,
            "service_name":  self.service_name,
            "received_at":   self.received_at,
            "content_type":  self.content_type,
            "_parsed":       self.parsed,
            "_summary":      self.summary,
            "_missing":      self.missing,
            "_raw_fields":   self.raw_fields,
            "_raw_request":  self.raw_request,
        }
