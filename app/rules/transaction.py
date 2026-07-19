"""
Canonical transaction-type classifier (v0.7) — deterministic, tolerant,
corroborated. THE single place transaction types are decided.

Replaces business_mapper._detect_transaction_type, whose exact-string
comparison (`partner_type == "זוג נשוי"`) classified married couples as
single tenants whenever the marital answer varied by a character, arrived
under an unmapped QID, or was simply absent while full partner details were
sitting in the submission.

Strategy (all deterministic, in priority order):
  1. Normalize every discriminator string (strip bidi marks, punctuation,
     collapse whitespace) before matching.
  2. Match partner kind by tolerant token search: any form of
     שותפ… → roommates; any form of זוג / נשוי / נשוא… → couple.
  3. If the mapped partner-kind field is empty, scan the submission's
     _unmapped values for the same tokens — a form-revision moving the
     question to a new QID must not silently degrade everyone to "single".
  4. CORROBORATION: if the partner section contains real person data but no
     partner-kind string was found anywhere, the tenant is still NOT single —
     classify as couple (the couple flow is the one that collects partner
     details on this form; the roommates flow uses its own explicit answer).

Role routing (which raw section feeds which business role) lives here too —
ROLE_ROUTING — so the classifier and the business mapper can never drift
apart again (pre-v0.7 the same branching was written twice in
business_mapper.py).
"""
from __future__ import annotations

import re
from typing import Any

from app.core.transactions import DEFAULT_TRANSACTION_TYPE

_BIDI_MARKS = "‎‏‪‫‬‭‮⁦⁧⁨⁩"

# Tolerant partner-kind tokens (normalized-substring match)
_ROOMMATE_TOKENS = ("שותפ", "שותף")               # שותפים / שותף (final-form) / שותפות
_COUPLE_TOKENS   = ("זוג", "נשוי", "נשוא", "בן זוג", "בת זוג")
_COMPANY_TOKENS  = ("חברה", "עסק", "תאגיד")


