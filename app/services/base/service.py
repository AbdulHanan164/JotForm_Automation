"""
Base contract for every service in the pipeline.

Each JotForm / service type (arnona, electricity, water, etc.)
implements this interface.  The orchestrator calls these methods
in order without knowing which concrete service it is talking to.

To add a new service:
  1. Create app/services/{name}/
  2. Subclass BaseService
  3. Register the form ID in app/pipeline/orchestrator.py

Nothing else changes in the core pipeline.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseService(ABC):

    # ── Identity ──────────────────────────────────────────────────────────
    @property
    @abstractmethod
    def form_id(self) -> str:
        """The JotForm form ID this service handles."""

    @property
    @abstractmethod
    def service_name(self) -> str:
        """Human-readable name, e.g. 'arnona_transfer'."""

    # ── Pipeline steps ────────────────────────────────────────────────────

    @abstractmethod
    def parse_fields(self, raw_fields: dict[str, Any]) -> dict[str, Any]:
        """
        Map raw JotForm field IDs → semantic labels.
        Returns a clean, section-keyed dict.
        No base64, no JotForm IDs in the output.
        """

    @abstractmethod
    def build_summary(self, parsed: dict[str, Any]) -> dict[str, Any]:
        """
        Build a business-focused summary from the parsed fields.
        All keys in Hebrew (or bilingual).
        This is what operators read.
        """

    @abstractmethod
    def detect_missing(
        self, parsed: dict[str, Any], summary: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Return a dict with:
          missing_info   — list of (label, reason)
          missing_docs   — list of (label, reason)
          is_complete    — bool
        Rules are city-aware and conditional-logic-aware.
        """

    @abstractmethod
    def draft_email(
        self,
        summary: dict[str, Any],
        missing: dict[str, Any],
    ) -> dict[str, str] | None:
        """
        Generate an RTL Hebrew draft email if anything is missing.
        Returns dict with keys: subject, body.
        Returns None if nothing is missing.
        """
