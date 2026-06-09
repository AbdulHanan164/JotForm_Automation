"""
Base contract for every service in the pipeline.

Each JotForm / service type implements this interface.
The orchestrator calls these methods in order.

To add a new service:
  1. Create app/services/{name}/
  2. Subclass BaseService, implement all abstract methods
  3. Register in app/pipeline/orchestrator.py

Nothing else changes in the core pipeline.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.pipeline.conditional_logic import ConditionalLogicEngine
from app.pipeline.validator import ValidationEngine, ValidationIssue


class BaseService(ABC):

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    @abstractmethod
    def form_id(self) -> str:
        """The JotForm form ID this service handles."""

    @property
    @abstractmethod
    def service_name(self) -> str:
        """Slug name, e.g. 'arnona_transfer'."""

    # ── Pipeline steps ────────────────────────────────────────────────────────

    @abstractmethod
    def parse_fields(self, raw_fields: dict[str, Any]) -> dict[str, Any]:
        """
        Map raw JotForm field IDs → section-keyed semantic labels.
        No base64, no JotForm IDs in output.
        Uses the conditional logic engine to resolve auto-fills.
        """

    @abstractmethod
    def build_summary(self, parsed: dict[str, Any]) -> dict[str, Any]:
        """Build a business-focused Hebrew summary. This is what operators read."""

    @abstractmethod
    def detect_missing(
        self,
        parsed:     dict[str, Any],
        summary:    dict[str, Any],
        visibility: dict[str, bool],   # ← from conditional logic engine
    ) -> dict[str, Any]:
        """
        Detect missing required fields/docs.
        visibility dict ensures hidden fields are NEVER flagged as missing.
        Returns: {is_complete, missing_info, missing_docs}
        """

    @abstractmethod
    def validate(
        self,
        parsed:          dict[str, Any],
        doc_extractions: dict[str, Any],
    ) -> list[ValidationIssue]:
        """
        Cross-document consistency validation.
        Compares form data against extracted document data.
        Returns list of ValidationIssue (errors/warnings/info).
        """

    @abstractmethod
    def draft_email(
        self,
        summary:  dict[str, Any],
        missing:  dict[str, Any],
    ) -> dict[str, str] | None:
        """
        Generate RTL Hebrew draft email for missing items.
        Returns None if nothing is missing.
        Email is NEVER sent automatically — always goes through review.
        """

    # ── Optional: override to provide service-specific engines ───────────────

    def get_conditional_logic_engine(self) -> ConditionalLogicEngine | None:
        """Override to return service-specific conditional logic engine."""
        return None

    def get_validation_engine(self) -> ValidationEngine | None:
        """Override to return service-specific validation engine."""
        return None

    def get_document_types(self) -> list[str]:
        """
        Return list of document labels this service expects to extract.
        Used by the document extractor to prioritize.
        """
        return []
