"""
Formal conditional logic evaluator.

Mirrors JotForm's conditional logic engine exactly.
Each rule maps conditions → action (show/hide) on target fields.

Why this exists:
  Fields hidden by JotForm conditional logic must NEVER be marked as missing.
  The rules engine must know which fields were actually visible to the user.

Usage:
  engine = ConditionalLogicEngine(rules)
  visibility = engine.evaluate(form_state)
  # visibility["מספר_לקוח_ארנונה"] → False  (hidden for Ramat Gan)
  # visibility["מספר_נכס_ארנונה"]  → True   (always visible)

Each service defines its own rules list.
The engine is generic — services just provide different rule sets.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Condition operators ───────────────────────────────────────────────────────

class Op:
    EQUALS       = "equals"
    NOT_EQUALS   = "not_equals"
    CONTAINS     = "contains"
    NOT_CONTAINS = "not_contains"
    IS_EMPTY     = "is_empty"
    NOT_EMPTY    = "not_empty"
    IN           = "in"          # value in a list


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class Condition:
    """One condition: field_label operator value."""
    field:    str          # semantic label, e.g. "עיר" or "שירותים_נבחרים"
    section:  str          # which section to look in, e.g. "basic"
    operator: str          # Op constant
    value:    Any = None   # comparison value (None for IS_EMPTY / NOT_EMPTY)


@dataclass
class ConditionalRule:
    """
    IF all/any conditions match THEN apply action to target fields.

    action:  "hide" | "show" | "autofill"
    targets: list of field labels affected
    logic:   "all" (AND) | "any" (OR)
    note:    human-readable description for debugging
    """
    conditions: list[Condition]
    action:     str                      # "hide" | "show" | "autofill"
    targets:    list[str]                # field labels
    logic:      str          = "all"     # "all" | "any"
    autofill_source: str | None = None   # for action="autofill": source label
    note:       str          = ""


# ── Engine ────────────────────────────────────────────────────────────────────

class ConditionalLogicEngine:
    """
    Evaluates a set of ConditionalRules against a parsed form state.

    Usage:
      engine = ConditionalLogicEngine(SERVICE_RULES)
      visibility = engine.evaluate(parsed_form)
      is_visible = visibility.get("some_label", True)
    """

    def __init__(self, rules: list[ConditionalRule]):
        self.rules = rules

    def evaluate(self, parsed: dict[str, Any]) -> dict[str, bool]:
        """
        Return {field_label: is_visible} for every field mentioned in any rule.
        Fields NOT mentioned in any rule default to True (visible).
        """
        # Start with everything visible
        visibility: dict[str, bool] = {}

        for rule in self.rules:
            matched = self._matches(rule, parsed)
            if not matched:
                continue

            if rule.action == "hide":
                for target in rule.targets:
                    visibility[target] = False

            elif rule.action == "show":
                for target in rule.targets:
                    # Only set to True if not already explicitly hidden
                    if target not in visibility:
                        visibility[target] = True

            # autofill doesn't affect visibility

        return visibility

    def get_autofills(self, parsed: dict[str, Any]) -> dict[str, str]:
        """
        Return {target_label: source_label} for every autofill rule that fires.
        Used by the summary builder to note auto-populated fields.
        """
        autofills: dict[str, str] = {}
        for rule in self.rules:
            if rule.action != "autofill":
                continue
            if self._matches(rule, parsed) and rule.autofill_source:
                for target in rule.targets:
                    autofills[target] = rule.autofill_source
        return autofills

    def is_visible(self, field_label: str, parsed: dict[str, Any]) -> bool:
        """Convenience: check one field."""
        return self.evaluate(parsed).get(field_label, True)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _matches(self, rule: ConditionalRule, parsed: dict[str, Any]) -> bool:
        results = [self._eval_condition(c, parsed) for c in rule.conditions]
        if rule.logic == "all":
            return all(results)
        return any(results)

    @staticmethod
    def _eval_condition(cond: Condition, parsed: dict[str, Any]) -> bool:
        section_data = parsed.get(cond.section, {})
        raw_value    = section_data.get(cond.field, "")

        # Normalise to string list for multi-value fields
        if isinstance(raw_value, list):
            values = [str(v).strip() for v in raw_value]
            str_value = ", ".join(values)
        else:
            str_value = str(raw_value).strip()
            values = [str_value]

        op = cond.operator
        cv = cond.value  # comparison value

        if op == Op.EQUALS:
            return str_value == str(cv)
        if op == Op.NOT_EQUALS:
            return str_value != str(cv)
        if op == Op.CONTAINS:
            return str(cv) in str_value or any(str(cv) in v for v in values)
        if op == Op.NOT_CONTAINS:
            return str(cv) not in str_value
        if op == Op.IS_EMPTY:
            return not bool(str_value)
        if op == Op.NOT_EMPTY:
            return bool(str_value)
        if op == Op.IN:
            return str_value in (cv or [])
        return False
