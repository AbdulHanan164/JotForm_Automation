"""
Arnona transfer — fallback business summary builder.

Used when BusinessSubmission is not available (YAML-driven services, mapper failure).
Produces the SAME fixed-template structure as BusinessSubmission.to_summary_dict():
  - Every section always present
  - Empty fields show "לא סופק" instead of being hidden
  - Consistent layout for all transaction types and flows

Consumer compatibility:
  queue.py       reads "דייר_נכנס"."שם", "פרטי_נכס"."כתובת", "סוג_עסקה"."שירות"
  email_templates reads same keys — all unchanged.
"""
from __future__ import annotations

from typing import Any

_N = "לא סופק"


def _get(d: dict, *keys: str) -> str:
    """Safe nested get that always returns a string."""
    for key in keys:
        val = d.get(key, "")
        if val:
            if isinstance(val, bool):
                return "כן" if val else "לא"
            if isinstance(val, dict):
                return val.get("url", val.get("placeholder", "✅" if val.get("present") else ""))
            if isinstance(val, list):
                return ", ".join(str(v) for v in val if v)
            return str(val).strip()
    return ""


def _v(val: str) -> str:
    """Return value or 'לא סופק' placeholder."""
    return val if val else _N


def _full_name(section: dict) -> str:
    first = _get(section, "שם_פרטי")
    last  = _get(section, "שם_משפחה")
    full  = _get(section, "שם_מלא")
    if first and last:
        return f"{first} {last}"
    return full or first or last or ""


def _doc_status(docs: dict, label: str) -> str:
    """Return ✅ if document is present, ❌ if not."""
    val = docs.get(label)
    if val is None:
        return "❌"
    if isinstance(val, bool):
        return "✅" if val else "❌"
    if isinstance(val, dict):
        return "✅" if (val.get("present") or val.get("url")) else "❌"
    s = str(val).strip()
    return "✅" if (s and s != "❌") else "❌"


