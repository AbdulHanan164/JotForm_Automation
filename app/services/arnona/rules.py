"""
Business rules for the arnona transfer service.

Rules are data — each rule is a dict with:
  id          — unique identifier
  label       — human-readable Hebrew label (shown in output/emails)
  section     — which section of the parsed data to check
  check       — callable(parsed) → bool: True = field is present/valid
  required    — callable(parsed) → bool: True = this rule must pass
  reason      — callable(parsed) → str: why it's required (for email)

v0.6 CHANGE: Removed _arnona_field_hidden() which depended on the removed
CITY_HIDDEN_FIELDS dict. The conditional logic engine (ConditionalLogicEngine)
is now the single source of truth for which fields are hidden.

The orchestrator calls detect_missing(parsed, summary, visibility) where
visibility is pre-computed by the engine. Rules no longer need to duplicate
the city/service logic — they just check required() and the orchestrator
skips any field whose visibility[label] == False.
"""
from __future__ import annotations

from typing import Any


def _has(parsed: dict, section: str, label: str) -> bool:
    """True if section.label exists and is non-empty / truthy."""
    val = parsed.get(section, {}).get(label)
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    if isinstance(val, dict):
        return val.get("present", False) or bool(val.get("url", "")) or bool(val.get("local_path", ""))
    if isinstance(val, list):
        return len(val) > 0
    return bool(str(val).strip())


def _city(parsed: dict) -> str:
    return str(parsed.get("basic", {}).get("עיר", "")).strip()


def _services(parsed: dict) -> list[str]:
    svcs = parsed.get("basic", {}).get("שירותים_נבחרים", [])
    if isinstance(svcs, str):
        return [s.strip() for s in svcs.split(",")]
    return [str(s).strip() for s in svcs]


def _has_service(parsed: dict, keyword: str) -> bool:
    return any(keyword in s for s in _services(parsed))


def _is_company(parsed: dict) -> bool:
    ptype = str(parsed.get("basic", {}).get("סוג_לקוח", "")).lower()
    return "חברה" in ptype or "עסק" in ptype or "תאגיד" in ptype


def _has_outgoing_tenant(parsed: dict) -> bool:
    return (
        _has(parsed, "outgoing", "שם_פרטי") or
        _has(parsed, "outgoing", "תעודת_זהות") or
        _has(parsed, "outgoing", "טלפון")
    )


def _has_partner(parsed: dict) -> bool:
    return (
        _has(parsed, "partner", "שם_פרטי") or
        _has(parsed, "partner", "תעודת_זהות") or
        _has(parsed, "partner", "טלפון")
    )


# ── Rule definitions ──────────────────────────────────────────────────────────
# NOTE: Fields hidden by conditional logic are filtered out by the orchestrator
# BEFORE these rules run (via the visibility dict). So rules here only need
# to express BUSINESS logic (is this field required given what was filled in?),
# not JotForm UI logic (is the field shown?). Keep them separate.

