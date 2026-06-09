"""
JotForm → Internal Rule Converter.

Takes the raw JotForm API form definition (questions + properties.conditions)
and converts it into:
  1. FieldMap entries    (field_id → {label, section, type})
  2. ConditionalRules    (executable ConditionalLogicEngine rules)
  3. RequiredFields      (from question.required == "Yes")

JotForm condition format (from /form/{id}/properties):
  {
    "conditions": [
      {
        "id": "1",
        "link": "And",         ← how to join with NEXT rule
        "action": "hide",      ← "hide" | "show" | "calculate" | "sendEmail" etc.
        "field": "q5_services5",
        "filters": [
          {"field": "q4_cityName4", "operator": "equals", "value": "רמת גן"},
          {"field": "q5_services5", "operator": "in",     "value": "מים"}
        ]
      }
    ]
  }

JotForm question format (from /form/{id}/questions):
  {
    "1": {
      "name":     "q1_cityName1",
      "text":     "שם הישוב",
      "type":     "control_textbox",
      "required": "No",
      "order":    "1"
    }
  }

Question types mapping:
  control_textbox   → text
  control_phone     → phone
  control_email     → email
  control_datetime  → date
  control_fileupload→ file
  control_signature → signature
  control_checkbox  → multi
  control_radio     → select
  control_dropdown  → select
  control_number    → text
  control_payment   → payment
"""
from __future__ import annotations

import logging
from typing import Any

from app.pipeline.conditional_logic import Condition, ConditionalRule, Op

logger = logging.getLogger("jotform.converter")

# ── JotForm type → internal type ──────────────────────────────────────────────

JOTFORM_TYPE_MAP = {
    "control_textbox":    "text",
    "control_fullname":   "text",
    "control_phone":      "phone",
    "control_email":      "email",
    "control_datetime":   "date",
    "control_date":       "date",
    "control_fileupload": "file",
    "control_signature":  "signature",
    "control_checkbox":   "multi",
    "control_radio":      "select",
    "control_dropdown":   "select",
    "control_number":     "text",
    "control_payment":    "payment",
    "control_textarea":   "text",
    "control_widget":     "text",
    "control_button":     None,     # skip buttons
    "control_pagebreak":  None,
    "control_head":       None,
    "control_text":       None,
}

# ── JotForm operator → internal Op ───────────────────────────────────────────

JOTFORM_OP_MAP = {
    "equals":        Op.EQUALS,
    "notEqual":      Op.NOT_EQUALS,
    "contains":      Op.CONTAINS,
    "notContain":    Op.NOT_CONTAINS,
    "isEmpty":       Op.IS_EMPTY,
    "isNotEmpty":    Op.NOT_EMPTY,
    "in":            Op.CONTAINS,    # treat "in" as contains for multi-select
}


# ── Section guesser ───────────────────────────────────────────────────────────
# JotForm doesn't have sections — we infer them from question text keywords.
# This is a best-effort heuristic. Override in YAML after discovery.

_SECTION_KEYWORDS = {
    "basic":    ["עיר", "שירות", "מעבר", "תאריך", "כניסה", "יציאה", "סוג"],
    "customer": ["שוכר", "דייר נכנס", "פרטי מגיש", "מגיש"],
    "partner":  ["שותף", "בן זוג", "שוכר שני", "דייר שני"],
    "outgoing": ["יוצא", "עוזב"],
    "landlord": ["בעל הבית", "בעלים", "משכיר"],
    "property": ["כתובת", "רחוב", "דירה", "קומה", "בניין", "כניסה"],
    "arnona":   ["ארנונה", "חשבון עירייה"],
    "water":    ["מים", "ועד בית"],
    "documents":["צילום", "חוזה", "חתימה", "אישור", "תעודה", "תמונה"],
    "payment":  ["תשלום", "מחיר", "עלות"],
    "system":   ["מזכ", "MZK", "מזהה", "קוד", "מספר פנייה"],
}


def _guess_section(text: str, name: str) -> str:
    combined = (text + " " + name).lower()
    for section, keywords in _SECTION_KEYWORDS.items():
        if any(k.lower() in combined for k in keywords):
            return section
    return "other"


# ── Public converters ─────────────────────────────────────────────────────────

