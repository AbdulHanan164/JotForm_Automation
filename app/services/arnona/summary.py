"""
Arnona transfer — business summary builder.

Produces the same structure as the client demonstrated in the Claude chat:
  - Transaction type
  - Property details
  - Dates
  - Main tenant
  - Partner (if present)
  - Outgoing tenant (if present)
  - Landlord
  - Arnona account numbers
  - Uploaded documents

All keys are in Hebrew.  No JotForm field IDs, no base64, no raw envelope.
"""
from __future__ import annotations

from typing import Any


def _get(d: dict, *keys: str, default: str = "") -> str:
    """Safe nested get that always returns a string."""
    for key in keys:
        val = d.get(key, "")
        if val:
            if isinstance(val, bool):
                return "כן" if val else "לא"
            if isinstance(val, dict):
                # File/signature: return URL or placeholder
                return val.get("url", val.get("placeholder", "✅" if val.get("present") else ""))
            if isinstance(val, list):
                return ", ".join(str(v) for v in val if v)
            return str(val).strip()
    return default


def _has_value(d: dict, *keys: str) -> bool:
    return bool(_get(d, *keys))


def _full_name(section: dict) -> str:
    first = _get(section, "שם_פרטי")
    last  = _get(section, "שם_משפחה")
    if first and last:
        return f"{first} {last}"
    return first or last or ""


def _doc_status(docs: dict, label: str) -> str:
    """Return ✅ if document is present, ❌ if not."""
    val = docs.get(label)
    if val is None:
        return "❌"
    if isinstance(val, bool):
        return "✅" if val else "❌"
    if isinstance(val, dict):
        return "✅" if (val.get("present") or val.get("url")) else "❌"
    return "✅" if str(val).strip() else "❌"


def build(parsed: dict[str, Any]) -> dict[str, Any]:
    """
    Build a clean Hebrew business summary from the parsed submission.
    This is the operator-facing document.
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

    city     = _get(basic, "עיר")
    services = _get(basic, "שירותים_נבחרים")
    amount   = _get(payment, "סכום")

    # ── Property Address ──────────────────────────────────────────────────────
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

    # ── Build sections ────────────────────────────────────────────────────────
    summary: dict[str, Any] = {}

    # Transaction
    summary["סוג_עסקה"] = {
        "שירות":        services or "—",
        "עיר":          city or "—",
        "סוג_מעבר":     _get(basic, "סוג_מעבר") or "—",
        "סוג_לקוח":     _get(basic, "סוג_לקוח") or "פרטי",
        "תשלום_בוצע":   f"{amount} ₪ ✅" if amount else "—",
    }

    # Property
    summary["פרטי_נכס"] = {
        "כתובת":    address or "—",
        "עיר":      city or "—",
        "רחוב":     street or "—",
        "דירה":     apartment or "—",
        "קומה":     floor or "—",
        "כניסה":    entrance or "—",
    }

    # Dates
    summary["תאריכים"] = {
        "כניסה":      _get(basic, "תאריך_כניסה") or "—",
        "יציאה":      _get(basic, "תאריך_יציאה") or "—",
        "סיום_חוזה":  _get(basic, "תאריך_סיום_חוזה") or "—",
        "תאריך_העברה":_get(basic, "תאריך_העברה") or "—",
    }

    # Main tenant
    customer_name = _full_name(customer)
    summary["דייר_נכנס"] = {
        "שם":          customer_name or "—",
        "טלפון":       _get(customer, "טלפון") or "—",
        "אימייל":      _get(customer, "אימייל") or "—",
        "תעודת_זהות":  _get(customer, "תעודת_זהות") or "—",
    }

    # Partner (only if present)
    partner_name = _full_name(partner)
    if partner_name or _has_value(partner, "טלפון"):
        summary["שוכר_שני"] = {
            "שם":          partner_name or "—",
            "טלפון":       _get(partner, "טלפון") or "—",
            "אימייל":      _get(partner, "אימייל") or "—",
            "תעודת_זהות":  _get(partner, "תעודת_זהות") or "—",
        }

    # Outgoing tenant (only if present)
    outgoing_name = _full_name(outgoing)
    if outgoing_name or _has_value(outgoing, "טלפון", "תעודת_זהות"):
        summary["דייר_יוצא"] = {
            "שם":          outgoing_name or "—",
            "טלפון":       _get(outgoing, "טלפון") or "—",
            "אימייל":      _get(outgoing, "אימייל") or "—",
            "תעודת_זהות":  _get(outgoing, "תעודת_זהות") or "—",
        }

    # Landlord
    landlord_name = _full_name(landlord) or _get(landlord, "שם_מלא")
    if landlord_name or _has_value(landlord, "טלפון"):
        summary["בעל_הבית"] = {
            "שם":          landlord_name or "—",
            "טלפון":       _get(landlord, "טלפון") or "—",
            "אימייל":      _get(landlord, "אימייל") or "—",
            "תעודת_זהות":  _get(landlord, "תעודת_זהות") or "—",
        }

    # Arnona numbers (only relevant ones)
    arnona_section: dict[str, str] = {}
    if _has_value(arnona, "מספר_נכס"):
        arnona_section["מספר_נכס"] = _get(arnona, "מספר_נכס")
    if _has_value(arnona, "מספר_לקוח"):
        arnona_section["מספר_לקוח"] = _get(arnona, "מספר_לקוח")
    if _has_value(arnona, "מספר_זיהוי_נכס"):
        arnona_section["מספר_זיהוי_נכס"] = _get(arnona, "מספר_זיהוי_נכס")
    if arnona_section:
        summary["חשבון_ארנונה"] = arnona_section

    # Water numbers (only if present)
    water_section: dict[str, str] = {}
    if _has_value(water, "מספר_נכס"):
        water_section["מספר_נכס"] = _get(water, "מספר_נכס")
    if _has_value(water, "מספר_לקוח"):
        water_section["מספר_לקוח"] = _get(water, "מספר_לקוח")
    if water_section:
        summary["חשבון_מים"] = water_section

    # Documents status
    summary["מסמכים"] = {
        "תעודת_זהות":   _doc_status(docs, "תעודת_זהות"),
        "חוזה_שכירות":  _doc_status(docs, "חוזה_שכירות"),
        "חתימה":        _doc_status(docs, "חתימה"),
        "חשבון_ארנונה": _doc_status(docs, "חשבון_ארנונה"),
    }
    if parsed.get("basic", {}).get("סוג_לקוח", "") in ("חברה", "תאגיד"):
        summary["מסמכים"]["תעודת_התאגדות"] = _doc_status(docs, "תעודת_התאגדות")
        summary["מסמכים"]["נסח_טאבו"]      = _doc_status(docs, "נסח_טאבו")

    # Internal reference (for operators only)
    mzk_id = _get(system, "מזהה_מזכ")
    if mzk_id:
        summary["מידע_פנימי"] = {
            "מספר_פנייה":  mzk_id,
            "מזהה_החזר":   _get(system, "מזהה_החזר") or "—",
        }

    return summary
