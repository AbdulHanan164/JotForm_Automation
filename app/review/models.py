"""
Review workflow models.

Every submission enters the pipeline as "pending_review".
An operator reviews it and either approves or flags it as needs_info.
Email is only sent after approval.

States:
  pending_review  — waiting for operator
  approved        — operator approved, email can be sent
  needs_info      — operator flagged it for follow-up before approval
  sent            — email was sent (final state)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ReviewStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    APPROVED       = "approved"
    NEEDS_INFO     = "needs_info"
    SENT           = "sent"


@dataclass
class ReviewItem:
    submission_id:   str
    service_name:    str
    form_title:      str
    received_at:     str

    # Summary for quick operator view
    customer_name:   str = ""
    customer_phone:  str = ""
    customer_email:  str = ""
    property_address:str = ""
    services:        str = ""
    mzk_ref:         str = ""

    # Review state
    status:          ReviewStatus = ReviewStatus.PENDING_REVIEW
    reviewed_at:     str | None   = None
    reviewed_by:     str | None   = None
    review_notes:    str          = ""

    # Full data (stored in review file)
    summary:          dict[str, Any] = field(default_factory=dict)
    missing_info:     list[dict]     = field(default_factory=list)
    missing_docs:     list[dict]     = field(default_factory=list)
    validation_issues: list[dict]   = field(default_factory=list)
    doc_extractions:  dict[str, Any] = field(default_factory=dict)
    draft_email:      dict[str, str] | None = None

    # Business-centric model (BusinessSubmission.to_dict()) — operator-facing
    business_data:    dict[str, Any] = field(default_factory=dict)

    # Operator can edit the email before approving
    final_email:      dict[str, str] | None = None

    # Document acquisition state (Group A). "" = not tracked (legacy / jobs off).
    # Set by the document job: docs_pending | ready | partial | failed.
    documents_status: str = ""

    @property
    def is_actionable(self) -> bool:
        """True if operator still needs to act on this."""
        return self.status in (
            ReviewStatus.PENDING_REVIEW, ReviewStatus.NEEDS_INFO
        )

    @property
    def has_errors(self) -> bool:
        return any(
            i.get("severity") == "error" for i in self.validation_issues
        )

    @property
    def has_warnings(self) -> bool:
        return any(
            i.get("severity") == "warning" for i in self.validation_issues
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "submission_id":    self.submission_id,
            "service_name":     self.service_name,
            "form_title":       self.form_title,
            "received_at":      self.received_at,
            "customer_name":    self.customer_name,
            "customer_phone":   self.customer_phone,
            "customer_email":   self.customer_email,
            "property_address": self.property_address,
            "services":         self.services,
            "mzk_ref":          self.mzk_ref,
            "status":           self.status.value,
            "reviewed_at":      self.reviewed_at,
            "reviewed_by":      self.reviewed_by,
            "review_notes":     self.review_notes,
            "summary":          self.summary,
            "business_data":    self.business_data,
            "missing_info":     self.missing_info,
            "missing_docs":     self.missing_docs,
            "validation_issues":self.validation_issues,
            "doc_extractions":  self.doc_extractions,
            "draft_email":      self.draft_email,
            "final_email":      self.final_email,
            "documents_status": self.documents_status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReviewItem":
        item = cls(
            submission_id    = data["submission_id"],
            service_name     = data.get("service_name", ""),
            form_title       = data.get("form_title", ""),
            received_at      = data.get("received_at", ""),
            customer_name    = data.get("customer_name", ""),
            customer_phone   = data.get("customer_phone", ""),
            customer_email   = data.get("customer_email", ""),
            property_address = data.get("property_address", ""),
            services         = data.get("services", ""),
            mzk_ref          = data.get("mzk_ref", ""),
            review_notes     = data.get("review_notes", ""),
            summary          = data.get("summary", {}),
            business_data    = data.get("business_data", {}),
            missing_info     = data.get("missing_info", []),
            missing_docs     = data.get("missing_docs", []),
            validation_issues= data.get("validation_issues", []),
            doc_extractions  = data.get("doc_extractions", {}),
            draft_email      = data.get("draft_email"),
            final_email      = data.get("final_email"),
            documents_status = data.get("documents_status", ""),
        )
        try:
            item.status = ReviewStatus(data.get("status", "pending_review"))
        except ValueError:
            item.status = ReviewStatus.PENDING_REVIEW
        item.reviewed_at = data.get("reviewed_at")
        item.reviewed_by = data.get("reviewed_by")
        return item
