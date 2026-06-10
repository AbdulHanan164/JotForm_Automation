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


def _load_yaml_field_map() -> tuple[dict[str, dict], list[str]]:
    """
    Load field map from YAML config.

    Returns:
      (field_map_dict, placeholder_labels)
      field_map_dict: {jotform_id: {label, section, type}}
      placeholder_labels: list of label strings that are still PLACEHOLDER
    """
    try:
        import yaml  # type: ignore
    except ImportError:
        logger.warning(
            "PyYAML not installed — field map YAML not loaded. "
            "Run: pip install pyyaml"
        )
        return {}, []

    if not _YAML_CONFIG.exists():
        logger.warning(
            "Field map config not found: %s — "
            "using Python fallback defaults.",
            _YAML_CONFIG,
        )
        return {}, []

    try:
        with _YAML_CONFIG.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as exc:
        logger.error("Failed to parse field map YAML %s: %s", _YAML_CONFIG, exc)
        return {}, []

    field_map: dict[str, dict] = {}
    placeholders: list[str] = []

    for entry in data.get("fields", []):
        jfid    = entry.get("jotform_id", "")
        label   = entry.get("label", "")
        section = entry.get("section", "other")
        ftype   = entry.get("type", "text")
        verified = entry.get("verified", False)

        if not jfid or not label:
            continue

        field_map[jfid] = {
            "label":    label,
            "section":  section,
            "type":     ftype,
            "verified": verified,
        }

        if not verified:
            placeholders.append(label)

    return field_map, placeholders


# ── Build the field map ───────────────────────────────────────────────────────

_YAML_MAP, _PLACEHOLDER_LABELS = _load_yaml_field_map()

# v0.8.2: Python fallback defaults removed — they held fictional placeholder
# IDs for the retired form 251955479892982 and inflated the unverified count.
# config/field_maps/arnona.yaml (real production IDs, verified against
# submission MZK6852) is now the single source of truth.
_PYTHON_DEFAULTS: dict[str, dict] = {}

# YAML overrides Python defaults for the same jotform_id.
# This means: update the YAML to update field IDs; Python defaults are fallback.
FIELD_MAP: dict[str, dict[str, Any]] = {**_PYTHON_DEFAULTS, **_YAML_MAP}


# ── Startup validation ────────────────────────────────────────────────────────

def check_field_map_status() -> dict[str, Any]:
    """
    Returns a status report on the field map.
    Called on startup and by GET /admin/fieldmap/arnona/status.
    """
    total     = len(FIELD_MAP)
    verified  = sum(1 for v in FIELD_MAP.values() if v.get("verified", False))
    unverified = total - verified

    if unverified > 0:
        logger.warning(
            "FIELD MAP: %d/%d fields are still PLACEHOLDER IDs. "
            "Submissions will not parse correctly until real IDs are set. "
            "Run GET /discover/{submission_id} to get real IDs, then update "
            "config/field_maps/arnona.yaml.",
            unverified, total,
        )
    else:
        logger.info("Field map: all %d fields verified ✓", total)

    return {
        "total":      total,
        "verified":   verified,
        "unverified": unverified,
        "unverified_labels": _PLACEHOLDER_LABELS,
        "config_file": str(_YAML_CONFIG),
        "config_exists": _YAML_CONFIG.exists(),
        "status": "ok" if unverified == 0 else "placeholder_ids_present",
    }


# ── Required documents per service type ──────────────────────────────────────
REQUIRED_DOCS: dict[str, list[str]] = {
    "ארנונה":  ["תעודת_זהות", "חוזה_שכירות", "חתימה"],
    "חשמל":    ["תעודת_זהות", "חוזה_שכירות", "חתימה"],
    "מים":     ["תעודת_זהות", "חוזה_שכירות", "חתימה"],
    "default": ["תעודת_זהות", "חוזה_שכירות", "חתימה"],
}