def normalize(value: Any) -> str:
    """Strip bidi marks/punctuation noise and collapse whitespace."""
    if value is None:
        return ""
    s = str(value)
    for ch in _BIDI_MARKS:
        s = s.replace(ch, "")
    s = re.sub(r"[\"'.\-_/]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return bool(text) and any(t in text for t in tokens)


def partner_kind(value: Any) -> str:
    """Classify a partner-type answer: "roommates" | "couple" | ""."""
    text = normalize(value)
    if _contains_any(text, _ROOMMATE_TOKENS):
        return "roommates"
    if _contains_any(text, _COUPLE_TOKENS):
        return "couple"
    return ""


def _is_company(customer_type: str) -> bool:
    return _contains_any(normalize(customer_type), _COMPANY_TOKENS)


def _partner_kind_from_unmapped(unmapped: dict[str, Any]) -> str:
    """Scan unmapped webhook values for a partner-kind answer (step 3)."""
    for value in (unmapped or {}).values():
        kind = partner_kind(value)
        if kind:
            return kind
    return ""


def _partner_section_has_data(partner: dict[str, Any]) -> bool:
    for key in ("שם_פרטי", "שם_משפחה", "תעודת_זהות", "טלפון", "אימייל"):
        v = partner.get(key)
        if v is not None and str(v).strip():
            return True
    return False


def detect_transaction_type(
    basic: dict[str, Any],
    package: str = "",
    transfer_to: str = "",
    partner_section: dict[str, Any] | None = None,
    unmapped: dict[str, Any] | None = None,
) -> str:
    """Derive the transaction type. Deterministic — no AI, no network.

    Args mirror what parse_fields produces: the basic section, the payment
    package description, the transfer-to field, plus (new in v0.7) the raw
    partner section and the _unmapped bucket for corroboration.
    """
    move_type     = normalize(basic.get("סוג_מעבר", ""))
    customer_type = normalize(basic.get("סוג_לקוח", ""))
    landlord_role = normalize(basic.get("סוג_משכיר", ""))

    # ── Partner kind: mapped field → _unmapped scan → data corroboration ─────
    kind = partner_kind(basic.get("שותפים", ""))
    if not kind:
        kind = _partner_kind_from_unmapped(unmapped or {})
    if (not kind
            and move_type in ("מתחיל שכירות", "מסיים שכירות")
            and _partner_section_has_data(partner_section or {})):
        # Partner details present but no marital/roommate answer found:
        # definitely not "single". The couple flow is the one that collects
        # partner details on this form (see config/field_maps/arnona.yaml,
        # partner section) — classify as couple.
        # NOT applied to the "בעל בית" flow, where the partner section holds
        # the TENANT's details (see role_routing), not a second tenant.
        kind = "couple"

    def _suffix() -> str:
        if _is_company(customer_type):
            return "company"
        if kind == "roommates":
            return "roommates"
        if kind == "couple":
            return "couple"
        return "single"

    if move_type == "מתחיל שכירות":
        return f"rental_start_{_suffix()}"

    if move_type == "מסיים שכירות":
        return f"rental_termination_{_suffix()}"

    if move_type == "בעל בית":
        if landlord_role == "משכיר":
            suffix = _suffix()
            if suffix == "company":       # company landlord has no dedicated code
                suffix = "single"
            return f"landlord_rental_{suffix}"
        if landlord_role == "קונה":
            return "sale_purchase"
        if landlord_role == "מוכר":
            return "sale_transfer"
        if landlord_role == "חוזר לנכס":
            return "owner_return"

    # ── Legacy fallback (pre-Phase-11 payloads without Q3/Q7) ────────────────
    pkg = (package or "").lower()
    if "גמר חשבון" in pkg:
        return "account_closure"
    if "קניה" in pkg or "מכירה" in pkg or "תאגיד" in pkg:
        return "sale_transfer"
    tf = transfer_to or ""
    if "בעל הנכס" in tf or "בעל_הנכס" in tf:
        return "owner_transfer"
    return DEFAULT_TRANSACTION_TYPE


# ── Role routing — single table shared with business_mapper ──────────────────
# (incoming, partner, outgoing, landlord) ← names of raw parse sections;
# None means "no source" (empty role).
#
# Keyed on the RAW form answers (סוג_מעבר / סוג_משכיר), exactly like the
# pre-v0.7 mapper branching — legacy payloads without those answers keep the
# default routing regardless of which transaction code the package-description
# fallback produced.

_DEFAULT_ROUTE = ("customer", "partner", "outgoing", "landlord")

_MOVE_TYPE_ROUTES: dict[str, tuple[str | None, str | None, str | None, str | None]] = {
    "מתחיל שכירות": _DEFAULT_ROUTE,
    "מסיים שכירות": (None, "partner", "customer", "landlord"),
}

_LANDLORD_ROLE_ROUTES: dict[str, tuple[str | None, str | None, str | None, str | None]] = {
    "משכיר":     ("partner",  None,      "outgoing", "customer"),
    "קונה":      ("customer", "partner", "outgoing", None),
    "מוכר":      ("outgoing", "partner", "customer", None),
    "חוזר לנכס": ("customer", "partner", "outgoing", "customer"),
}


def role_routing(
    move_type: Any,
    landlord_role: Any = "",
) -> tuple[str | None, str | None, str | None, str | None]:
    """(incoming_src, partner_src, outgoing_src, landlord_src) section names.

    THE routing table — business_mapper consumes it; the same raw answers
    drive detect_transaction_type, so classification and role assignment can
    never drift apart.
    """
    mt = normalize(move_type)
    if mt == "בעל בית":
        return _LANDLORD_ROLE_ROUTES.get(normalize(landlord_role), _DEFAULT_ROUTE)
    return _MOVE_TYPE_ROUTES.get(mt, _DEFAULT_ROUTE)
