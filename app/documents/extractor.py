"""
Document extractor — dispatcher.

Given a section of parsed form data (documents section), extracts
each uploaded document by dispatching to the right analyzer.

Returns dict[doc_label → BaseExtraction subclass].

Design:
  - Each document type has its own analyzer module.
  - Adding a new type = add one entry to DISPATCH_MAP.
  - Extraction is non-blocking: a failure on one doc doesn't stop others.
  - All results are stored; failures are marked with state=FAILED.
"""
from __future__ import annotations

import logging
from typing import Any

from app.documents.schemas import (
    BaseExtraction, ExtractionState,
    LeaseExtraction, SignatureExtraction,
)

logger = logging.getLogger("webhook")


def extract_all(
    docs_section: dict[str, Any],
    parsed_form:  dict[str, Any],
) -> dict[str, Any]:
    """
    Extract data from all uploaded documents found in the docs section.

    docs_section: the 'documents' key from parsed form
      e.g. {"חוזה_שכירות": {"present": True, "url": "https://..."}, ...}

    Returns dict: label → extraction.to_dict()
    """
    extractions: dict[str, Any] = {}

    for label, value in docs_section.items():
        if not isinstance(value, dict):
            continue
        url     = value.get("url", "")
        present = value.get("present", False)

        if not present:
            continue

        try:
            extraction = _dispatch(label, url, parsed_form)
        except Exception as exc:
            logger.warning("Extraction failed for '%s': %s", label, exc)
            extraction = BaseExtraction(
                doc_type         = label,
                source_url       = url,
                state            = ExtractionState.FAILED,
                extraction_notes = str(exc),
            )

        extractions[label] = extraction.to_dict()
        logger.info(
            "Extracted '%s': state=%s confidence=%.2f",
            label,
            extraction.state,
            extraction.confidence,
        )

    return extractions


def _dispatch(
    label:       str,
    url:         str,
    parsed_form: dict[str, Any],
) -> BaseExtraction:
    """Route a document label to the correct analyzer."""
    from app.documents import lease_analyzer

    # ── Lease agreement ───────────────────────────────────────────────────────
    if label in ("חוזה_שכירות", "lease_contract"):
        return lease_analyzer.analyze(url, parsed_form)

    # ── Signature ─────────────────────────────────────────────────────────────
    if label in ("חתימה", "signature"):
        return SignatureExtraction(
            source_url  = url,
            file_name   = label,
            state       = ExtractionState.AI_EXTRACTED,
            confidence  = 1.0,
            extracted_by= "rule",
            is_present  = bool(url),
        )

    # ── ID photo — stub until ID OCR is implemented ───────────────────────────
    if label in ("תעודת_זהות", "id_photo"):
        from app.documents.schemas import IDExtraction
        return IDExtraction(
            source_url       = url,
            file_name        = label,
            state            = ExtractionState.MOCK,
            confidence       = 0.0,
            extracted_by     = "mock",
            extraction_notes = "⚠️ OCR לת.ז לא מוגדר — נדרש אימות ידני",
        )

    # ── Arnona bill — stub ────────────────────────────────────────────────────
    if label in ("חשבון_ארנונה", "arnona_bill"):
        from app.documents.schemas import ArnonaBillExtraction
        return ArnonaBillExtraction(
            source_url       = url,
            file_name        = label,
            state            = ExtractionState.MOCK,
            confidence       = 0.0,
            extracted_by     = "mock",
            extraction_notes = "⚠️ חילוץ חשבון ארנונה לא מוגדר — נדרש אימות ידני",
        )

    # ── Default: not handled ──────────────────────────────────────────────────
    return BaseExtraction(
        doc_type         = label,
        source_url       = url,
        state            = ExtractionState.NOT_ATTEMPTED,
        extraction_notes = f"אין מנתח מסמכים עבור '{label}'",
    )
