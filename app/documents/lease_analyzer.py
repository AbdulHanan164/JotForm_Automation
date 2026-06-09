"""
Lease agreement analyzer.

Current state: STUB — returns a mock extraction with a clear note.
The interface is fully defined so dropping in OpenAI Vision requires
only implementing _ai_extract() below.

To wire up AI extraction:
  1. Set OPENAI_API_KEY in .env
  2. Implement _ai_extract(file_bytes, filename) → LeaseExtraction
  3. Change the dispatch in analyze() to call _ai_extract()

The mock is intentionally realistic so the rest of the pipeline
(validator, review queue) can be tested without AI credentials.
"""
from __future__ import annotations

import logging
from typing import Any

from app.documents.schemas import ExtractionState, LeaseExtraction

logger = logging.getLogger("webhook")


def analyze(url: str, parsed_form: dict[str, Any]) -> LeaseExtraction:
    """
    Entry point: analyze a lease document from its JotForm URL.

    parsed_form is passed so the mock can build a realistic placeholder
    using names/dates that are already known from the form.
    """
    if not url or not url.startswith("http"):
        return LeaseExtraction(
            source_url = url,
            state      = ExtractionState.NOT_ATTEMPTED,
            extraction_notes = "No valid URL provided",
        )

    # Check if AI is available
    try:
        from app.config import settings
        has_openai = bool(settings.openai_api_key)
    except Exception:
        has_openai = False

    if has_openai:
        return _ai_extract(url, parsed_form)
    else:
        return _mock_extract(url, parsed_form)


def _mock_extract(url: str, parsed_form: dict[str, Any]) -> LeaseExtraction:
    """
    Return a mock extraction built from known form data.
    Clearly marked as MOCK so the review UI shows it needs manual verification.
    """
    customer = parsed_form.get("customer", {})
    partner  = parsed_form.get("partner", {})
    outgoing = parsed_form.get("outgoing", {})
    landlord = parsed_form.get("landlord", {})
    basic    = parsed_form.get("basic", {})
    prop     = parsed_form.get("property", {})

    # Build tenant list from form data
    tenants = []
    c_first = customer.get("שם_פרטי", "")
    c_last  = customer.get("שם_משפחה", "")
    if c_first or c_last:
        tenants.append(f"{c_first} {c_last}".strip())
    p_first = partner.get("שם_פרטי", "")
    p_last  = partner.get("שם_משפחה", "")
    if p_first or p_last:
        tenants.append(f"{p_first} {p_last}".strip())

    # Landlord from form
    ll_name = landlord.get("שם_מלא", "") or (
        f"{landlord.get('שם_פרטי', '')} {landlord.get('שם_משפחה', '')}".strip()
    )

    # Address from form
    street    = prop.get("רחוב", "")
    apartment = prop.get("דירה", "")
    city      = basic.get("עיר", "")
    address   = f"{street} דירה {apartment}, {city}".strip(", ")

    tenant_ids = []
    if customer.get("תעודת_זהות"):
        tenant_ids.append(customer["תעודת_זהות"])
    if partner.get("תעודת_זהות"):
        tenant_ids.append(partner["תעודת_זהות"])

    n_tenants = len(tenants)

    logger.info(
        "Lease: MOCK extraction (AI not configured) for %s — %d tenants",
        url.split("/")[-1], n_tenants,
    )

    return LeaseExtraction(
        source_url               = url,
        file_name                = url.split("/")[-1],
        state                    = ExtractionState.MOCK,
        confidence               = 0.0,
        extracted_by             = "mock",
        extraction_notes         = (
            "⚠️ חילוץ AI לא מוגדר — נדרש אימות ידני של פרטי החוזה. "
            "הנתונים לקוחים מהטופס ולא מהחוזה עצמו."
        ),
        landlord_names           = [ll_name] if ll_name else [],
        tenant_names             = tenants,
        tenant_ids               = tenant_ids,
        property_address         = address,
        start_date               = basic.get("תאריך_כניסה", ""),
        end_date                 = basic.get("תאריך_סיום_חוזה", ""),
        is_landlord_signed       = False,   # unknown without AI
        tenant_signatures_found  = 0,       # unknown without AI
        tenant_signatures_needed = n_tenants,
        missing_signatures       = ["נדרש אימות ידני"],
    )


def _ai_extract(url: str, parsed_form: dict[str, Any]) -> LeaseExtraction:
    """
    AI-powered extraction using OpenAI Vision.
    Implement this when OPENAI_API_KEY is set.

    Steps:
      1. Download the file from `url`
      2. If PDF: convert pages to images (pdf2image)
      3. Send each page to openai.chat.completions with vision
      4. Parse structured JSON response into LeaseExtraction fields
      5. Return with state=AI_EXTRACTED, confidence=response.confidence

    Placeholder — raises NotImplementedError until implemented.
    """
    raise NotImplementedError(
        "AI lease extraction not yet implemented. "
        "Set OPENAI_API_KEY and implement _ai_extract() in lease_analyzer.py"
    )