def convert_questions(questions_raw: dict | list) -> list[dict[str, Any]]:
    """
    Convert JotForm /questions response to a flat list of field definitions.

    Returns:
      [{"field_id": "q1_name1", "label": "...", "section": "...",
        "type": "...", "required": bool, "order": int}, ...]
    """
    # JotForm returns either a dict keyed by qid or a list
    if isinstance(questions_raw, dict):
        items = list(questions_raw.values())
    else:
        items = list(questions_raw)

    fields = []
    for q in items:
        if not isinstance(q, dict):
            continue
        jf_type = q.get("type", "")
        internal_type = JOTFORM_TYPE_MAP.get(jf_type)
        if internal_type is None:
            continue   # skip layout-only elements

        name     = q.get("name", "")
        text     = q.get("text", name)
        required = str(q.get("required", "No")).lower() in ("yes", "1", "true")

        fields.append({
            "field_id":     name,
            "label":        text,
            "label_clean":  _clean_label(text),
            "section":      _guess_section(text, name),
            "type":         internal_type,
            "jotform_type": jf_type,
            "required":     required,
            "order":        int(q.get("order", 999)),
        })

    fields.sort(key=lambda f: f["order"])
    logger.info("Converted %d question fields", len(fields))
    return fields


def convert_conditions(properties_raw: dict | list) -> list[ConditionalRule]:
    """
    Convert JotForm conditions to ConditionalRule objects.

    JotForm stores conditions in properties["conditions"] as a list.
    Each condition can have multiple filters joined by AND/OR.
    """
    # Extract conditions list
    if isinstance(properties_raw, dict):
        conditions_list = properties_raw.get("conditions", [])
        if isinstance(conditions_list, dict):
            conditions_list = list(conditions_list.values())
    elif isinstance(properties_raw, list):
        conditions_list = properties_raw
    else:
        return []

    rules: list[ConditionalRule] = []
    skipped = 0

    for raw in conditions_list:
        if not isinstance(raw, dict):
            continue

        action = str(raw.get("action", "")).lower()
        if action not in ("hide", "show"):
            skipped += 1
            continue  # skip sendEmail, calculate etc. for now

        target_field = raw.get("field", "")
        if not target_field:
            continue

        filters = raw.get("filters", [])
        if not filters:
            continue

        # Convert filters to Conditions
        conditions: list[Condition] = []
        for f in (filters if isinstance(filters, list) else list(filters.values())):
            jf_op   = f.get("operator", "equals")
            op      = JOTFORM_OP_MAP.get(jf_op, Op.EQUALS)
            c_field = f.get("field", "")
            c_value = f.get("value", "")

            # We use field name (e.g. "q4_cityName4") as label for now
            # This gets resolved against the field map after conversion
            conditions.append(Condition(
                field    = c_field,   # JotForm field name
                section  = "_jotform_raw",  # resolved later
                operator = op,
                value    = c_value,
            ))

        if not conditions:
            continue

        # JotForm "link" = how THIS rule connects to the NEXT one (not within filters)
        # Within a single rule, all filters are AND-ed by JotForm default
        logic = "all"

        rule = ConditionalRule(
            note       = f"JotForm rule: {action} {target_field}",
            logic      = logic,
            conditions = conditions,
            action     = action,
            targets    = [target_field],
        )
        rules.append(rule)

    logger.info(
        "Converted %d conditional rules (%d non-show/hide skipped)",
        len(rules), skipped,
    )
    return rules


def build_field_map_yaml(fields: list[dict]) -> str:
    """
    Generate a YAML-ready field map from converted questions.
    Operator pastes this into the service YAML to finalize section assignments.
    """
    lines = ["fields:"]
    for f in fields:
        req = "always" if f["required"] else "never"
        lines.append(f"  - jotform_id: {f['field_id']}")
        lines.append(f"    label: \"{f['label_clean']}\"")
        lines.append(f"    section: {f['section']}   # TODO: verify")
        lines.append(f"    type: {f['type']}")
        lines.append(f"    required: {req}")
        lines.append("")
    return "\n".join(lines)


def _clean_label(text: str) -> str:
    """Strip HTML tags and normalise label text."""
    import re
    text = re.sub(r"<[^>]+>", "", text)
    return " ".join(text.strip().split())
