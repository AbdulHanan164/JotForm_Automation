"""
Data models for extracted document content.

Every document type returns one of these dataclasses.
The pipeline stores them in PipelineResult.doc_extractions
and the validator compares them against form data.

Extraction states:
  NOT_ATTEMPTED  — no extractor configured for this file type
  MOCK           — placeholder data (AI not yet wired up)
  AI_EXTRACTED   — extracted by OpenAI Vision / NVIDIA
  MANUAL         — operator filled in manually via review UI
  FAILED         — extraction attempted but failed
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ExtractionState(str, Enum):
    NOT_ATTEMPTED = "not_attempted"
    MOCK          = "mock"
    AI_EXTRACTED  = "ai_extracted"
    MANUAL        = "manual"
    FAILED        = "failed"


@dataclass
class BaseExtraction:
    """Fields common to every extracted document."""
    doc_type:   str            = "unknown"      # lease / id / arnona_bill / signature
    source_url: str            = ""             # original JotForm upload URL
    file_name:  str            = ""
    state:      ExtractionState = ExtractionState.NOT_ATTEMPTED
    confidence: float          = 0.0            # 0.0–1.0
    extracted_by: str          = "none"         # "ai" | "manual" | "mock"
    extraction_notes: str      = ""             # operator/AI notes
    raw_text:   str            = ""             # full extracted text for debugging

    def to_dict(self) -> dict[str, Any]:
        return {k: (v.value if isinstance(v, Enum) else v)
                for k, v in self.__dict__.items()}


@dataclass
class LeaseExtraction(BaseExtraction):
    """Extracted data from a lease agreement (PDF or image)."""
    doc_type: str = "lease"

    # Parties
    landlord_names: list[str] = field(default_factory=list)   # as they appear in doc
    tenant_names:   list[str] = field(default_factory=list)   # all tenants listed
    tenant_ids:     list[str] = field(default_factory=list)   # ID numbers if present

    # Property
    property_address: str = ""

    # Dates
    start_date:       str = ""   # DD/MM/YYYY
    end_date:         str = ""
    duration_months:  int | None = None

    # Signatures
    is_landlord_signed:       bool         = False
    tenant_signatures_found:  int          = 0      # how many signature blocks found
    tenant_signatures_needed: int          = 0      # how many tenants are listed
    missing_signatures:       list[str]    = field(default_factory=list)

    # Flags
    has_renewal_clause:  bool = False
    has_guarantor:       bool = False
    monthly_rent:        str  = ""


@dataclass
class IDExtraction(BaseExtraction):
    """Extracted data from an Israeli ID card photo."""
    doc_type: str = "id"

    id_number:    str  = ""
    first_name:   str  = ""
    last_name:    str  = ""
    birth_date:   str  = ""
    expiry_date:  str  = ""
    is_expired:   bool = False


@dataclass
class ArnonaBillExtraction(BaseExtraction):
    """Extracted data from an arnona (municipal tax) bill."""
    doc_type: str = "arnona_bill"

    property_number:   str = ""
    customer_number:   str = ""
    identity_number:   str = ""
    tenant_account:    str = ""
    customer_account:  str = ""
    property_address:  str = ""
    amount_due:        str = ""
    due_date:          str = ""


@dataclass
class SignatureExtraction(BaseExtraction):
    """Extracted data from a digital signature field."""
    doc_type: str = "signature"

    is_present:    bool = False
    signer_name:   str  = ""    # if embedded in signature metadata
