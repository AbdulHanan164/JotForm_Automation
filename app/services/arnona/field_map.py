"""
Field map for form 251955479892982 — "העברת חשבון ארנונה".

v0.6 CHANGE: Field IDs are now loaded from config/field_maps/arnona.yaml
instead of being hardcoded here. This lets the operator update field IDs
without touching Python code.

WORKFLOW TO UPDATE FIELD IDs:
  1. Receive one real JotForm submission.
  2. GET /discover/{submission_id} — see all raw field IDs.
  3. Open config/field_maps/arnona.yaml.
  4. Replace placeholder jotform_id values with real ones.
  5. Set verified: true for each confirmed field.
  6. Restart the server.

  OR use POST /admin/sync/251955479892982 with JOTFORM_API_KEY set.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("webhook")

# ── Section constants ─────────────────────────────────────────────────────────
S_BASIC     = "basic"
S_CUSTOMER  = "customer"
S_PARTNER   = "partner"
S_OUTGOING  = "outgoing"
S_LANDLORD  = "landlord"
S_PROPERTY  = "property"
S_ARNONA    = "arnona"
S_WATER     = "water"
S_DOCS      = "documents"
S_PAYMENT   = "payment"
S_SYSTEM    = "system"
S_FHS       = "fhs"   # JotForm computed normalization columns (74-92 in Google Sheet)

# ── Config path ───────────────────────────────────────────────────────────────
_YAML_CONFIG = Path("config/field_maps/arnona.yaml")


def _is_fabricated_id(jotform_id: str) -> bool:
    """True for IDs that can never match a real webhook field (e.g.
    ``fhs_partner_email_placeholder``). Such entries must NOT enter FIELD_MAP:
    besides being useless for parsing, they leak into
    ``evaluator.build_label_visibility`` as permanently-visible passive QIDs
    and corrupt label-visibility decisions."""
    lowered = jotform_id.lower()
    return any(marker in lowered for marker in ("placeholder", "here", "todo"))


def _load_yaml_field_map() -> tuple[dict[str, dict], list[str], list[dict]]:
    """
    Load field map from YAML config — the single mapping layer.

    Returns:
      (field_map_dict, placeholder_labels, unresolved)
      field_map_dict:     {jotform_id: {label, section, type, verified}} —
                          only entries whose ID could plausibly match a real
                          webhook field (fabricated IDs are quarantined)
      placeholder_labels: labels still awaiting verification (incl. quarantined)
      unresolved:         full entries quarantined or unverified, for
                          /admin/fieldmap status and docs/UNRESOLVED_MAPPINGS.md
    """
    try:
        import yaml  # type: ignore
    except ImportError:
        logger.warning(
            "PyYAML not installed — field map YAML not loaded. "
            "Run: pip install pyyaml"
        )
        return {}, [], []

    if not _YAML_CONFIG.exists():
        logger.warning("Field map config not found: %s", _YAML_CONFIG)
        return {}, [], []

    try:
        with _YAML_CONFIG.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as exc:
        logger.error("Failed to parse field map YAML %s: %s", _YAML_CONFIG, exc)
        return {}, [], []

    field_map: dict[str, dict] = {}
    placeholders: list[str] = []
    unresolved: list[dict] = []

    for entry in data.get("fields", []):
        jfid    = entry.get("jotform_id", "")
        label   = entry.get("label", "")
        section = entry.get("section", "other")
        ftype   = entry.get("type", "text")
        verified = entry.get("verified", False)

        if not jfid or not label:
            continue

        if not verified:
            placeholders.append(label)
            unresolved.append({
                "jotform_id": jfid, "label": label, "section": section,
                "type": ftype, "fabricated": _is_fabricated_id(jfid),
            })

        if _is_fabricated_id(jfid):
            continue   # quarantined — documented, never matched

        field_map[jfid] = {
            "label":    label,
            "section":  section,
            "type":     ftype,
            "verified": verified,
        }

    return field_map, placeholders, unresolved


# ── Build the field map ───────────────────────────────────────────────────────

_YAML_MAP, _PLACEHOLDER_LABELS, UNRESOLVED_MAPPINGS = _load_yaml_field_map()

# config/field_maps/arnona.yaml is the single source of truth for field IDs.
FIELD_MAP: dict[str, dict[str, Any]] = dict(_YAML_MAP)


# ── Startup validation ────────────────────────────────────────────────────────

def check_field_map_status() -> dict[str, Any]:
    """
    Returns a status report on the field map.
    Called on startup and by GET /admin/fieldmap/arnona/status.
    """
    active     = len(FIELD_MAP)
    unverified = len(UNRESOLVED_MAPPINGS)
    total      = active + sum(1 for u in UNRESOLVED_MAPPINGS if u["fabricated"])
    verified   = sum(1 for v in FIELD_MAP.values() if v.get("verified", False))

    if unverified > 0:
        logger.warning(
            "FIELD MAP: %d mapping(s) unresolved (%d fabricated IDs quarantined). "
            "See docs/UNRESOLVED_MAPPINGS.md. Run GET /discover/{submission_id} "
            "to get real IDs, then update config/field_maps/arnona.yaml.",
            unverified,
            sum(1 for u in UNRESOLVED_MAPPINGS if u["fabricated"]),
        )
    else:
        logger.info("Field map: all %d fields verified ✓", total)

    return {
        "total":      total,
        "verified":   verified,
        "unverified": unverified,
        "unverified_labels": _PLACEHOLDER_LABELS,
        "unresolved": UNRESOLVED_MAPPINGS,
        "config_file": str(_YAML_CONFIG),
        "config_exists": _YAML_CONFIG.exists(),
        "status": "ok" if unverified == 0 else "placeholder_ids_present",
    }


# v0.7: REQUIRED_DOCS removed — it was dead config referenced by nothing.
# Document requirements live in app/rules/requirements.py (DOC_RULES).
