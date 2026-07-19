"""
Business mapper — converts the section-keyed parsed dict → BusinessSubmission.

Priority order (per field):
  1. FHS-normalized section (parsed["fhs"]) — populated once JotForm field IDs
     for FHS columns are configured in config/field_maps/arnona.yaml.
  2. Raw section-keyed data (parsed["customer"], ["outgoing"], etc.) — always
     available regardless of field ID configuration status.

This means the mapper works correctly before FHS IDs are known — it falls back
to the raw section data.  When the operator configures real FHS IDs and restarts,
FHS data takes priority automatically.

Usage:
    from app.mappers.business_mapper import build_from_parsed
    bs = build_from_parsed(parsed)
    parsed["_business"] = bs.to_dict()   # stored on parsed, JSON-safe
"""
from __future__ import annotations

from typing import Any

from app.mappers.models import (
    ArnonaAccounts,
    BusinessSubmission,
    Dates,
    Documents,
    Person,
    Property,
    SubmissionMeta,
    WaterAccounts,
)


# ── Private helpers ───────────────────────────────────────────────────────────

def _s(val: Any) -> str:
    """Safe string — coerce and strip, return '' for None/empty."""
    if val is None:
        return ""
    if isinstance(val, dict):
        return ""   # file/signature blob — not a string
    if isinstance(val, list):
        return ", ".join(str(v) for v in val if v)
    return str(val).strip()


def _coalesce(*values: Any) -> str:
    """Return the first non-empty string value."""
    for v in values:
        s = _s(v) if not isinstance(v, str) else v.strip()
        if s:
            return s
    return ""


def _join_name(section: dict) -> str:
    """Combine שם_פרטי + שם_משפחה from a customer-style section."""
    first = _s(section.get("שם_פרטי", ""))
    last  = _s(section.get("שם_משפחה", ""))
    if first and last:
        return f"{first} {last}"
    return first or last


def _is_company(basic: dict) -> bool:
    ptype = _s(basic.get("סוג_לקוח", "")).lower()
    return "חברה" in ptype or "עסק" in ptype or "תאגיד" in ptype


def _build_address(city: str, prop: dict) -> str:
    """Assemble a human-readable address from property section fields."""
    street    = _s(prop.get("רחוב", ""))
    building  = _s(prop.get("בניין", ""))
    entrance  = _s(prop.get("כניסה", ""))
    apartment = _s(prop.get("דירה", ""))
    floor_    = _s(prop.get("קומה", ""))

    parts = [street]
    if building:  parts.append(f"בניין {building}")
    if entrance:  parts.append(f"כניסה {entrance}")
    if apartment: parts.append(f"דירה {apartment}")
    if floor_:    parts.append(f"קומה {floor_}")
    if city:      parts.append(city)
    return ", ".join(p for p in parts if p)


# ── Public API ────────────────────────────────────────────────────────────────

