"""
Business rules for the arnona transfer service.

Rules are data — each rule is a dict with:
  id          — unique identifier
  label       — human-readable Hebrew label (shown in output/emails)
  section     — which section of the parsed data to check
  check       — callable(parsed) → bool: True = field is present/valid
  required    — callable(parsed) → bool: True = this rule must pass
  reason      — callable(parsed) → str: why it's required (for email)

The engine iterates rules, evaluates check() and required() independently,
then builds the missing_info / missing_docs lists.

CITY-AWARE RULES:
  Some fields are hidden by JotForm conditional logic for certain cities.
  The required() lambda returns False for those combinations, so they
  never appear as "missing" even when the field is empty.
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
        # File/signature field: check 'present' key
        return val.get("present", False) or bool(val.get("url", ""))
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
    """True if the applicant is a company, not a private person."""
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


def _arnona_field_hidden(parsed: dict, field_label: str) -> bool:
    """
    Returns True if this arnona field is hidden by JotForm conditional logic
    (i.e. it was never shown to the user, so we must NOT flag it as missing).
    """
    from app.services.arnona.field_map import CITY_HIDDEN_FIELDS
    city = _city(parsed)
    hidden = CITY_HIDDEN_FIELDS.get(city, {})
    if _has_service(parsed, "ארנונה"):
        if field_label in hidden.get("ארנונה", []):
            return True
    if _has_service(parsed, "מים"):
        if field_label in hidden.get("מים", []):
            return True
    return False


# ── Rule definitions ──────────────────────────────────────────────────────────

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
        "label":    "תאריך כניסה",
        "section":  "basic",
        "check":    lambda p: _has(p, "basic", "תאריך_כניסה"),
        "required": lambda p: True,
        "reason":   lambda p: "נדרש לצורך עיבוד ההעברה",
    },
    {
        "id":       "services_selected",
        "label":    "שירותים לטיפול",
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
        "label":    "טלפון דייר נכנס",
        "section":  "customer",
        "check":    lambda p: _has(p, "customer", "טלפון"),
        "required": lambda p: True,
        "reason":   lambda p: "נדרש ליצירת קשר",
    },
    {
        "id":       "customer_email",
        "label":    "אימייל דייר נכנס",
        "section":  "customer",
        "check":    lambda p: _has(p, "customer", "אימייל"),
        "required": lambda p: True,
        "reason":   lambda p: "נדרש לשליחת אישורים",
    },
    {
        "id":       "customer_id",
        "label":    "ת.ז דייר נכנס",
        "section":  "customer",
        "check":    lambda p: _has(p, "customer", "תעודת_זהות"),
        "required": lambda p: not _is_company(p),
        "reason":   lambda p: "נדרש לרישום מול הרשויות",
    },

    # ── Partner (conditional) ─────────────────────────────────────────────────
    {
        "id":       "partner_id",
        "label":    "ת.ז שוכר שני",
        "section":  "partner",
        "check":    lambda p: _has(p, "partner", "תעודת_זהות"),
        "required": lambda p: _has_partner(p),
        "reason":   lambda p: "שוכר שני מופיע בטופס — נדרשת ת.ז",
    },

    # ── Outgoing Tenant (conditional) ─────────────────────────────────────────
    {
        "id":       "outgoing_id",
        "label":    "ת.ז דייר יוצא",
        "section":  "outgoing",
        "check":    lambda p: _has(p, "outgoing", "תעודת_זהות"),
        "required": lambda p: _has_outgoing_tenant(p),
        "reason":   lambda p: "נדרש לביטול החשבון על שם הדייר היוצא",
    },
    {
        "id":       "outgoing_phone",
        "label":    "טלפון דייר יוצא",
        "section":  "outgoing",
        "check":    lambda p: _has(p, "outgoing", "טלפון"),
        "required": lambda p: _has_outgoing_tenant(p),
        "reason":   lambda p: "נדרש ליצירת קשר עם הדייר היוצא",
    },

    # ── Property Owner ────────────────────────────────────────────────────────
    {
        "id":       "owner_phone",
        "label":    "טלפון בעל הבית",
        "section":  "landlord",
        "check":    lambda p: _has(p, "landlord", "טלפון"),
        "required": lambda p: True,
        "reason":   lambda p: "נדרש לאישור ההעברה מול בעל הבית",
    },

    # ── Arnona Numbers ────────────────────────────────────────────────────────
    {
        "id":       "arnona_property_number",
        "label":    "מספר נכס ארנונה",
        "section":  "arnona",
        "check":    lambda p: _has(p, "arnona", "מספר_נכס"),
        "required": lambda p: (
            _has_service(p, "ארנונה") and
            not _arnona_field_hidden(p, "מספר_נכס")  # always shown
        ),
        "reason":   lambda p: "נדרש לרישום חשבון הארנונה — ניתן למצוא בחשבון הארנונה של הנכס",
    },
    {
        "id":       "arnona_customer_number",
        "label":    "מספר לקוח ארנונה",
        "section":  "arnona",
        "check":    lambda p: _has(p, "arnona", "מספר_לקוח"),
        "required": lambda p: (
            _has_service(p, "ארנונה") and
            not _arnona_field_hidden(p, "מספר_לקוח")
        ),
        "reason":   lambda p: "מספר לקוח/משלם ארנונה — מופיע בחשבון הארנונה",
    },
    {
        "id":       "arnona_id_number",
        "label":    "מספר זיהוי נכס ארנונה",
        "section":  "arnona",
        "check":    lambda p: _has(p, "arnona", "מספר_זיהוי_נכס"),
        "required": lambda p: (
            _has_service(p, "ארנונה") and
            not _arnona_field_hidden(p, "מספר_זיהוי_נכס")
        ),
        "reason":   lambda p: "מספר זיהוי הנכס — מופיע בחשבון הארנונה",
    },
]


DOC_RULES: list[dict[str, Any]] = [
    {
        "id":       "id_photo",
        "label":    "צילום תעודת זהות",
        "section":  "documents",
        "check":    lambda p: _has(p, "documents", "תעודת_זהות"),
        "required": lambda p: not _is_company(p),
        "reason":   lambda p: "נדרש לצורך אימות זהות",
    },
    {
        "id":       "lease_contract",
        "label":    "חוזה שכירות",
        "section":  "documents",
        "check":    lambda p: _has(p, "documents", "חוזה_שכירות"),
        "required": lambda p: True,
        "reason":   lambda p: "נדרש להוכחת זכאות לדירה",
    },
    {
        "id":       "signature",
        "label":    "חתימה דיגיטלית",
        "section":  "documents",
        "check":    lambda p: _has(p, "documents", "חתימה"),
        "required": lambda p: True,
        "reason":   lambda p: "נדרש לאישור הבקשה",
    },
    {
        "id":       "arnona_bill",
        "label":    "צילום חשבון ארנונה",
        "section":  "documents",
        "check":    lambda p: _has(p, "documents", "חשבון_ארנונה"),
        "required": lambda p: (
            _has_service(p, "ארנונה") and
            not _arnona_field_hidden(p, "מספר_נכס")
        ),
        "reason":   lambda p: "נדרש לאימות מספר הנכס ופרטי חשבון הארנונה",
    },
    {
        "id":       "corp_cert",
        "label":    "תעודת התאגדות",
        "section":  "documents",
        "check":    lambda p: _has(p, "documents", "תעודת_התאגדות"),
        "required": lambda p: _is_company(p),
        "reason":   lambda p: "נדרש לאימות חברה",
    },
    {
        "id":       "tabu",
        "label":    "נסח טאבו",
        "section":  "documents",
        "check":    lambda p: _has(p, "documents", "נסח_טאבו"),
        "required": lambda p: _is_company(p),
        "reason":   lambda p: "נדרש לאימות בעלות",
    },
]
