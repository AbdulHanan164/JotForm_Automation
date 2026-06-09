"""
Cross-document validation engine.

Runs consistency rules across the unified view (form data + extracted docs).
Returns a list of ValidationIssues, sorted by severity.

Severity levels:
  error    — blocks approval (e.g. name on ID doesn't match form)
  warning  — requires attention but doesn't block (e.g. landlord = outgoing tenant)
  info     — notable, no action needed (e.g. lease mentions guarantor)

Each service defines its own validation rules.
The engine is generic.

Difference from missing-field rules:
  missing rules  → "this required field was not filled in"
  validation rules → "this field was filled in but conflicts with another field/document"
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class ValidationIssue:
    id:               str
    severity:         str          # "error" | "warning" | "info"
    label:            str          # short Hebrew label shown to operator
    description:      str          # full Hebrew explanation
    rule_triggered:   str          # which business rule fired (for audit)
    affected_fields:  list[str]    = field(default_factory=list)
    conflicting_values: dict[str, str] = field(default_factory=dict)
    suggestion:       str          = ""   # what operator should do

    def to_dict(self) -> dict[str, Any]:
        return {
            "id":                 self.id,
            "severity":           self.severity,
            "label":              self.label,
            "description":        self.description,
            "rule_triggered":     self.rule_triggered,
            "affected_fields":    self.affected_fields,
            "conflicting_values": self.conflicting_values,
            "suggestion":         self.suggestion,
        }


@dataclass
class ValidationRule:
    """
    A single validation rule.

    check(parsed, doc_extractions) → ValidationIssue | None
    If check returns an issue, that issue is added to the results.
    If check returns None, the rule passed.
    """
    id:      str
    enabled: bool = True
    check:   Callable[[dict, dict], ValidationIssue | None] = field(
        default=lambda p, d: None
    )


# ── Engine ────────────────────────────────────────────────────────────────────

class ValidationEngine:

    def __init__(self, rules: list[ValidationRule]):
        self.rules = [r for r in rules if r.enabled]

    def validate(
        self,
        parsed:         dict[str, Any],
        doc_extractions: dict[str, Any],
    ) -> list[ValidationIssue]:
        """
        Run all rules against the unified view.
        Returns list sorted: errors first, then warnings, then info.
        """
        issues: list[ValidationIssue] = []
        for rule in self.rules:
            try:
                issue = rule.check(parsed, doc_extractions)
                if issue is not None:
                    issues.append(issue)
            except Exception as exc:
                # Rule failure must not stop the pipeline
                issues.append(ValidationIssue(
                    id             = f"{rule.id}_rule_error",
                    severity       = "info",
                    label          = f"שגיאה בכלל {rule.id}",
                    description    = f"כלל הבדיקה נכשל: {exc}",
                    rule_triggered = rule.id,
                ))

        order = {"error": 0, "warning": 1, "info": 2}
        return sorted(issues, key=lambda i: order.get(i.severity, 9))
