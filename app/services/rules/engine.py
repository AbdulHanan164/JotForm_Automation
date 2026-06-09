"""
Rule engine — evaluates DOCUMENT_RULES against a ParsedSubmission
and returns a DocumentReport.

Design:
  - Rules are data (list of dicts in document_rules.py).
  - The engine is a pure function: no state, no I/O.
  - Future AI can consume the report or override individual rule results.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.services.rules.document_rules import DOCUMENT_RULES

if TYPE_CHECKING:
    from app.parsers.jotform_parser import ParsedSubmission

logger = logging.getLogger("webhook")


@dataclass
class RuleResult:
    rule_id:   str
    label:     str
    section:   str
    required:  bool
    present:   bool

    @property
    def missing(self) -> bool:
        return self.required and not self.present

    @property
    def status(self) -> str:
        if not self.required:
            return "optional"
        return "ok" if self.present else "missing"


@dataclass
class DocumentReport:
    results:  list[RuleResult] = field(default_factory=list)

    @property
    def received(self) -> list[str]:
        return [r.label for r in self.results if r.present]

    @property
    def missing(self) -> list[str]:
        return [r.label for r in self.results if r.missing]

    @property
    def optional_missing(self) -> list[str]:
        return [r.label for r in self.results if not r.required and not r.present]

    @property
    def is_complete(self) -> bool:
        return len(self.missing) == 0

    def to_dict(self) -> dict:
        return {
            "is_complete":      self.is_complete,
            "received":         self.received,
            "missing":          self.missing,
            "optional_missing": self.optional_missing,
            "detail": [
                {
                    "id":       r.rule_id,
                    "label":    r.label,
                    "section":  r.section,
                    "required": r.required,
                    "present":  r.present,
                    "status":   r.status,
                }
                for r in self.results
            ],
        }


class RuleEngine:
    """Evaluate all document rules against a submission."""

    @staticmethod
    def evaluate(sub: "ParsedSubmission") -> DocumentReport:
        report = DocumentReport()

        for rule in DOCUMENT_RULES:
            try:
                is_required = bool(rule["required"](sub))
                is_present  = bool(rule["check"](sub))
            except Exception as exc:
                logger.warning("Rule %s evaluation error: %s", rule["id"], exc)
                is_required = False
                is_present  = False

            result = RuleResult(
                rule_id  = rule["id"],
                label    = rule["label"],
                section  = rule["section"],
                required = is_required,
                present  = is_present,
            )
            report.results.append(result)

            if result.missing:
                logger.warning("MISSING: %s", result.label)

        logger.info(
            "Document check: %d received, %d missing",
            len(report.received),
            len(report.missing),
        )
        return report
