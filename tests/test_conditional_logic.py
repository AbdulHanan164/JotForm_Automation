"""
Tests for FIX #4: YAML conditional logic engine — section-keyed parsed format.

THE BUG (v0.5.0):
  YAMLDrivenService.parse_fields() returned a FLAT dict:
    {"עיר": "רמת גן", "שם_פרטי": "ישראל"}

  ConditionalLogicEngine._eval_condition() does:
    parsed.get(cond.section, {})         → always {} (section not found)
  and get_conditional_logic_engine() created Condition(section="") for all conditions.

  Result: ALL fields stayed visible regardless of city/service. Missing-field
  detection always ran on ALL fields, producing wrong emails.

THE FIX (v0.6.0):
  parse_fields() returns section-keyed dict:
    {"basic": {"עיר": "רמת גן"}, "customer": {"שם_פרטי": "ישראל"}}
  get_conditional_logic_engine() resolves section via _section_for_field(label).

TESTS:
  - parse_fields() returns section-keyed dict (not flat).
  - ConditionalLogicEngine evaluates correctly against section-keyed dict.
  - A "hide" rule correctly marks a field as not visible.
  - A "show" rule correctly marks a field as visible.
  - Conditions with wrong section always fail (regression guard).
  - detect_missing() skips hidden fields.
"""
from __future__ import annotations

import pytest
from pathlib import Path
from app.config_service.loader import YAMLDrivenService
from app.pipeline.conditional_logic import (
    ConditionalLogicEngine, ConditionalRule, Condition, Op,
)


# ── Minimal YAML service config for testing ───────────────────────────────────

def _make_service(extra_cond=None) -> YAMLDrivenService:
    """Build a minimal YAMLDrivenService with a couple of test fields."""
    cond = extra_cond or []
    config = {
        "service": {
            "name": "test_service",
            "display_name": "Test Service",
            "form_id": "999999999",
        },
        "fields": [
            {"jotform_id": "q1", "label": "עיר",         "section": "basic",    "type": "text",  "required": "always"},
            {"jotform_id": "q2", "label": "שירות",        "section": "basic",    "type": "text",  "required": "always"},
            {"jotform_id": "q3", "label": "שם_פרטי",     "section": "customer", "type": "text",  "required": "always"},
            {"jotform_id": "q4", "label": "מספר_נכס",    "section": "arnona",   "type": "text",  "required": "always"},
            {"jotform_id": "q5", "label": "טלפון_שוכר2", "section": "partner",  "type": "text",  "required": "always"},
        ],
        "conditional_rules": cond,
        "required_documents": [],
        "missing_info_rules": [],
        "email": {},
    }
    return YAMLDrivenService(config, Path("test.yaml"))


# ── parse_fields() format ─────────────────────────────────────────────────────

class TestParseFieldsFormat:
    """parse_fields() must return a section-keyed dict (v0.6 fix)."""

    def test_returns_section_keyed_dict(self):
        svc = _make_service()
        raw = {"q1": "רמת גן", "q3": "ישראל"}
        parsed = svc.parse_fields(raw)

        # Must have section keys, NOT flat keys
        assert "basic" in parsed, "Expected 'basic' section in parsed dict"
        assert "customer" in parsed, "Expected 'customer' section in parsed dict"

    def test_values_nested_under_sections(self):
        svc = _make_service()
        raw = {"q1": "תל אביב", "q3": "שרה"}
        parsed = svc.parse_fields(raw)

        assert parsed["basic"]["עיר"] == "תל אביב"
        assert parsed["customer"]["שם_פרטי"] == "שרה"

    def test_flat_key_not_at_top_level(self):
        """Regression: flat key 'עיר' must NOT appear at the top level."""
        svc = _make_service()
        raw = {"q1": "חיפה"}
        parsed = svc.parse_fields(raw)

        assert "עיר" not in parsed, (
            "BUG: 'עיר' is at the top level — parse_fields() returned a flat dict. "
            "This is the v0.5.0 bug — section-keyed format required."
        )

    def test_unmapped_fields_collected(self):
        svc = _make_service()
        raw = {"q1": "תל אביב", "unknown_field_99": "some value"}
        parsed = svc.parse_fields(raw)
        assert "unknown_field_99" in parsed.get("_unmapped", {})

    def test_empty_raw_returns_empty_sections(self):
        svc = _make_service()
        parsed = svc.parse_fields({})
        # All known sections present, all empty
        assert parsed["basic"] == {}
        assert parsed["customer"] == {}

    def test_multiple_sections_populated(self):
        svc = _make_service()
        raw = {"q1": "ירושלים", "q3": "דוד", "q4": "12345"}
        parsed = svc.parse_fields(raw)
        assert parsed["basic"]["עיר"] == "ירושלים"
        assert parsed["customer"]["שם_פרטי"] == "דוד"
        assert parsed["arnona"]["מספר_נכס"] == "12345"


