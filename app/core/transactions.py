"""
Canonical transaction-type registry — the ONE source of truth for transaction
codes, their business traits, and their display labels.

Before v0.7 the codes lived implicitly in business_mapper string branches and
the display labels were duplicated in two dashboard i18n dicts. The traits
below also drive the requirement engine (app/rules/requirements.py), replacing
per-rule hardcoding of "which transaction needs what".

Traits vocabulary
-----------------
  has_incoming   — someone is moving IN (incoming-tenant details required)
  has_outgoing   — someone is moving OUT (outgoing-tenant details required)
  has_landlord   — a landlord distinct from the paying customer must confirm
  needs_contract — a lease/sale contract proves entitlement
  contract_kind  — "lease" | "sale" | None (display + satisfied-by set)
  needs_tabu     — ownership proof required regardless of client type
  partner_expected — the type itself implies a second person (couple/roommates)
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TransactionTraits:
    has_incoming:     bool = True
    has_outgoing:     bool = False
    has_landlord:     bool = False
    needs_contract:   bool = True
    contract_kind:    str | None = "lease"
    needs_tabu:       bool = False
    partner_expected: bool = False


_RENTAL_IN  = TransactionTraits(has_incoming=True,  has_landlord=True)
_RENTAL_OUT = TransactionTraits(has_incoming=False, has_outgoing=True, has_landlord=True)
# Landlord flows: the submitting customer IS the landlord (business_mapper
# routes the customer section to the landlord role), so has_landlord stays True
# — the data is present by construction and never produces a false "missing".
_LANDLORD   = TransactionTraits(has_incoming=True,  has_landlord=True)

TRANSACTION_TRAITS: dict[str, TransactionTraits] = {
    # ── Rental move-in ────────────────────────────────────────────────────────
    "rental_start_single":        _RENTAL_IN,
    "rental_start_couple":        TransactionTraits(has_incoming=True, has_landlord=True, partner_expected=True),
    "rental_start_roommates":     TransactionTraits(has_incoming=True, has_landlord=True, partner_expected=True),
    "rental_start_company":       _RENTAL_IN,
    # ── Rental termination ────────────────────────────────────────────────────
    "rental_termination_single":    _RENTAL_OUT,
    "rental_termination_couple":    TransactionTraits(has_incoming=False, has_outgoing=True, has_landlord=True, partner_expected=True),
    "rental_termination_roommates": TransactionTraits(has_incoming=False, has_outgoing=True, has_landlord=True, partner_expected=True),
    "rental_termination_company":   _RENTAL_OUT,
    # ── Landlord-submitted flows ──────────────────────────────────────────────
    "landlord_rental_single":     _LANDLORD,
    "landlord_rental_couple":     TransactionTraits(has_incoming=True, has_landlord=True, partner_expected=True),
    "landlord_rental_roommates":  TransactionTraits(has_incoming=True, has_landlord=True, partner_expected=True),
    # ── Sale / ownership ──────────────────────────────────────────────────────
    "sale_purchase":  TransactionTraits(has_incoming=True, contract_kind="sale"),
    "sale_transfer":  TransactionTraits(has_incoming=True, has_outgoing=True, contract_kind="sale"),
    "owner_return":   TransactionTraits(has_incoming=True, needs_contract=False, contract_kind=None, needs_tabu=True),
    # ── Legacy codes (pre-Phase-11 records still carry these) ─────────────────
    "rental_transfer": _RENTAL_IN,
    "owner_transfer":  TransactionTraits(has_incoming=True, needs_contract=False, contract_kind=None),
    "account_closure": _RENTAL_OUT,
}

DEFAULT_TRANSACTION_TYPE = "rental_transfer"


def traits_for(transaction_type: str) -> TransactionTraits:
    """Traits for a transaction code; unknown codes get safe rental defaults."""
    return TRANSACTION_TRAITS.get(transaction_type, _RENTAL_IN)


# ── Display labels (moved verbatim from app/routes/dashboard.py) ──────────────

TRANSACTION_LABELS: dict[str, dict[str, str]] = {
    "he": {
        "rental_transfer": "שכירות — כניסה",
        "sale_transfer":   "מכירת נכס",
        "owner_transfer":  "העברה לבעל הנכס",
        "account_closure": "גמר חשבון",
        "rental_start_single": "שכירות - כניסה (שוכר יחיד)",
        "rental_start_couple": "שכירות - כניסה (זוג)",
        "rental_start_roommates": "שכירות - כניסה (שותפים)",
        "rental_start_company": "שכירות - כניסה (חברה/עסק)",
        "rental_termination_single": "סיום שכירות - שוכר יחיד",
        "rental_termination_couple": "סיום שכירות - זוג",
        "rental_termination_roommates": "סיום שכירות - שותפים",
        "rental_termination_company": "סיום שכירות - חברה/עסק",
        "landlord_rental_single": "בעל בית - שוכר יחיד",
        "landlord_rental_couple": "בעל בית - זוג",
        "landlord_rental_roommates": "בעל בית - שותפים",
        "owner_return": "חזרת בעלים לנכס",
        "sale_purchase": "קניית נכס",
    },
    "en": {
        "rental_transfer": "Rental — Move In",
        "sale_transfer":   "Sale (Account Closure)",
        "owner_transfer":  "Transfer to Owner",
        "account_closure": "Account Closure",
        "rental_start_single": "Rental - Move In (Single)",
        "rental_start_couple": "Rental - Move In (Couple)",
        "rental_start_roommates": "Rental - Move In (Roommates)",
        "rental_start_company": "Rental - Move In (Corporate)",
        "rental_termination_single": "Rental Termination - Single",
        "rental_termination_couple": "Rental Termination - Couple",
        "rental_termination_roommates": "Rental Termination - Roommates",
        "rental_termination_company": "Rental Termination - Corporate",
        "landlord_rental_single": "Landlord - Rental (Single)",
        "landlord_rental_couple": "Landlord - Rental (Couple)",
        "landlord_rental_roommates": "Landlord - Rental (Roommates)",
        "owner_return": "Owner Return",
        "sale_purchase": "Purchase (New Owner)",
    },
}


def transaction_label(code: str, lang: str = "he") -> str:
    """Human-readable label; falls back to the raw code for unknown values."""
    return TRANSACTION_LABELS.get(lang, {}).get(code, code)
