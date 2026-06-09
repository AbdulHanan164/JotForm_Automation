"""
Document rule definitions.

Each rule is a plain dict:
  {
      "id":       str    — unique rule identifier
      "label":    str    — human-readable name shown in the summary
      "check":    callable(ParsedSubmission) -> bool   — True = present/satisfied
      "required": callable(ParsedSubmission) -> bool   — True = this doc is required
      "section":  str    — "documents" | "customer" | "landlord" etc.
  }

Adding a new required document = adding one entry here. Zero code elsewhere changes.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.parsers.jotform_parser import ParsedSubmission


def _doc_present(sub: "ParsedSubmission", key: str) -> bool:
    """Return True if a document field exists and is marked as present."""
    val = sub.documents.get(key)
    if isinstance(val, dict):
        return bool(val.get("present", False))
    if isinstance(val, bool):
        return val
    return bool(val)


DOCUMENT_RULES: list[dict] = [

    # ── Always required ────────────────────────────────────────────────────
    {
        "id":       "id_photo",
        "label":    "ID Photo",
        "section":  "documents",
        "check":    lambda sub: _doc_present(sub, "id_photo"),
        "required": lambda sub: True,
    },
    {
        "id":       "signature",
        "label":    "Digital Signature",
        "section":  "documents",
        "check":    lambda sub: _doc_present(sub, "signature"),
        "required": lambda sub: True,
    },
    {
        "id":       "terms_accepted",
        "label":    "Terms & Conditions Accepted",
        "section":  "documents",
        "check":    lambda sub: sub.documents.get("terms_accepted", False) is True,
        "required": lambda sub: True,
    },
    {
        "id":       "agreement_signed",
        "label":    "Agreement Signed",
        "section":  "documents",
        "check":    lambda sub: sub.documents.get("agreement_signed", False) is True,
        "required": lambda sub: True,
    },

    # ── Required when outgoing tenant is provided ──────────────────────────
    {
        "id":       "outgoing_tenant_id",
        "label":    "Outgoing Tenant ID Number",
        "section":  "outgoing_tenant",
        "check":    lambda sub: bool(sub.outgoing_tenant.get("id_number", "").strip()),
        "required": lambda sub: bool(sub.outgoing_tenant.get("email") or sub.outgoing_tenant.get("phone")),
    },
    {
        "id":       "outgoing_tenant_email",
        "label":    "Outgoing Tenant Email",
        "section":  "outgoing_tenant",
        "check":    lambda sub: bool(sub.outgoing_tenant.get("email", "").strip()),
        "required": lambda sub: bool(sub.outgoing_tenant.get("first_name")),
    },

    # ── Required when landlord is provided ────────────────────────────────
    {
        "id":       "landlord_email",
        "label":    "Landlord Email",
        "section":  "landlord",
        "check":    lambda sub: bool(sub.landlord.get("email", "").strip()),
        "required": lambda sub: bool(sub.landlord.get("first_name")),
    },
    {
        "id":       "landlord_phone",
        "label":    "Landlord Phone",
        "section":  "landlord",
        "check":    lambda sub: bool(sub.landlord.get("phone", "").strip()),
        "required": lambda sub: bool(sub.landlord.get("first_name")),
    },

    # ── Required when electricity is a selected utility ────────────────────
    {
        "id":       "electricity_meter",
        "label":    "Electricity Meter Number",
        "section":  "services",
        "check":    lambda sub: bool(sub.services.get("electricity_meter", "").strip()),
        "required": lambda sub: sub.services.get("utilities", {}).get("electricity", False),
    },
]
