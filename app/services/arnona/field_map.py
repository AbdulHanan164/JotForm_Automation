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

# Python fallback defaults (used when YAML is absent or a field is missing)
_PYTHON_DEFAULTS: dict[str, dict] = {
    "q3_moveType3":      {"label": "סוג_מעבר",          "section": S_BASIC,    "type": "select"},
    "q4_cityName4":      {"label": "עיר",                "section": S_BASIC,    "type": "text"},
    "q5_services5":      {"label": "שירותים_נבחרים",     "section": S_BASIC,    "type": "multi"},
    "q6_moveOutDate6":   {"label": "תאריך_יציאה",        "section": S_BASIC,    "type": "date"},
    "q7_moveInDate7":    {"label": "תאריך_כניסה",        "section": S_BASIC,    "type": "date"},
    "q8_leaseEnd8":      {"label": "תאריך_סיום_חוזה",    "section": S_BASIC,    "type": "date"},
    "q9_transferDate9":  {"label": "תאריך_העברה",        "section": S_BASIC,    "type": "date"},
    "q10_personType10":  {"label": "סוג_לקוח",           "section": S_BASIC,    "type": "select"},
    "q21_firstName21":   {"label": "שם_פרטי",            "section": S_CUSTOMER, "type": "text"},
    "q22_lastName22":    {"label": "שם_משפחה",            "section": S_CUSTOMER, "type": "text"},
    "q23_phone23":       {"label": "טלפון",               "section": S_CUSTOMER, "type": "phone"},
    "q24_email24":       {"label": "אימייל",              "section": S_CUSTOMER, "type": "email"},
    "q25_idNumber25":    {"label": "תעודת_זהות",          "section": S_CUSTOMER, "type": "id_num"},
    "q104_input104":     {"label": "שם_פרטי",            "section": S_PARTNER,  "type": "text"},
    "q235_input235":     {"label": "שם_משפחה",            "section": S_PARTNER,  "type": "text"},
    "q103_input103":     {"label": "טלפון",               "section": S_PARTNER,  "type": "phone"},
    "q105_email105":     {"label": "אימייל",              "section": S_PARTNER,  "type": "email"},
    "q106_idNumber106":  {"label": "תעודת_זהות",          "section": S_PARTNER,  "type": "id_num"},
    "q30_outFirstName30":{"label": "שם_פרטי",            "section": S_OUTGOING, "type": "text"},
    "q31_outLastName31": {"label": "שם_משפחה",            "section": S_OUTGOING, "type": "text"},
    "q32_outId32":       {"label": "תעודת_זהות",          "section": S_OUTGOING, "type": "id_num"},
    "q33_outPhone33":    {"label": "טלפון",               "section": S_OUTGOING, "type": "phone"},
    "q34_outEmail34":    {"label": "אימייל",              "section": S_OUTGOING, "type": "email"},
    "q40_ownerName40":   {"label": "שם_מלא",             "section": S_LANDLORD, "type": "text"},
    "q41_ownerPhone41":  {"label": "טלפון",               "section": S_LANDLORD, "type": "phone"},
    "q42_ownerEmail42":  {"label": "אימייל",              "section": S_LANDLORD, "type": "email"},
    "q43_ownerId43":     {"label": "תעודת_זהות",          "section": S_LANDLORD, "type": "id_num"},
    "q50_street50":      {"label": "רחוב",               "section": S_PROPERTY, "type": "text"},
    "q51_building51":    {"label": "בניין",              "section": S_PROPERTY, "type": "text"},
    "q52_apartment52":   {"label": "דירה",               "section": S_PROPERTY, "type": "text"},
    "q53_floor53":       {"label": "קומה",               "section": S_PROPERTY, "type": "text"},
    "q54_entrance54":    {"label": "כניסה",              "section": S_PROPERTY, "type": "text"},
    "q60_arnonaProperty60": {"label": "מספר_נכס",        "section": S_ARNONA,   "type": "text"},
    "q61_arnonaCust61":     {"label": "מספר_לקוח",       "section": S_ARNONA,   "type": "text"},
    "q62_arnonaId62":       {"label": "מספר_זיהוי_נכס",  "section": S_ARNONA,   "type": "text"},
    "q63_arnonaTenant63":   {"label": "מספר_חשבון_תושב", "section": S_ARNONA,   "type": "text"},
    "q64_arnonaCustomer64": {"label": "מספר_חשבון_לקוח", "section": S_ARNONA,   "type": "text"},
    "q70_waterProperty70":  {"label": "מספר_נכס",        "section": S_WATER,    "type": "text"},
    "q71_waterCust71":      {"label": "מספר_לקוח",       "section": S_WATER,    "type": "text"},
    "q80_idPhoto80":        {"label": "תעודת_זהות",      "section": S_DOCS,     "type": "file"},
    "q81_arnonaBill81":     {"label": "חשבון_ארנונה",    "section": S_DOCS,     "type": "file"},
    "q82_leaseContract82":  {"label": "חוזה_שכירות",    "section": S_DOCS,     "type": "file"},
    "q83_signature83":      {"label": "חתימה",           "section": S_DOCS,     "type": "signature"},
    "q84_tabu84":           {"label": "נסח_טאבו",        "section": S_DOCS,     "type": "file"},
    "q85_corpCert85":       {"label": "תעודת_התאגדות",   "section": S_DOCS,     "type": "file"},
    "q87_terms87":          {"label": "תנאים",           "section": S_DOCS,     "type": "bool"},
    "q90_amount90":         {"label": "סכום",            "section": S_PAYMENT,  "type": "text"},
    "q91_serviceName91":    {"label": "שם_שירות",        "section": S_PAYMENT,  "type": "text"},
    "q100_mzkId100":        {"label": "מזהה_מזכ",        "section": S_SYSTEM,   "type": "text"},
    "q101_refundId101":     {"label": "מזהה_החזר",       "section": S_SYSTEM,   "type": "text"},
    "q102_dealType102":     {"label": "סוג_עסקה",        "section": S_SYSTEM,   "type": "text"},
}

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
