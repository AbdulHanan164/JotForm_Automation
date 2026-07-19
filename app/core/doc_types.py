"""
Canonical document vocabulary — the ONE source of truth for document types.

Before v0.7 the system had two vocabularies:

  * 6 "requirement" types (storage.DOC_TYPES / missing_detector / manifests):
      id_photo, lease_contract, signature, arnona_bill, corp_cert, tabu
  * 13 "classifier" types (FilenameClassifier / Gemini / OpenAI vision):
      the 6 above (with tabu spelled "tabu_document") plus sale_contract,
      water_bill, water_meter, electricity_bill, electricity_meter,
      gas_bill, gas_meter

A tabu uploaded via the Missing-Documents form was stored in the manifest as
"tabu_document" while every consumer looked up "tabu" — so the document was
re-requested forever. This module fixes that permanently:

  * CANONICAL_TYPES        — every type the system may store or reason about.
  * REQUIREMENT_TYPES      — the subset that can appear as a REQUIREMENT.
  * ALIASES                — classifier/legacy spelling → canonical spelling.
  * SATISFIED_BY           — requirement type → set of canonical types whose
                             presence satisfies it (e.g. a sale contract
                             satisfies the "contract" requirement).
  * canonicalize()         — normalize any spelling to the canonical one.
  * types_satisfying()     — all manifest keys that resolve a requirement.

Backward compatibility: manifests written before v0.7 may contain alias keys
("tabu_document", ...). Consumers must therefore always match through
`types_satisfying()` / `canonicalize()` rather than raw string equality.
"""
from __future__ import annotations

# ── Canonical types ───────────────────────────────────────────────────────────
# type: (Hebrew label, filename stem)
CANONICAL_TYPES: dict[str, tuple[str, str]] = {
    # Requirement-bearing types (may be demanded from the customer)
    "id_photo":          ("תעודת_זהות",     "id_photo"),
    "lease_contract":    ("חוזה_שכירות",    "lease"),
    "sale_contract":     ("חוזה_מכר",       "sale_contract"),
    "signature":         ("חתימה",          "signature"),
    "arnona_bill":       ("חשבון_ארנונה",   "arnona_bill"),
    "corp_cert":         ("תעודת_התאגדות",  "corporation_certificate"),
    "tabu":              ("נסח_טאבו",       "tabu"),
    # Recognized supplemental/utility types (never demanded by the arnona
    # requirement table today, but classified, stored, and displayed)
    "water_bill":        ("חשבון_מים",      "water_bill"),
    "water_meter":       ("קריאת_מונה_מים", "water_meter"),
    "electricity_bill":  ("חשבון_חשמל",     "electricity_bill"),
    "electricity_meter": ("קריאת_מונה_חשמל", "electricity_meter"),
    "gas_bill":          ("חשבון_גז",       "gas_bill"),
    "gas_meter":         ("קריאת_מונה_גז",  "gas_meter"),
}

# Types that the requirement engine may demand (subset of CANONICAL_TYPES).
REQUIREMENT_TYPES: tuple[str, ...] = (
    "id_photo", "lease_contract", "sale_contract",
    "signature", "arnona_bill", "corp_cert", "tabu",
)

# The 6 types the operator summary has always displayed (kept stable for the
# review-queue JSON shape; supplemental types are shown separately).
SUMMARY_TYPES: tuple[str, ...] = (
    "id_photo", "lease_contract", "signature", "arnona_bill", "corp_cert", "tabu",
)

# ── Alias resolution ──────────────────────────────────────────────────────────
# Any spelling a classifier, an old manifest, or legacy code may produce.
ALIASES: dict[str, str] = {
    "tabu_document":       "tabu",
    "corporation_certificate": "corp_cert",
    "lease":               "lease_contract",
    "rental_contract":     "lease_contract",
    "purchase_contract":   "sale_contract",
}

# requirement type → canonical types whose presence satisfies it.
# A signed sale contract proves entitlement exactly like a lease does, so the
# "contract" requirement accepts either.
SATISFIED_BY: dict[str, frozenset[str]] = {
    "id_photo":       frozenset({"id_photo"}),
    "lease_contract": frozenset({"lease_contract", "sale_contract"}),
    "sale_contract":  frozenset({"sale_contract", "lease_contract"}),
    "signature":      frozenset({"signature"}),
    "arnona_bill":    frozenset({"arnona_bill"}),
    "corp_cert":      frozenset({"corp_cert"}),
    "tabu":           frozenset({"tabu"}),
}

_HEBREW_TO_TYPE: dict[str, str] = {heb: ct for ct, (heb, _) in CANONICAL_TYPES.items()}


# ── Public helpers ────────────────────────────────────────────────────────────

def canonicalize(doc_type: str) -> str:
    """Normalize any classifier/legacy/Hebrew spelling to the canonical type.

    Returns "" for unknown/empty input (caller decides how to handle unmapped).
    """
    if not doc_type:
        return ""
    t = str(doc_type).strip()
    if t in CANONICAL_TYPES:
        return t
    if t in ALIASES:
        return ALIASES[t]
    return _HEBREW_TO_TYPE.get(t, "")


def is_valid_type(doc_type: str) -> bool:
    """True if the spelling resolves to a canonical type."""
    return bool(canonicalize(doc_type))


def hebrew_label(doc_type: str) -> str:
    entry = CANONICAL_TYPES.get(canonicalize(doc_type))
    return entry[0] if entry else ""


def filename_stem(doc_type: str) -> str:
    entry = CANONICAL_TYPES.get(canonicalize(doc_type))
    return entry[1] if entry else (doc_type or "document")


def types_satisfying(requirement_type: str) -> frozenset[str]:
    """All canonical types whose presence satisfies `requirement_type`.

    Manifest lookups must check every spelling of every satisfying type —
    use `manifest_keys_satisfying()` for that.
    """
    req = canonicalize(requirement_type)
    return SATISFIED_BY.get(req, frozenset({req} if req else set()))


def manifest_keys_satisfying(requirement_type: str) -> frozenset[str]:
    """Every raw manifest key (canonical OR alias spelling) that satisfies
    `requirement_type`. Covers manifests written before alias normalization."""
    satisfying = types_satisfying(requirement_type)
    keys = set(satisfying)
    for alias, canonical in ALIASES.items():
        if canonical in satisfying:
            keys.add(alias)
    return frozenset(keys)
