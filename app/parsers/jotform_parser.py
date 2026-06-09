"""
JotForm multipart → clean Python dict pipeline.

Responsibilities:
  1. Extract envelope fields (submissionID, formID, formTitle, ip, username)
     from the top-level multipart fields.
  2. Extract and JSON-decode rawRequest.
  3. Apply the field map to produce a section-keyed dict.
  4. Separate document fields (base64 blobs) from text fields.
  5. Return a structured ParsedSubmission ready for the rule engine.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.parsers.field_maps.main_form import (
    FIELD_MAP,
    REQUIRED_DOCS,
    UTILITY_LABELS,
    S_META, S_CUSTOMER, S_PROPERTY, S_LEASE,
    S_SERVICES, S_PAYMENT, S_DOCS, S_OUTGOING, S_LANDLORD, S_SYSTEM,
)
from app.utils.hebrew import (
    clean_text, format_date, is_base64_image,
    safe_str, split_csv_field, strip_base64,
)

logger = logging.getLogger("webhook")


# ---------------------------------------------------------------------------
# Top-level envelope fields that live OUTSIDE rawRequest (in the multipart)
# ---------------------------------------------------------------------------
ENVELOPE_FIELDS = {
    "submissionID", "formID", "formTitle", "username",
    "ip", "type", "action", "webhookURL",
}


class ParsedSubmission:
    """
    Container produced by JotFormParser.parse().
    All downstream services (rule engine, storage, integrations) consume this.
    """

    def __init__(self):
        self.received_at: str = datetime.now(timezone.utc).isoformat()

        # Envelope
        self.submission_id: str = "unknown"
        self.form_id: str = ""
        self.form_title: str = ""
        self.username: str = ""
        self.submitter_ip: str = ""

        # Section-keyed clean data
        self.meta: dict[str, Any]     = {}
        self.customer: dict[str, Any] = {}
        self.property: dict[str, Any] = {}
        self.lease: dict[str, Any]    = {}
        self.services: dict[str, Any] = {}
        self.payment: dict[str, Any]  = {}
        self.documents: dict[str, Any]= {}
        self.outgoing_tenant: dict[str, Any] = {}
        self.landlord: dict[str, Any] = {}
        self.system: dict[str, Any]   = {}

        # Raw data kept for debugging / future AI
        self.raw_envelope: dict[str, Any] = {}
        self.raw_request: dict[str, Any]  = {}
        self.unmapped_fields: dict[str, Any] = {}

    # ── Section accessor by key ──────────────────────────────────────────
    def _section(self, key: str) -> dict:
        return {
            S_META:     self.meta,
            S_CUSTOMER: self.customer,
            S_PROPERTY: self.property,
            S_LEASE:    self.lease,
            S_SERVICES: self.services,
            S_PAYMENT:  self.payment,
            S_DOCS:     self.documents,
            S_OUTGOING: self.outgoing_tenant,
            S_LANDLORD: self.landlord,
            S_SYSTEM:   self.system,
        }.get(key, self.unmapped_fields)

    def to_dict(self) -> dict[str, Any]:
        return {
            "received_at":    self.received_at,
            "submission_id":  self.submission_id,
            "form_id":        self.form_id,
            "form_title":     self.form_title,
            "username":       self.username,
            "submitter_ip":   self.submitter_ip,
            "meta":           self.meta,
            "customer":       self.customer,
            "property":       self.property,
            "lease":          self.lease,
            "services":       self.services,
            "payment":        self.payment,
            "documents":      self.documents,
            "outgoing_tenant":self.outgoing_tenant,
            "landlord":       self.landlord,
            "system":         self.system,
            "unmapped_fields":self.unmapped_fields,
            "_raw": {
                "envelope":   self.raw_envelope,
                "raw_request":self.raw_request,
            },
        }


class JotFormParser:
    """
    Stateless parser — call parse(multipart_fields) to get a ParsedSubmission.
    """

    # ── Public entry point ───────────────────────────────────────────────
    @staticmethod
    def parse(multipart_fields: dict[str, Any]) -> ParsedSubmission:
        sub = ParsedSubmission()

        # 1 ── Extract envelope fields ──────────────────────────────────────
        JotFormParser._extract_envelope(sub, multipart_fields)

        # 2 ── Decode rawRequest ────────────────────────────────────────────
        raw_request = JotFormParser._decode_raw_request(multipart_fields)
        sub.raw_request = raw_request

        # 3 ── Map fields to sections ───────────────────────────────────────
        JotFormParser._map_fields(sub, raw_request)

        # 4 ── Post-process each section ────────────────────────────────────
        JotFormParser._post_process(sub)

        logger.info(
            "Parsed submission %s | form=%s | customer=%s %s",
            sub.submission_id,
            sub.form_id,
            sub.customer.get("first_name", ""),
            sub.customer.get("last_name", ""),
        )
        return sub

    # ── Step 1: envelope ────────────────────────────────────────────────
    @staticmethod
    def _extract_envelope(sub: ParsedSubmission, fields: dict) -> None:
        sub.submission_id = clean_text(fields.get("submissionID", "unknown")) or "unknown"
        sub.form_id       = clean_text(fields.get("formID", ""))
        sub.form_title    = clean_text(fields.get("formTitle", ""))
        sub.username      = clean_text(fields.get("username", ""))
        sub.submitter_ip  = clean_text(fields.get("ip", ""))
        sub.raw_envelope  = {k: v for k, v in fields.items() if k in ENVELOPE_FIELDS}

    # ── Step 2: decode rawRequest ───────────────────────────────────────
    @staticmethod
    def _decode_raw_request(fields: dict) -> dict[str, Any]:
        raw = fields.get("rawRequest", "{}")
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                logger.warning("rawRequest JSON decode failed: %s", exc)
                return {}
        if isinstance(raw, dict):
            return raw
        return {}

    # ── Step 3: map fields ──────────────────────────────────────────────
    @staticmethod
    def _map_fields(sub: ParsedSubmission, raw: dict) -> None:
        for field_id, value in raw.items():
            mapping = FIELD_MAP.get(field_id)
            if mapping is None:
                # Store unmapped for future reference
                if not is_base64_image(safe_str(value)):
                    sub.unmapped_fields[field_id] = value
                continue

            label   = mapping["label"]
            section = mapping["section"]
            ftype   = mapping["type"]

            # Normalise value by type
            if ftype == "date":
                value = format_date(value)
            elif ftype in ("image", "signature"):
                # Keep a metadata stub, not the raw base64
                if is_base64_image(safe_str(value)):
                    value = {
                        "type":        ftype,
                        "placeholder": strip_base64(safe_str(value)),
                        "present":     True,
                    }
                else:
                    value = {"type": ftype, "present": False}
            elif ftype == "multi":
                if isinstance(value, list):
                    value = [clean_text(str(v)) for v in value]
                else:
                    value = split_csv_field(safe_str(value))
            elif ftype == "bool":
                value = str(value).lower() in ("accepted", "הוסכם", "true", "1", "yes")
            else:
                value = clean_text(safe_str(value))

            sub._section(section)[label] = value

    # ── Step 4: post-process ────────────────────────────────────────────
    @staticmethod
    def _post_process(sub: ParsedSubmission) -> None:
        # Promote submission_id from meta if not found in envelope
        if sub.submission_id == "unknown" and sub.meta.get("unique_id"):
            sub.submission_id = sub.meta["unique_id"]

        # Parse utilities into a structured dict
        utilities_raw = sub.services.get("utilities_text", "")
        utilities_list = sub.services.get("utilities_list", [])
        source = utilities_list if utilities_list else split_csv_field(utilities_raw)
        parsed_utils: dict[str, bool] = {}
        for key_he, key_en in UTILITY_LABELS.items():
            parsed_utils[key_en] = any(key_he in str(v) for v in source)
        sub.services["utilities"] = parsed_utils

        # Normalise amount to float
        try:
            sub.payment["amount"] = float(sub.payment.get("amount", 0))
        except (ValueError, TypeError):
            sub.payment["amount"] = 0.0

        # Build full_name convenience fields
        if sub.customer.get("first_name") and sub.customer.get("last_name"):
            sub.customer["full_name"] = (
                f"{sub.customer['first_name']} {sub.customer['last_name']}"
            )
        if sub.outgoing_tenant.get("first_name") and sub.outgoing_tenant.get("last_name"):
            sub.outgoing_tenant["full_name"] = (
                f"{sub.outgoing_tenant['first_name']} {sub.outgoing_tenant['last_name']}"
            )
        if sub.landlord.get("first_name") and sub.landlord.get("last_name"):
            sub.landlord["full_name"] = (
                f"{sub.landlord['first_name']} {sub.landlord['last_name']}"
            )
