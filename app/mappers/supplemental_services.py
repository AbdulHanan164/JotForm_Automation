"""
Supplemental services — models, parser, validators, serializers (v0.7).

Before v0.7 the system had NO concept of add-on services: an "address update"
purchased with the transfer landed in ``_unmapped`` and vanished — the
operator never saw it (production bug report #3, 2026-07). This module gives
supplemental services a first-class, deterministic path:

  parse   — scan the parsed submission (mapped fields, package description,
            payment products, _unmapped bucket) for known service tokens
  model   — SupplementalService dataclass, JSON-safe
  validate— structural sanity checks for the parsed list
  serialize — to_dict()/from_dict() round-trip, embedded in
            BusinessSubmission.to_dict() → review-queue JSON → dashboard

Detection is token-based and DATA-DRIVEN: adding a new supplemental service is
one REGISTRY entry, no code. Values are matched with the same normalization
used by the transaction classifier (bidi marks, punctuation, whitespace).

Field IDs for the ancillary-services multi-select (q568/q569/q630 →
שירותים_נוספים) were verified against all 58 production submissions from the
2026-07 server backup — see config/field_maps/arnona.yaml.

TODO (requires .env / external integration — see docs/INTEGRATION_TODO.md):
  * Fulfillment integrations (e.g. actually submitting the address update to
    the authority) — out of scope for the webhook service today.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.rules.transaction import normalize


# ── Registry ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ServiceDefinition:
    key:      str
    label_he: str
    label_en: str
    tokens:   tuple[str, ...]   # normalized-substring detection tokens


REGISTRY: tuple[ServiceDefinition, ...] = (
    ServiceDefinition(
        key="address_update",
        label_he="עדכון כתובת",
        label_en="Address update",
        tokens=("עדכון כתובת", "שינוי כתובת", "address update"),
    ),
    ServiceDefinition(
        key="mail_forwarding",
        label_he="העברת דואר",
        label_en="Mail forwarding",
        tokens=("העברת דואר", "דואר ישראל", "mail forwarding"),
    ),
    ServiceDefinition(
        key="gas_transfer",
        label_he="העברת גז",
        label_en="Gas transfer",
        tokens=("העברת גז", "חברת גז", "gas transfer"),
    ),
    ServiceDefinition(
        key="internet_tv",
        label_he="אינטרנט/טלוויזיה",
        label_en="Internet / TV",
        tokens=("אינטרנט", "טלוויזיה", "internet"),
    ),
)

_BY_KEY = {d.key: d for d in REGISTRY}


# ── Model ─────────────────────────────────────────────────────────────────────

@dataclass
class SupplementalService:
    key:       str
    label_he:  str = ""
    label_en:  str = ""
    selected:  bool = True
    source:    str = ""     # where it was detected (field label / "_unmapped:qid")
    raw_value: str = ""     # the original answer text

    def to_dict(self) -> dict[str, Any]:
        return {
            "key":       self.key,
            "label_he":  self.label_he,
            "label_en":  self.label_en,
            "selected":  self.selected,
            "source":    self.source,
            "raw_value": self.raw_value,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SupplementalService":
        return cls(
            key       = d.get("key", ""),
            label_he  = d.get("label_he", ""),
            label_en  = d.get("label_en", ""),
            selected  = bool(d.get("selected", True)),
            source    = d.get("source", ""),
            raw_value = d.get("raw_value", ""),
        )


# ── Parser ────────────────────────────────────────────────────────────────────

# Answers that NAME a service while declining it. The production form's
# ancillary multi-select offers explicit decline options like
# "לא תודה - עדכון כתובת בתעודת זהות" — validated against the 2026-07
# production corpus (20/58 submissions declined this way).


def _is_negated(norm: str) -> bool:
    """True for answers that decline the named service.

    Word-boundary aware: "אין"/"ללא"/"לא" must be whole words — a bare
    substring test would match "אין" inside "אינטרנט" and kill legitimate
    internet/TV detection.
    """
    padded = f" {norm} "
    return "לא תודה" in norm or any(f" {w} " in padded for w in ("ללא", "אין", "לא"))


def _candidate_texts(parsed: dict[str, Any]) -> list[tuple[str, str]]:
    """(source, text) pairs to scan, most-authoritative first.

    ONLY selection-type sources are scanned. Scanning ``_unmapped`` was tried
    and REMOVED after historical replay over 58 production submissions showed
    a 100% false-positive rate: JotForm posts static text-widget content
    (e.g. q620 "עדכון כתובת בתעודת זהות 79 ₪", a price label) with every
    submission, purchased or not. The real answer is the mapped
    שירותים_נוספים multi-select (q568/q569/q630 in arnona.yaml).
    """
    out: list[tuple[str, str]] = []
    basic   = parsed.get("basic", {}) or {}
    payment = parsed.get("payment", {}) or {}

    # 1. The dedicated ancillary-services multi-select (verified field IDs)
    dedicated = basic.get("שירותים_נוספים")
    if dedicated:
        vals = dedicated if isinstance(dedicated, list) else [dedicated]
        out.extend(("basic.שירותים_נוספים", str(v)) for v in vals if v)

    # 2. Selected-services multi-select + package description
    services = basic.get("שירותים_נבחרים", [])
    if isinstance(services, str):
        services = [services]
    out.extend(("basic.שירותים_נבחרים", str(s)) for s in services or [] if s)
    if payment.get("שם_שירות"):
        out.append(("payment.שם_שירות", str(payment["שם_שירות"])))
    if payment.get("מוצרים"):
        out.append(("payment.מוצרים", str(payment["מוצרים"])))

    return out


def parse_supplemental(parsed: dict[str, Any]) -> list[SupplementalService]:
    """Detect supplemental services in a parsed submission. Deterministic."""
    found: dict[str, SupplementalService] = {}
    for source, text in _candidate_texts(parsed):
        norm = normalize(text).lower()
        if not norm:
            continue
        if _is_negated(norm):
            continue   # "לא תודה - עדכון כתובת..." names the service to DECLINE it
        for definition in REGISTRY:
            if definition.key in found:
                continue
            if any(normalize(tok).lower() in norm for tok in definition.tokens):
                found[definition.key] = SupplementalService(
                    key       = definition.key,
                    label_he  = definition.label_he,
                    label_en  = definition.label_en,
                    selected  = True,
                    source    = source,
                    raw_value = str(text)[:200],
                )
    return list(found.values())


# ── Validators ────────────────────────────────────────────────────────────────

def validate_supplemental(services: list[SupplementalService]) -> list[str]:
    """Structural sanity checks; returns a list of issue strings (empty = ok)."""
    issues: list[str] = []
    seen: set[str] = set()
    for svc in services:
        if not svc.key:
            issues.append("supplemental service with empty key")
            continue
        if svc.key not in _BY_KEY:
            issues.append(f"unknown supplemental service key: {svc.key}")
        if svc.key in seen:
            issues.append(f"duplicate supplemental service: {svc.key}")
        seen.add(svc.key)
    return issues


# ── Serializers ───────────────────────────────────────────────────────────────

def serialize(services: list[SupplementalService]) -> list[dict[str, Any]]:
    return [s.to_dict() for s in services]


def deserialize(raw: Any) -> list[SupplementalService]:
    if not isinstance(raw, list):
        return []
    return [SupplementalService.from_dict(d) for d in raw if isinstance(d, dict)]