def build(parsed: dict[str, Any]) -> dict[str, Any]:
    """
    Build a fixed-template Hebrew summary from the section-keyed parsed dict.
    Every section is always present; empty fields show 'לא סופק'.
    """
    basic    = parsed.get("basic", {})
    customer = parsed.get("customer", {})
    partner  = parsed.get("partner", {})
    outgoing = parsed.get("outgoing", {})
    landlord = parsed.get("landlord", {})
    prop     = parsed.get("property", {})
    arnona   = parsed.get("arnona", {})
    water    = parsed.get("water", {})
    docs     = parsed.get("documents", {})
    payment  = parsed.get("payment", {})
    system   = parsed.get("system", {})

    city      = _get(basic, "עיר")
    services  = _get(basic, "שירותים_נבחרים")
    amount    = _get(payment, "סכום")
    pkg_name  = _get(payment, "שם_שירות")

    # ── Property address ──────────────────────────────────────────────────────
    street    = _get(prop, "רחוב")
    building  = _get(prop, "בניין")
    apartment = _get(prop, "דירה")
    floor     = _get(prop, "קומה")
    entrance  = _get(prop, "כניסה")

    address_parts = [street]
    if building:  address_parts.append(f"בניין {building}")
    if entrance:  address_parts.append(f"כניסה {entrance}")
    if apartment: address_parts.append(f"דירה {apartment}")
    if floor:     address_parts.append(f"קומה {floor}")
    if city:      address_parts.append(city)
    address = ", ".join(p for p in address_parts if p)

    summary: dict[str, Any] = {}

    # ── 1. Transaction type ───────────────────────────────────────────────────
    summary["סוג_עסקה"] = {
        "סוג_עסקה":      _v(_get(system, "סוג_עסקה") or _get(basic, "סוג_מעבר")),
        "שירות":         _v(pkg_name),
        "שירותים":       _v(services),
        "עיר":           _v(city),
        "סוג_לקוח":      _v(_get(basic, "סוג_לקוח")),
        "לאן_מעבירים":   _v(_get(basic, "לאן_להעביר")),
    }

    # ── 2. Property ───────────────────────────────────────────────────────────
    summary["פרטי_נכס"] = {
        "כתובת":  _v(address),
        "עיר":    _v(city),
        "רחוב":   _v(street),
        "בניין":  _v(building),
        "דירה":   _v(apartment),
        "קומה":   _v(floor),
        "כניסה":  _v(entrance),
    }

    # ── 3. Dates ──────────────────────────────────────────────────────────────
    summary["תאריכים"] = {
        "כניסה":         _v(_get(basic, "תאריך_כניסה")),
        "יציאה":         _v(_get(basic, "תאריך_יציאה")),
        "סיום_חוזה":     _v(_get(basic, "תאריך_סיום_חוזה")),
        "תאריך_העברה":   _v(_get(basic, "תאריך_העברה")),
    }

    # ── 4. Incoming tenant — always ───────────────────────────────────────────
    customer_name = _full_name(customer)
    summary["דייר_נכנס"] = {
        "שם":          _v(customer_name),
        "טלפון":       _v(_get(customer, "טלפון")),
        "אימייל":      _v(_get(customer, "אימייל")),
        "תעודת_זהות":  _v(_get(customer, "תעודת_זהות")),
    }

    # ── 5. Second tenant / partner — ALWAYS shown ─────────────────────────────
    summary["שוכר_שני"] = {
        "שם":          _v(_full_name(partner)),
        "טלפון":       _v(_get(partner, "טלפון")),
        "אימייל":      _v(_get(partner, "אימייל")),
        "תעודת_זהות":  _v(_get(partner, "תעודת_זהות")),
    }

    # ── 6. Outgoing tenant — ALWAYS shown ─────────────────────────────────────
    summary["דייר_יוצא"] = {
        "שם":          _v(_full_name(outgoing)),
        "טלפון":       _v(_get(outgoing, "טלפון")),
        "אימייל":      _v(_get(outgoing, "אימייל")),
        "תעודת_זהות":  _v(_get(outgoing, "תעודת_זהות")),
    }

    # ── 7. Landlord — ALWAYS shown ────────────────────────────────────────────
    summary["בעל_הבית"] = {
        "שם":          _v(_full_name(landlord) or _get(landlord, "שם_מלא")),
        "טלפון":       _v(_get(landlord, "טלפון")),
        "אימייל":      _v(_get(landlord, "אימייל")),
        "תעודת_זהות":  _v(_get(landlord, "תעודת_זהות")),
    }

    # ── 8. Arnona account numbers — ALWAYS shown ──────────────────────────────
    summary["חשבון_ארנונה"] = {
        "מספר_נכס":          _v(_get(arnona, "מספר_נכס")),
        "מספר_לקוח":         _v(_get(arnona, "מספר_לקוח")),
        "מספר_זיהוי_נכס":    _v(_get(arnona, "מספר_זיהוי_נכס")),
        "מספר_חשבון_תושב":   _v(_get(arnona, "מספר_חשבון_תושב")),
        "מספר_חשבון_לקוח":   _v(_get(arnona, "מספר_חשבון_לקוח")),
    }

    # ── 9. Water account numbers — ALWAYS shown ───────────────────────────────
    summary["חשבון_מים"] = {
        "מספר_נכס":   _v(_get(water, "מספר_נכס")),
        "מספר_לקוח":  _v(_get(water, "מספר_לקוח")),
    }

    # ── 10. Electricity — ALWAYS shown (no form fields yet) ──────────────────
    summary["חשבון_חשמל"] = {
        "מספר_נכס":   _N,
        "מספר_לקוח":  _N,
    }

    # ── 11. Documents — ALWAYS shown, all 6 types ────────────────────────────
    summary["מסמכים"] = {
        "תעודת_זהות":       _doc_status(docs, "תעודת_זהות"),
        "חוזה_שכירות":      _doc_status(docs, "חוזה_שכירות"),
        "חתימה":             _doc_status(docs, "חתימה"),
        "חשבון_ארנונה":      _doc_status(docs, "חשבון_ארנונה"),
        "תעודת_התאגדות":     _doc_status(docs, "תעודת_התאגדות"),
        "נסח_טאבו":          _doc_status(docs, "נסח_טאבו"),
    }

    # ── 12. Payment — ALWAYS shown ────────────────────────────────────────────
    amount_str  = f"{amount} ₪" if amount else _N
    paid_status = "שולם ✅" if amount else "לא שולם"
    summary["פרטי_תשלום"] = {
        "שירות":          _v(pkg_name),
        "סכום":           amount_str,
        "סטטוס_תשלום":    paid_status,
    }

    # ── 13. Internal reference — ALWAYS shown ────────────────────────────────
    mzk_id     = _get(system, "מזהה_מזכ")
    refund_id  = _get(system, "מזהה_החזר")
    summary["מידע_פנימי"] = {
        "מספר_פנייה":  mzk_id   or _N,
        "מזהה_החזר":   refund_id or _N,
    }

    return summary
