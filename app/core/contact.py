"""
Canonical resolution of "who is the customer" for a submission.

Several places need to address one person: the dashboard quick view, and the
draft email greeting. Deriving that independently is how the greeting ended up
reading "לא שלום" — it took the incoming tenant's name, which on a termination
is the "not provided" placeholder.

The ORDER below is the single definition of that business rule. The two
adapters differ only in the shape they read (strongly-typed business_data vs
the Hebrew summary blocks); neither restates the order.
"""
from __future__ import annotations

from typing import Any

# The order in which a participant becomes "the customer".
PRIMARY_ROLE_ORDER: tuple[str, ...] = ("incoming_tenant", "outgoing_tenant", "landlord")

# The same roles as they appear in the Hebrew summary produced by build_summary().
SUMMARY_BLOCK: dict[str, str] = {
    "incoming_tenant": "דייר_נכנס",
    "outgoing_tenant": "דייר_יוצא",
    "landlord":        "בעל_הבית",
}

PLACEHOLDER = "לא סופק"


def clean(value: Any) -> str:
    """Trimmed text, treating the Hebrew "not provided" placeholder as absent."""
    s = str(value or "").strip()
    return "" if s in ("", PLACEHOLDER, "—") else s


def primary_contact(business_data: dict[str, Any] | None) -> tuple[dict[str, Any], str]:
    """The primary participant from strongly-typed business data.

    Returns (person, role). Selection is by who is actually NAMED — not by any
    populated field — so a termination stays on the outgoing tenant even when an
    incoming phone happens to be present. Returns ({}, "") when nobody is named.
    """
    bd = business_data or {}
    for role in PRIMARY_ROLE_ORDER:
        person = bd.get(role) or {}
        if isinstance(person, dict) and clean(person.get("full_name")):
            return person, role
    return {}, ""


def primary_name_from_summary(summary: dict[str, Any] | None) -> str:
    """The primary participant's full name, read from the Hebrew summary blocks.

    Used where only the summary is in scope (the email template). Walks the same
    PRIMARY_ROLE_ORDER, so it can never disagree with primary_contact().
    """
    s = summary or {}
    for role in PRIMARY_ROLE_ORDER:
        block = s.get(SUMMARY_BLOCK[role]) or {}
        if isinstance(block, dict):
            name = clean(block.get("שם"))
            if name:
                return name
    return ""


def first_name(full_name: str) -> str:
    """First token of a full name — "" when there is nothing usable."""
    name = clean(full_name)
    return name.split()[0] if name else ""
