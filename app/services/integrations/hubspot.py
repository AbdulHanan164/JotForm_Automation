"""
HubSpot CRM integration stub.

When ready to implement:
  pip install hubspot-api-client
  Set HUBSPOT_API_KEY in .env

The summary dict passed here is the OnboardingSummary output —
no raw JotForm field IDs, only clean labelled data.
"""
from typing import Any


def create_or_update_contact(summary: dict[str, Any]) -> dict:
    """Create/update a HubSpot contact from customer data."""
    raise NotImplementedError

def create_deal(summary: dict[str, Any]) -> dict:
    """Create a HubSpot deal linked to the contact."""
    raise NotImplementedError

def attach_note(deal_id: str, note: str) -> None:
    """Attach a note to an existing deal."""
    raise NotImplementedError