# ── ConditionalLogicEngine with section-keyed dict ────────────────────────────

class TestConditionalLogicEngineWithSectionKeyed:
    """The engine must evaluate correctly against section-keyed parsed dicts."""

    def test_hide_rule_fires_when_condition_met(self):
        """
        Rule: hide 'מספר_נכס' when basic.שירות != 'ארנונה'.
        Condition: basic.שירות == 'חשמל' → hide arnona field.
        """
        rules = [
            ConditionalRule(
                note="hide arnona fields when no arnona service",
                logic="all",
                conditions=[
                    Condition(field="שירות", section="basic", operator=Op.NOT_EQUALS, value="ארנונה"),
                ],
                action="hide",
                targets=["מספר_נכס"],
            ),
        ]
        engine = ConditionalLogicEngine(rules)
        parsed = {
            "basic":   {"שירות": "חשמל"},
            "arnona":  {"מספר_נכס": "12345"},
        }
        visibility = engine.evaluate(parsed)
        assert visibility.get("מספר_נכס") is False, (
            "Engine should hide 'מספר_נכס' when service is 'חשמל'"
        )

    def test_hide_rule_does_not_fire_when_condition_not_met(self):
        rules = [
            ConditionalRule(
                note="hide arnona fields when no arnona service",
                logic="all",
                conditions=[
                    Condition(field="שירות", section="basic", operator=Op.NOT_EQUALS, value="ארנונה"),
                ],
                action="hide",
                targets=["מספר_נכס"],
            ),
        ]
        engine = ConditionalLogicEngine(rules)
        parsed = {
            "basic":  {"שירות": "ארנונה"},  # service IS ארנונה — don't hide
            "arnona": {"מספר_נכס": "12345"},
        }
        visibility = engine.evaluate(parsed)
        # Field should remain visible (True or absent from dict)
        assert visibility.get("מספר_נכס", True) is True

    def test_wrong_section_condition_never_fires(self):
        """
        Regression guard: if section="" (v0.5 bug), the engine can't find the field.
        With the fix, this should reliably evaluate to False (no match → hide does not fire).
        """
        rules = [
            ConditionalRule(
                note="broken condition with no section",
                logic="all",
                conditions=[
                    Condition(field="שירות", section="", operator=Op.EQUALS, value="חשמל"),
                ],
                action="hide",
                targets=["מספר_נכס"],
            ),
        ]
        engine = ConditionalLogicEngine(rules)
        parsed = {
            "basic":  {"שירות": "חשמל"},  # correct value, but engine can't find it
            "arnona": {"מספר_נכס": "12345"},
        }
        visibility = engine.evaluate(parsed)
        # With empty section, the condition should NOT evaluate to True
        # (engine looks in parsed.get("", {}) which is empty)
        assert visibility.get("מספר_נכס", True) is True, (
            "With empty section, hide rule should not fire — "
            "this confirms the old v0.5 bug behavior"
        )

    def test_all_logic_requires_all_conditions(self):
        """logic='all': both conditions must match for rule to fire."""
        rules = [
            ConditionalRule(
                note="hide when city=רמת גן AND service=ארנונה",
                logic="all",
                conditions=[
                    Condition(field="עיר",    section="basic", operator=Op.EQUALS, value="רמת גן"),
                    Condition(field="שירות", section="basic", operator=Op.EQUALS, value="ארנונה"),
                ],
                action="hide",
                targets=["מספר_נכס"],
            ),
        ]
        engine = ConditionalLogicEngine(rules)

        # Only one condition matches → rule should NOT fire
        parsed_partial = {"basic": {"עיר": "רמת גן", "שירות": "חשמל"}}
        vis = engine.evaluate(parsed_partial)
        assert vis.get("מספר_נכס", True) is True

        # Both conditions match → rule fires
        parsed_full = {"basic": {"עיר": "רמת גן", "שירות": "ארנונה"}}
        vis = engine.evaluate(parsed_full)
        assert vis.get("מספר_נכס") is False

    def test_any_logic_requires_one_condition(self):
        """logic='any': at least one condition must match for rule to fire."""
        rules = [
            ConditionalRule(
                note="hide when city=חיפה OR city=באר שבע",
                logic="any",
                conditions=[
                    Condition(field="עיר", section="basic", operator=Op.EQUALS, value="חיפה"),
                    Condition(field="עיר", section="basic", operator=Op.EQUALS, value="באר שבע"),
                ],
                action="hide",
                targets=["מספר_נכס"],
            ),
        ]
        engine = ConditionalLogicEngine(rules)

        # First condition matches → fires
        parsed = {"basic": {"עיר": "חיפה"}}
        vis = engine.evaluate(parsed)
        assert vis.get("מספר_נכס") is False

        # Second condition matches → fires
        parsed = {"basic": {"עיר": "באר שבע"}}
        vis = engine.evaluate(parsed)
        assert vis.get("מספר_נכס") is False

        # Neither matches → does not fire
        parsed = {"basic": {"עיר": "תל אביב"}}
        vis = engine.evaluate(parsed)
        assert vis.get("מספר_נכס", True) is True