def build_from_parsed(parsed: dict[str, Any]) -> BusinessSubmission:
    """
    Map the section-keyed parsed dict produced by ArnonaService.parse_fields()
    into a typed BusinessSubmission.

    FHS section (parsed["fhs"]) takes priority; raw sections are the fallback.
    """
    fhs      = parsed.get("fhs", {})
    basic    = parsed.get("basic", {})
    customer = parsed.get("customer", {})
    partner  = parsed.get("partner", {})
    outgoing = parsed.get("outgoing", {})
    landlord = parsed.get("landlord", {})
    prop     = parsed.get("property", {})
    arnona   = parsed.get("arnona", {})
    docs     = parsed.get("documents", {})
    payment  = parsed.get("payment", {})

    # ── Submission metadata ───────────────────────────────────────────────────
    from app.rules.transaction import detect_transaction_type, role_routing

    package     = _coalesce(fhs.get("package"), payment.get("שם_שירות"))
    transfer_to = _s(basic.get("לאן_להעביר", ""))
    txn_type    = detect_transaction_type(
        basic, package, transfer_to,
        partner_section=partner,
        unmapped=parsed.get("_unmapped", {}),
    )

    raw_amount = payment.get("סכום", "")
    try:
        amount_paid: float | None = float(
            _s(raw_amount).replace("₪", "").replace(",", "") or "x"
        )
    except ValueError:
        amount_paid = None

    raw_services = basic.get("שירותים_נבחרים", [])
    if isinstance(raw_services, list):
        services_selected = [str(s).strip() for s in raw_services if s]
    else:
        services_selected = [s.strip() for s in _s(raw_services).split(",") if s.strip()]

    submission_meta = SubmissionMeta(
        transaction_type    = txn_type,
        package_description = package,
        services_selected   = services_selected,
        amount_paid         = amount_paid,
        transfer_to         = transfer_to,
    )

    # Role routing: which raw section feeds which business role.
    # Single table in app/rules/transaction.py — shared with the classifier so
    # classification and role assignment can never drift apart (pre-v0.7 this
    # branching was duplicated here).
    _sections = {
        "customer": customer, "partner": partner,
        "outgoing": outgoing, "landlord": landlord,
    }
    inc_name, part_name, out_name, ll_name = role_routing(
        basic.get("סוג_מעבר", ""), basic.get("סוג_משכיר", "")
    )
    inc_src  = _sections.get(inc_name, {})  if inc_name  else {}
    part_src = _sections.get(part_name, {}) if part_name else {}
    out_src  = _sections.get(out_name, {})  if out_name  else {}
    ll_src   = _sections.get(ll_name, {})   if ll_name   else {}

    # ── Incoming tenant ───────────────────────────────────────────────────────
    in_name = _coalesce(fhs.get("incoming_full_name"), _join_name(inc_src))
    incoming_tenant = Person(
        full_name    = in_name,
        first_name   = _s(inc_src.get("שם_פרטי", "")),
        last_name    = _s(inc_src.get("שם_משפחה", "")),
        id_number    = _coalesce(fhs.get("incoming_id"), inc_src.get("תעודת_זהות")),
        phone        = _coalesce(fhs.get("incoming_phone"), inc_src.get("טלפון")),
        email        = _coalesce(fhs.get("incoming_email"), inc_src.get("אימייל")),
        is_company   = _is_company(basic),
        company_name = _s(inc_src.get("שם_חברה", "")),
        company_reg  = _s(inc_src.get("מספר_חברה", "")),
    )

    # ── Outgoing tenant ───────────────────────────────────────────────────────
    out_name  = _coalesce(fhs.get("outgoing_full_name"), _join_name(out_src))
    out_phone = _coalesce(fhs.get("outgoing_phone"), out_src.get("טלפון"))
    out_id    = _coalesce(fhs.get("outgoing_id"), out_src.get("תעודת_זהות"))
    outgoing_tenant: Person | None = None
    if out_name or out_phone or out_id:
        outgoing_tenant = Person(
            full_name    = out_name,
            first_name   = _s(out_src.get("שם_פרטי", "")),
            last_name    = _s(out_src.get("שם_משפחה", "")),
            id_number    = out_id,
            phone        = out_phone,
            email        = _coalesce(fhs.get("outgoing_email"), out_src.get("אימייל")),
        )

    # ── Partner (second tenant) ───────────────────────────────────────────────
    part_name  = _coalesce(fhs.get("partner_full_name"), _join_name(part_src))
    part_phone = _coalesce(fhs.get("partner_phone"), part_src.get("טלפון"))
    part_id    = _coalesce(fhs.get("partner_id"), part_src.get("תעודת_זהות"))
    partner_person: Person | None = None
    if part_name or part_phone or part_id:
        partner_person = Person(
            full_name    = part_name,
            first_name   = _s(part_src.get("שם_פרטי", "")),
            last_name    = _s(part_src.get("שם_משפחה", "")),
            id_number    = part_id,
            phone        = part_phone,
            email        = _coalesce(fhs.get("partner_email"), part_src.get("אימייל")),
        )

    # ── Landlord ──────────────────────────────────────────────────────────────
    ll_name  = _coalesce(
        fhs.get("landlord_full_name"),
        _join_name(ll_src),
        ll_src.get("שם_מלא"),
    )
    ll_phone = _coalesce(fhs.get("landlord_phone"), ll_src.get("טלפון"))
    ll_id    = _coalesce(fhs.get("landlord_id"), ll_src.get("תעודת_זהות"))
    landlord_person: Person | None = None
    if ll_name or ll_phone or ll_id:
        landlord_person = Person(
            full_name    = ll_name,
            first_name   = _s(ll_src.get("שם_פרטי", "")),
            last_name    = _s(ll_src.get("שם_משפחה", "")),
            id_number    = ll_id,
            phone        = ll_phone,
            email        = _coalesce(fhs.get("landlord_email"), ll_src.get("אימייל")),
        )

    # ── Property ──────────────────────────────────────────────────────────────
    city         = _coalesce(fhs.get("city"), basic.get("עיר"))
    full_address = _coalesce(fhs.get("full_address"), _build_address(city, prop))
    property_ = Property(
        city         = city,
        street       = _s(prop.get("רחוב", "")),
        building     = _s(prop.get("בניין", "")),
        apartment    = _s(prop.get("דירה", "")),
        floor        = _s(prop.get("קומה", "")),
        entrance     = _s(prop.get("כניסה", "")),
        full_address = full_address,
    )

    # ── Dates ─────────────────────────────────────────────────────────────────
    dates = Dates(
        move_in       = _s(basic.get("תאריך_כניסה", "")),
        move_out      = _s(basic.get("תאריך_יציאה", "")),
        lease_end     = _s(basic.get("תאריך_סיום_חוזה", "")),
        transfer_date = _coalesce(fhs.get("transfer_date"), basic.get("תאריך_העברה")),
    )

    # ── Arnona accounts ───────────────────────────────────────────────────────
    arnona_accounts = ArnonaAccounts(
        property_number       = _s(arnona.get("מספר_נכס", "")),
        identification_number = _s(arnona.get("מספר_זיהוי_נכס", "")),
        payer_number          = _s(arnona.get("מספר_לקוח", "")),
        resident_account      = _s(arnona.get("מספר_חשבון_תושב", "")),
        customer_account      = _s(arnona.get("מספר_חשבון_לקוח", "")),
    )

    # ── Water accounts ────────────────────────────────────────────────────────
    water_accounts = WaterAccounts(
        property_number = _s(parsed.get("water", {}).get("מספר_נכס", "")),
        payer_number    = _s(parsed.get("water", {}).get("מספר_לקוח", "")),
    )

    # ── Documents ─────────────────────────────────────────────────────────────
    documents = Documents(
        id_photo       = docs.get("תעודת_זהות"),
        lease_contract = docs.get("חוזה_שכירות"),
        signature      = docs.get("חתימה"),
        arnona_bill    = docs.get("חשבון_ארנונה"),
        corp_cert      = docs.get("תעודת_התאגדות"),
        tabu           = docs.get("נסח_טאבו"),
    )

    # ── Supplemental services (v0.7 — address update etc.) ───────────────────
    from app.mappers.supplemental_services import parse_supplemental, serialize
    supplemental = serialize(parse_supplemental(parsed))

    sub_id = parsed.get("system", {}).get("submission_id", "") or parsed.get("submission_id", "")
    return BusinessSubmission(
        submission      = submission_meta,
        dates           = dates,
        property        = property_,
        arnona_accounts = arnona_accounts,
        water_accounts  = water_accounts,
        incoming_tenant = incoming_tenant,
        outgoing_tenant = outgoing_tenant,
        partner         = partner_person,
        landlord        = landlord_person,
        documents       = documents,
        submission_id   = sub_id,
        supplemental_services = supplemental,
    )
