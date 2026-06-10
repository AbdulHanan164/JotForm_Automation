"""
Arnona transfer — operator summary builders.

Two-layer design:

  Layer A — executive operator summary (30-second read).
    • Only relevant sections shown (unordered services hidden entirely).
    • Empty fields omitted — no "לא סופק" rows.
    • Missing items and validation warnings surfaced inline on the field.
    • Ends with a single operator recommendation.
    • Built from: BusinessSubmission + missing_info + missing_docs + validation_issues.

  Layer B — detailed submission record.
    • All account numbers, full contact data, payment details.
    • Internal references (MZK ref, refund ID).
    • Everything needed to actually process the submission.
    • Built from: BusinessSubmission.

  Legacy build() — backward-compatible fallback.
    • Used by YAML-driven services that don't produce a BusinessSubmission.
    • Consumed by email_templates.py and queue.py.
    • Unchanged — do not modify.
"""
from __future__ import annotations

from typing import Any

_N = "לא סופק"


# ─────────────────────────────────────────────────────────────────────────────
# Layer A — executive operator summary
# ─────────────────────────────────────────────────────────────────────────────

def build_layer_a(
    bs: Any,                        # BusinessSubmission
    missing_info: list[dict],
    missing_docs: list[dict],
    validation_issues: list[dict],
) -> dict[str, Any]:
    """
    Build Layer A: the 30-second operator decision summary.

    Rules:
      - Show only sections for services that were actually ordered.
      - Omit empty fields — no "לא סופק" placeholder rows.
      - Append " ⚠️ חסר" inline when a field is in the missing list.
      - Append " ⚠️" inline when a validation rule fired on a field.
      - Partner section collapses to one line when no partner exists.
      - Outgoing tenant + landlord share one section.
      - Recommendation is the last field — one action sentence.
    """
    from app.mappers.models import Documents

    # ── Lookup sets ──────────────────────────────────────────────────────────
    missing_ids: set[str] = (
        {item["id"] for item in (missing_info or [])}
        | {item["id"] for item in (missing_docs or [])}
    )
    validation_map: dict[str, str] = {
        issue["id"]: issue.get("label", "")
        for issue in (validation_issues or [])
    }

    # ── Service detection ────────────────────────────────────────────────────
    services: list[str] = bs.submission.services_selected or []
    _svc = " ".join(s.lower() for s in services)

    def _has_svc(*keywords: str) -> bool:
        return any(kw in _svc for kw in keywords)

    has_arnona      = _has_svc("ארנונה", "arnona", "municipality")
    has_water       = _has_svc("מים", "water")
    has_electricity = _has_svc("חשמל", "electricity")
    has_gas         = _has_svc("גז", "gas")
    has_committee   = _has_svc("ועד", "committee")

    # ── Field helpers ─────────────────────────────────────────────────────────

    def _f(label: str, value: str, missing_id: str = "") -> str | None:
        """Format 'label: value'. Shows '⚠️ חסר' if field is missing. Omits when empty."""
        if missing_id and missing_id in missing_ids:
            return f"{label}: חסר ⚠️"
        if value:
            return f"{label}: {value}"
        return None

    def _fv(label: str, value: str, missing_id: str = "",
            warn_id: str = "") -> str | None:
        """Like _f but also appends ⚠️ when a validation rule fired on this field."""
        if missing_id and missing_id in missing_ids:
            return f"{label}: חסר ⚠️"
        if value:
            if warn_id and warn_id in validation_map:
                return f"{label}: {value} ⚠️"
            return f"{label}: {value}"
        return None

    def _collect(*args: str | None) -> list[str]:
        return [a for a in args if a]

    # ── Duration calculation ──────────────────────────────────────────────────

    def _duration(start: str, end: str) -> str:
        if not start or not end:
            return ""
        from datetime import datetime
        for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
            try:
                d1 = datetime.strptime(start, fmt)
                d2 = datetime.strptime(end,   fmt)
                days = (d2 - d1).days
                return str(abs(days)) if days != 0 else ""
            except ValueError:
                continue
        return ""

    # ─── 1. Transaction block ────────────────────────────────────────────────
    inc         = bs.incoming_tenant
    client_type = "חברה" if inc.is_company else "אדם פרטי"
    tx_type     = bs.submission.transaction_type or ""

    tx_parts = [p for p in [tx_type, client_type] if p]
    tx_line  = ", ".join(tx_parts)

    svc_inline: list[str] = []
    if has_arnona:      svc_inline.append("ארנונה IN")
    if has_water:       svc_inline.append("מים IN")
    if has_electricity: svc_inline.append("חשמל IN")
    if has_gas:         svc_inline.append("גז IN")
    if has_committee:   svc_inline.append("ועד בית IN")
    if not svc_inline and services:
        svc_inline = [s + " IN" for s in services]

    services_line = "שירותים: " + " + ".join(svc_inline) if svc_inline else None

    if bs.submission.amount_paid:
        amt          = f"{bs.submission.amount_paid:.0f} ₪"
        payment_line = f"תשלום: {amt}  ✅ שולם"
    else:
        payment_line = "תשלום: ❌ לא שולם"

    tx_section = {
        "id":      "transaction",
        "heading": "סוג העסקה",
        "lines":   _collect(tx_line, services_line, payment_line),
    }

    # ─── 2. Property ─────────────────────────────────────────────────────────
    prop    = bs.property
    address = prop.full_address

    if not address:
        parts = [prop.street,
                 f"בניין {prop.building}" if prop.building else None,
                 f"דירה {prop.apartment}" if prop.apartment else None,
                 prop.city]
        address = ", ".join(p for p in parts if p)

    prop_section = {
        "id":      "property",
        "heading": "פרטי הנכס",
        "lines":   _collect(address),
    }

    # ─── 3. Dates ─────────────────────────────────────────────────────────────
    date_lines: list[str] = []

    if bs.dates.move_in:
        date_lines.append(f"כניסה: {bs.dates.move_in}")

    if bs.dates.lease_end:
        date_lines.append(f"סיום שכירות: {bs.dates.lease_end}")
        dur = _duration(bs.dates.move_in, bs.dates.lease_end)
        if dur:
            date_lines.append(f"אורך השכירות: {dur} ימים")

    if bs.dates.move_out:
        date_lines.append(f"תאריך יציאה: {bs.dates.move_out}")

    if bs.dates.transfer_date and bs.dates.transfer_date != bs.dates.move_in:
        date_lines.append(f"תאריך מעבר: {bs.dates.transfer_date}")

    date_section = {
        "id":      "dates",
        "heading": "תאריכים",
        "lines":   date_lines,
    }

    # ─── 4. Incoming tenant ───────────────────────────────────────────────────
    if inc.is_company:
        id_line = _fv("ח.פ",     inc.company_reg  or inc.id_number, "customer_id")
        nm_line = _f("שם חברה",  inc.company_name or inc.full_name, "customer_name")
    else:
        id_line = _fv("ת.ז",     inc.id_number, "customer_id",
                      warn_id="duplicate_tenant_id")
        nm_line = _f("שם",       inc.full_name,  "customer_name")

    inc_section = {
        "id":      "incoming_tenant",
        "heading": "דייר נכנס",
        "lines":   _collect(
            nm_line,
            id_line,
            _f("טלפון",  inc.phone, "customer_phone"),
            _f("אימייל", inc.email, "customer_email"),
        ),
    }

    # ─── 5. Partner ───────────────────────────────────────────────────────────
    par = bs.partner
    if par and (par.full_name or par.phone):
        par_id_line = _fv("ת.ז", par.id_number, "partner_id",
                          warn_id="partner_phone_no_id")
        partner_section = {
            "id":      "partner",
            "heading": "שותף",
            "lines":   _collect(
                _f("שם",     par.full_name),
                par_id_line,
                _f("טלפון",  par.phone),
                _f("אימייל", par.email),
            ),
        }
    else:
        partner_section = {
            "id":      "partner",
            "heading": "שותף",
            "lines":   ["אין"],
        }

    # ─── 6. Outgoing tenant / Landlord (combined) ─────────────────────────────
    combined_lines: list[str] = []
    out = bs.outgoing_tenant
    ll  = bs.landlord

    out_present = out and (out.full_name or out.phone or out.id_number)
    ll_present  = ll  and (ll.full_name  or ll.phone)

    if out_present:
        email_line: str | None
        if out.email and "outgoing_email_is_text_none" in validation_map:
            email_line = f"אימייל: {out.email} ⚠️ (נראה לא תקין)"
        else:
            email_line = _f("אימייל", out.email)

        combined_lines.extend(_collect(
            _f("שם",    out.full_name),
            _fv("ת.ז",  out.id_number, "outgoing_id",
                warn_id="landlord_is_outgoing_tenant"),
            _f("טלפון", out.phone,     "outgoing_phone"),
            email_line,
        ))

    if out_present and ll_present:
        combined_lines.append("—")

    if ll_present:
        combined_lines.extend(_collect(
            _f("שם בעל הבית", ll.full_name),
            _f("ת.ז",         ll.id_number),
            _f("טלפון",       ll.phone,  "owner_phone"),
            _f("אימייל",      ll.email),
        ))

    if out_present and ll_present:
        other_heading = "דייר יוצא / בעל הבית"
    elif out_present:
        other_heading = "דייר יוצא"
    elif ll_present:
        other_heading = "בעל הבית"
    else:
        other_heading = ""

    other_section: dict | None = None
    if combined_lines:
        other_section = {
            "id":      "outgoing_landlord",
            "heading": other_heading,
            "lines":   combined_lines,
        }

    # ─── 7. Accounts (only for ordered services) ──────────────────────────────
    acct_lines: list[str] = []
    a = bs.arnona_accounts
    w = bs.water_accounts

    if has_arnona:
        acct_lines.extend(_collect(
            _f("מספר נכס ארנונה",    a.property_number,       "arnona_property_number"),
            _f("מספר לקוח ארנונה",   a.payer_number,          "arnona_customer_number"),
            _f("מספר זיהוי ארנונה",  a.identification_number, "arnona_id_number"),
        ))

    if has_water:
        wp = _f("מספר נכס מים",  w.property_number)
        wc = _f("מספר לקוח מים", w.payer_number)
        acct_lines.append(wp or "מספר נכס מים: חסר")
        acct_lines.append(wc or "מספר לקוח מים: חסר")

    if has_electricity:
        acct_lines.append("חשמל: פרטי מונה בפרטים המלאים")

    if has_gas:
        acct_lines.append("גז: פרטים בפרטים המלאים")

    acct_section = {
        "id":      "accounts",
        "heading": "חשבונות",
        "lines":   acct_lines,
    }

    # ─── 8. Documents ─────────────────────────────────────────────────────────
    def _doc_line(label: str, doc: Any) -> str:
        present = bool(Documents._doc_present(doc) and Documents._doc_present(doc) != "❌")
        return f"{label}: {'✅' if present else '❌ חסר'}"

    ds = bs.documents
    doc_lines = [
        _doc_line("תעודת זהות",   ds.id_photo),
        _doc_line("חתימה",         ds.signature),
        _doc_line("חוזה שכירות",   ds.lease_contract),
        _doc_line("חשבון ארנונה",  ds.arnona_bill),
    ]
    if inc.is_company:
        doc_lines.extend([
            _doc_line("תעודת התאגדות", ds.corp_cert),
            _doc_line("נסח טאבו",      ds.tabu),
        ])

    docs_section = {
        "id":      "documents",
        "heading": "מסמכים",
        "lines":   doc_lines,
    }

    # ─── Recommendation ────────────────────────────────────────────────────────
    all_missing_labels = (
        [item["label"] for item in (missing_info or [])]
        + [item["label"] for item in (missing_docs or [])]
    )
    has_errors = any(
        i.get("severity") == "error" for i in (validation_issues or [])
    )

    first_name = (
        (inc.first_name or "")
        or (inc.full_name.split()[0] if inc.full_name else "")
        or "הלקוח"
    )

    if all_missing_labels:
        items_str      = ", ".join(all_missing_labels)
        recommendation = f"📧 יש לבקש מ{first_name}: {items_str}"
    elif has_errors:
        recommendation = "🔍 בדיקה ידנית נדרשת לפני עיבוד — קיימות שגיאות"
    elif validation_issues:
        recommendation = "⚠️ בדוק אזהרות — ניתן לאשר לאחר בדיקה"
    else:
        recommendation = "✅ ניתן לעיבוד — שלח לעיר"

    # ─── Status ───────────────────────────────────────────────────────────────
    if has_errors:
        status, status_text = "error",   "❌ שגיאות — נדרשת בדיקה ידנית"
    elif all_missing_labels or validation_issues:
        status, status_text = "warning", "⚠️ ממתין להשלמת פרטים"
    else:
        status, status_text = "ok",      "✅ מלא — ניתן לעיבוד"

    # ─── Assemble sections ────────────────────────────────────────────────────
    sections = [tx_section, prop_section, date_section, inc_section, partner_section]
    if other_section:
        sections.append(other_section)
    if acct_lines:
        sections.append(acct_section)
    sections.append(docs_section)

    # ─── Header ───────────────────────────────────────────────────────────────
    header_date = bs.dates.move_in or ""
    header      = f"סיכום הגשה | {inc.full_name} | {header_date}"

    return {
        "header":         header,
        "status":         status,
        "status_text":    status_text,
        "sections":       sections,
        "recommendation": recommendation,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Layer B — detailed submission record
# ─────────────────────────────────────────────────────────────────────────────

def build_layer_b(
    bs: Any,                    # BusinessSubmission
    mzk_ref:      str = "",
    refund_id:    str = "",
    submitted_at: str = "",
) -> dict[str, Any]:
    """
    Build Layer B: full submission archive for operational use.

    Contains everything needed to process the submission with the municipality,
    water authority, and electric company. Does NOT omit empty fields — this is
    the complete record, not the decision view.
    """
    from app.mappers.models import Documents

    def _person_block(p: Any) -> dict[str, str]:
        if p is None:
            return {}
        block: dict[str, str] = {
            "שם מלא":    p.full_name   or "—",
            "שם פרטי":   p.first_name  or "—",
            "שם משפחה":  p.last_name   or "—",
            "ת.ז":       p.id_number   or "—",
            "טלפון":     p.phone       or "—",
            "אימייל":    p.email       or "—",
        }
        if p.is_company:
            block["שם חברה"] = p.company_name or "—"
            block["ח.פ"]     = p.company_reg  or "—"
        return block

    inc = bs.incoming_tenant
    out = bs.outgoing_tenant
    par = bs.partner
    ll  = bs.landlord
    a   = bs.arnona_accounts
    w   = bs.water_accounts

    amount_str = f"{bs.submission.amount_paid:.0f} ₪" if bs.submission.amount_paid else "—"

    result: dict[str, Any] = {
        "תשלום": {
            "חבילה":    bs.submission.package_description or "—",
            "סכום":     amount_str,
            "סטטוס":    "✅ שולם" if bs.submission.amount_paid else "❌ לא שולם",
            "סוג עסקה": bs.submission.transaction_type or "—",
            "שירותים":  ", ".join(bs.submission.services_selected) or "—",
        },

        "חשבון ארנונה": {
            "מספר נכס":         a.property_number       or "—",
            "מספר לקוח":        a.payer_number          or "—",
            "מספר זיהוי נכס":   a.identification_number or "—",
            "מספר חשבון תושב":  a.resident_account      or "—",
            "מספר חשבון לקוח":  a.customer_account      or "—",
        },

        "חשבון מים": {
            "מספר נכס":  w.property_number or "—",
            "מספר לקוח": w.payer_number    or "—",
        },

        "דייר נכנס": _person_block(inc),

        "תאריכים": {
            "כניסה":       bs.dates.move_in       or "—",
            "יציאה":       bs.dates.move_out       or "—",
            "סיום שכירות": bs.dates.lease_end     or "—",
            "תאריך מעבר":  bs.dates.transfer_date or "—",
        },

        "נכס": {
            "כתובת מלאה": bs.property.full_address or "—",
            "עיר":        bs.property.city         or "—",
            "רחוב":       bs.property.street       or "—",
            "בניין":      bs.property.building     or "—",
            "דירה":       bs.property.apartment    or "—",
            "קומה":       bs.property.floor        or "—",
            "כניסה":      bs.property.entrance     or "—",
        },

        "מסמכים": {
            "תעודת זהות":    "✅" if Documents._doc_present(bs.documents.id_photo)       else "❌",
            "חתימה":          "✅" if Documents._doc_present(bs.documents.signature)      else "❌",
            "חוזה שכירות":   "✅" if Documents._doc_present(bs.documents.lease_contract) else "❌",
            "חשבון ארנונה":  "✅" if Documents._doc_present(bs.documents.arnona_bill)    else "❌",
            "תעודת התאגדות": "✅" if Documents._doc_present(bs.documents.corp_cert)      else "❌",
            "נסח טאבו":      "✅" if Documents._doc_present(bs.documents.tabu)           else "❌",
        },

        "מידע פנימי": {
            "מספר פנייה": mzk_ref      or "—",
            "מזהה החזר":  refund_id    or "—",
            "תאריך הגשה": submitted_at or "—",
        },
    }

    # Add optional party blocks only when they exist
    if par and (par.full_name or par.phone):
        result["שותף"] = _person_block(par)
    if out and (out.full_name or out.phone or out.id_number):
        result["דייר יוצא"] = _person_block(out)
    if ll and (ll.full_name or ll.phone):
        result["בעל הבית"] = _person_block(ll)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Legacy fallback — DO NOT MODIFY
# ─────────────────────────────────────────────────────────────────────────────
# Used by YAML-driven services and as fallback when BusinessSubmission fails.
# Consumed by email_templates.py (reads "דייר_נכנס"."שם", "פרטי_נכס"."כתובת",
# "סוג_עסקה"."שירות") and queue.py (reads "מידע_פנימי"."מספר_פנייה").
# ─────────────────────────────────────────────────────────────────────────────


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
    Legacy fixed-template summary from section-keyed parsed dict.
    Every section always present; empty fields show 'לא סופק'.
    Consumed by email_templates.py and queue.py — keys must not change.
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
        "סוג_עסקה":    _v(_get(system, "סוג_עסקה") or _get(basic, "סוג_מעבר")),
        "שירות":       _v(pkg_name),
        "שירותים":     _v(services),
        "עיר":         _v(city),
        "סוג_לקוח":    _v(_get(basic, "סוג_לקוח")),
        "לאן_מעבירים": _v(_get(basic, "לאן_להעביר")),
    }

    # ── 2. Property ───────────────────────────────────────────────────────────
    summary["פרטי_נכס"] = {
        "כתובת": _v(address),
        "עיר":   _v(city),
        "רחוב":  _v(street),
        "בניין": _v(building),
        "דירה":  _v(apartment),
        "קומה":  _v(floor),
        "כניסה": _v(entrance),
    }

    # ── 3. Dates ──────────────────────────────────────────────────────────────
    summary["תאריכים"] = {
        "כניסה":       _v(_get(basic, "תאריך_כניסה")),
        "יציאה":       _v(_get(basic, "תאריך_יציאה")),
        "סיום_חוזה":   _v(_get(basic, "תאריך_סיום_חוזה")),
        "תאריך_העברה": _v(_get(basic, "תאריך_העברה")),
    }

    # ── 4. Incoming tenant — always ───────────────────────────────────────────
    customer_name = _full_name(customer)
    summary["דייר_נכנס"] = {
        "שם":         _v(customer_name),
        "טלפון":      _v(_get(customer, "טלפון")),
        "אימייל":     _v(_get(customer, "אימייל")),
        "תעודת_זהות": _v(_get(customer, "תעודת_זהות")),
    }

    # ── 5. Second tenant / partner — ALWAYS shown ─────────────────────────────
    summary["שוכר_שני"] = {
        "שם":         _v(_full_name(partner)),
        "טלפון":      _v(_get(partner, "טלפון")),
        "אימייל":     _v(_get(partner, "אימייל")),
        "תעודת_זהות": _v(_get(partner, "תעודת_זהות")),
    }

    # ── 6. Outgoing tenant — ALWAYS shown ─────────────────────────────────────
    summary["דייר_יוצא"] = {
        "שם":         _v(_full_name(outgoing)),
        "טלפון":      _v(_get(outgoing, "טלפון")),
        "אימייל":     _v(_get(outgoing, "אימייל")),
        "תעודת_זהות": _v(_get(outgoing, "תעודת_זהות")),
    }

    # ── 7. Landlord — ALWAYS shown ────────────────────────────────────────────
    summary["בעל_הבית"] = {
        "שם":         _v(_full_name(landlord) or _get(landlord, "שם_מלא")),
        "טלפון":      _v(_get(landlord, "טלפון")),
        "אימייל":     _v(_get(landlord, "אימייל")),
        "תעודת_זהות": _v(_get(landlord, "תעודת_זהות")),
    }

    # ── 8. Arnona account numbers — ALWAYS shown ──────────────────────────────
    summary["חשבון_ארנונה"] = {
        "מספר_נכס":         _v(_get(arnona, "מספר_נכס")),
        "מספר_לקוח":        _v(_get(arnona, "מספר_לקוח")),
        "מספר_זיהוי_נכס":   _v(_get(arnona, "מספר_זיהוי_נכס")),
        "מספר_חשבון_תושב":  _v(_get(arnona, "מספר_חשבון_תושב")),
        "מספר_חשבון_לקוח":  _v(_get(arnona, "מספר_חשבון_לקוח")),
    }

    # ── 9. Water account numbers — ALWAYS shown ───────────────────────────────
    summary["חשבון_מים"] = {
        "מספר_נכס":  _v(_get(water, "מספר_נכס")),
        "מספר_לקוח": _v(_get(water, "מספר_לקוח")),
    }

    # ── 10. Electricity — ALWAYS shown (no form fields yet) ──────────────────
    summary["חשבון_חשמל"] = {
        "מספר_נכס":  _N,
        "מספר_לקוח": _N,
    }

    # ── 11. Documents — ALWAYS shown, all 6 types ────────────────────────────
    summary["מסמכים"] = {
        "תעודת_זהות":     _doc_status(docs, "תעודת_זהות"),
        "חוזה_שכירות":    _doc_status(docs, "חוזה_שכירות"),
        "חתימה":           _doc_status(docs, "חתימה"),
        "חשבון_ארנונה":    _doc_status(docs, "חשבון_ארנונה"),
        "תעודת_התאגדות":  _doc_status(docs, "תעודת_התאגדות"),
        "נסח_טאבו":        _doc_status(docs, "נסח_טאבו"),
    }

    # ── 12. Payment — ALWAYS shown ────────────────────────────────────────────
    amount_str  = f"{amount} ₪" if amount else _N
    paid_status = "שולם ✅" if amount else "לא שולם"
    summary["פרטי_תשלום"] = {
        "שירות":       _v(pkg_name),
        "סכום":        amount_str,
        "סטטוס_תשלום": paid_status,
    }

    # ── 13. Internal reference — ALWAYS shown ────────────────────────────────
    mzk_id    = _get(system, "מזהה_מזכ")
    refund_id = _get(system, "מזהה_החזר")
    summary["מידע_פנימי"] = {
        "מספר_פנייה": mzk_id    or _N,
        "מזהה_החזר":  refund_id or _N,
    }

    return summary