# ── YAML service conditional logic (end-to-end) ───────────────────────────────

class TestYAMLServiceConditionalLogic:
    """get_conditional_logic_engine() builds a correctly configured engine."""

    def test_engine_built_from_yaml_config(self):
        cond = [
            {
                "note":   "hide partner phone unless partner info given",
                "logic":  "all",
                "action": "hide",
                "conditions": [
                    {"field": "עיר", "operator": "equals", "value": "תל אביב"},
                ],
                "targets": ["טלפון_שוכר2"],
            }
        ]
        svc = _make_service(extra_cond=cond)
        engine = svc.get_conditional_logic_engine()
        assert engine is not None

    def test_engine_resolves_correct_section(self):
        """
        The engine's condition must have section='basic' for field 'עיר',
        not section='' (the v0.5 bug).
        """
        cond = [
            {
                "note":   "test section resolution",
                "logic":  "all",
                "action": "hide",
                "conditions": [
                    {"field": "עיר", "operator": "equals", "value": "רמת גן"},
                ],
                "targets": ["מספר_נכס"],
            }
        ]
        svc = _make_service(extra_cond=cond)
        engine = svc.get_conditional_logic_engine()

        # Parse with the section-keyed format
        raw = {"q1": "רמת גן", "q4": "12345"}
        parsed = svc.parse_fields(raw)

        # Engine should find 'עיר' in 'basic' and fire the hide rule
        visibility = engine.evaluate(parsed)
        assert visibility.get("מספר_נכס") is False, (
            "Engine should hide 'מספר_נכס' when עיר=רמת גן. "
            "If this fails, the section was not resolved correctly (v0.5 bug)."
        )

    def test_detect_missing_skips_hidden_fields(self):
        """
        detect_missing() must skip fields hidden by conditional logic.
        If visibility['מספר_נכס'] = False, the missing detection should
        NOT flag 'מספר_נכס' as missing.
        """
        cond = [
            {
                "note":   "hide arnona when service=חשמל",
                "logic":  "all",
                "action": "hide",
                "conditions": [
                    {"field": "שירות", "operator": "equals", "value": "חשמל"},
                ],
                "targets": ["מספר_נכס"],
            }
        ]
        svc = _make_service(extra_cond=cond)

        # Submission has no arnona number (because service is חשמל, so it's hidden)
        raw = {"q1": "תל אביב", "q2": "חשמל", "q3": "ישראל"}
        parsed = svc.parse_fields(raw)

        engine = svc.get_conditional_logic_engine()
        visibility = engine.evaluate(parsed) if engine else {}

        summary = {}
        missing = svc.detect_missing(parsed, summary, visibility)

        missing_labels = [m["label"] for m in missing["missing_info"]]
        assert "מספר_נכס" not in missing_labels, (
            "מספר_נכס is hidden by conditional logic — "
            "it should NOT appear in missing_info"
        )