INFO_RULES: list[dict[str, Any]] = [

    # ── Basic / Transaction ───────────────────────────────────────────────────
    {
        "id":       "city",
        "label":    "עיר",
        "section":  "basic",
        "check":    lambda p: _has(p, "basic", "עיר"),
        "required": lambda p: True,
        "reason":   lambda p: "נדרש לצורך קביעת שדות הארנונה הרלוונטיים",
    },
    {
        "id":       "move_in_date",
        "label":    "תאריך_כניסה",
        "section":  "basic",
        "check":    lambda p: _has(p, "basic", "תאריך_כניסה"),
        "required": lambda p: True,
        "reason":   lambda p: "נדרש לצורך עיבוד ההעברה",
    },
    {
        "id":       "services_selected",
        "label":    "שירותים_נבחרים",
        "section":  "basic",
        "check":    lambda p: len(_services(p)) > 0,
        "required": lambda p: True,
        "reason":   lambda p: "לא נבחר אף שירות להעברה",
    },

    # ── Main Customer ─────────────────────────────────────────────────────────
    {
        "id":       "customer_name",
        "label":    "שם הדייר הנכנס",
        "section":  "customer",
        "check":    lambda p: _has(p, "customer", "שם_פרטי") and _has(p, "customer", "שם_משפחה"),
        "required": lambda p: True,
        "reason":   lambda p: "נדרש לפתיחת תיק",
    },
    {
        "id":       "customer_phone",
        "label":    "טלפון",
        "section":  "customer",
        "check":    lambda p: _has(p, "customer", "טלפון"),
        "required": lambda p: True,
        "reason":   lambda p: "נדרש ליצירת קשר",
    },
    {
        "id":       "customer_email",
        "label":    "אימייל",
        "section":  "customer",
        "check":    lambda p: _has(p, "customer", "אימייל"),
        "required": lambda p: True,
        "reason":   lambda p: "נדרש לשליחת אישורים",
    },
    {
        "id":       "customer_id",
        "label":    "תעודת_זהות",
        "section":  "customer",
        "check":    lambda p: _has(p, "customer", "תעודת_זהות"),
        "required": lambda p: not _is_company(p),
        "reason":   lambda p: "נדרש לרישום מול הרשויות",
    },

    # ── Partner (conditional) ─────────────────────────────────────────────────
    {
        "id":       "partner_id",
        "label":    "תעודת_זהות (שוכר שני)",
        "section":  "partner",
        "check":    lambda p: _has(p, "partner", "תעודת_זהות"),
        "required": lambda p: _has_partner(p),
        "reason":   lambda p: "שוכר שני מופיע בטופס — נדרשת ת.ז",
    },

    # ── Outgoing Tenant (conditional) ─────────────────────────────────────────
    {
        "id":       "outgoing_id",
        "label":    "תעודת_זהות (דייר יוצא)",
        "section":  "outgoing",
        "check":    lambda p: _has(p, "outgoing", "תעודת_זהות"),
        "required": lambda p: _has_outgoing_tenant(p),
        "reason":   lambda p: "נדרש לביטול החשבון על שם הדייר היוצא",
    },
    {
        "id":       "outgoing_phone",
        "label":    "טלפון (דייר יוצא)",
        "section":  "outgoing",
        "check":    lambda p: _has(p, "outgoing", "טלפון"),
        "required": lambda p: _has_outgoing_tenant(p),
        "reason":   lambda p: "נדרש ליצירת קשר עם הדייר היוצא",
    },

    # ── Property Owner ────────────────────────────────────────────────────────
    {
        "id":       "owner_phone",
        "label":    "טלפון (בעל הבית)",
        "section":  "landlord",
        "check":    lambda p: _has(p, "landlord", "טלפון"),
        "required": lambda p: True,
        "reason":   lambda p: "נדרש לאישור ההעברה מול בעל הבית",
    },

    # ── Arnona Numbers ────────────────────────────────────────────────────────
    # Note: fields hidden by conditional logic (e.g. Ramat Gan) are filtered
    # BEFORE these rules run, via the visibility dict from the engine.
    # No city logic needed here.
    {
        "id":       "arnona_property_number",
        "label":    "מספר_נכס",
        "section":  "arnona",
        "check":    lambda p: _has(p, "arnona", "מספר_נכס"),
        "required": lambda p: _has_service(p, "ארנונה"),
        "reason":   lambda p: "נדרש לרישום חשבון הארנונה",
    },
    {
        "id":       "arnona_customer_number",
        "label":    "מספר_לקוח",
        "section":  "arnona",
        "check":    lambda p: _has(p, "arnona", "מספר_לקוח"),
        "required": lambda p: _has_service(p, "ארנונה"),
        "reason":   lambda p: "מספר לקוח/משלם ארנונה — מופיע בחשבון הארנונה",
    },
    {
        "id":       "arnona_id_number",
        "label":    "מספר_זיהוי_נכס",
        "section":  "arnona",
        "check":    lambda p: _has(p, "arnona", "מספר_זיהוי_נכס"),
        "required": lambda p: _has_service(p, "ארנונה"),
        "reason":   lambda p: "מספר זיהוי הנכס — מופיע בחשבון הארנונה",
    },
]


DOC_RULES: list[dict[str, Any]] = [
    {
        "id":       "id_photo",
        "label":    "תעודת_זהות",
        "section":  "documents",
        "check":    lambda p: _has(p, "documents", "תעודת_זהות"),
        "required": lambda p: not _is_company(p),
        "reason":   lambda p: "נדרש לצורך אימות זהות",
    },
    {
        "id":       "lease_contract",
        "label":    "חוזה_שכירות",
        "section":  "documents",
        "check":    lambda p: _has(p, "documents", "חוזה_שכירות"),
        "required": lambda p: True,
        "reason":   lambda p: "נדרש להוכחת זכאות לדירה",
    },
    {
        "id":       "signature",
        "label":    "חתימה",
        "section":  "documents",
        "check":    lambda p: _has(p, "documents", "חתימה"),
        "required": lambda p: True,
        "reason":   lambda p: "נדרש לאישור הבקשה",
    },
    {
        "id":       "arnona_bill",
        "label":    "חשבון_ארנונה",
        "section":  "documents",
        "check":    lambda p: _has(p, "documents", "חשבון_ארנונה"),
        "required": lambda p: _has_service(p, "ארנונה"),
        "reason":   lambda p: "נדרש לאימות מספר הנכס ופרטי חשבון הארנונה",
    },
    {
        "id":       "corp_cert",
        "label":    "תעודת_התאגדות",
        "section":  "documents",
        "check":    lambda p: _has(p, "documents", "תעודת_התאגדות"),
        "required": lambda p: _is_company(p),
        "reason":   lambda p: "נדרש לאימות חברה",
    },
    {
        "id":       "tabu",
        "label":    "נסח_טאבו",
        "section":  "documents",
        "check":    lambda p: _has(p, "documents", "נסח_טאבו"),
        "required": lambda p: _is_company(p),
        "reason":   lambda p: "נדרש לאימות בעלות",
    },
]
