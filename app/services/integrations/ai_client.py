"""
AI integration stub (OpenAI / NVIDIA).

Future use cases:
  - Classify move type from free-text fields
  - Detect anomalies in submitted data
  - Generate follow-up email drafts
  - Extract missing info from uploaded documents (OCR + LLM)

The summary dict is designed to be a clean LLM prompt context —
all fields are labelled in English with no raw JotForm IDs.
"""
from typing import Any


def classify_submission(summary: dict[str, Any]) -> dict:
    """Use LLM to classify submission intent and priority."""
    raise NotImplementedError

def generate_followup_email(summary: dict[str, Any]) -> str:
    """Generate a follow-up email for missing documents."""
    raise NotImplementedError

def extract_from_document(image_base64: str) -> dict:
    """OCR + LLM extraction from an uploaded ID photo or contract."""
    raise NotImplementedError
