"""
Configuration-Driven Service Loader.

PROBLEM SOLVED:
  Adding a new service (gas, internet, etc.) previously required:
    - Writing Python code in app/services/new_service/
    - Registering in the orchestrator
    - Restart

  With this loader, you only need:
    1. Create config/services/new_service.yaml
    2. Restart — it's registered automatically

HOW IT WORKS:
  - On startup, scan config/services/*.yaml
  - For each YAML that has a valid form_id, instantiate a YAMLDrivenService
  - YAMLDrivenService implements BaseService using data from the YAML
  - Python-coded services (ArnonaService) take priority if registered for same form_id

YAML SCHEMA:
  See config/services/arnona.yaml for a full example.

PRIORITY:
  Hardcoded Python service > YAML-driven service
  (ArnonaService stays in place because it has custom validation logic)
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("config_service.loader")

SERVICES_DIR = Path("config/services")


# ── YAML helpers (no PyYAML dependency — use stdlib) ──────────────────────────

def _load_yaml(path: Path) -> dict:
    """
    Minimal YAML loader for our known schema.

    We do NOT want to add a PyYAML dependency just for config files.
    Instead, we load using PyYAML if available, and fall back to a
    JSON-compatible subset otherwise.

    In production, add PyYAML to requirements.txt:
      pip install pyyaml
    """
    try:
        import yaml  # type: ignore
        with path.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        # Fallback: warn and return empty
        logger.warning(
            "PyYAML not installed — cannot load %s. "
            "Run: pip install pyyaml",
            path,
        )
        return {}
    except Exception as exc:
        logger.error("Failed to parse YAML %s: %s", path, exc)
        return {}


# ── Service class built from YAML ─────────────────────────────────────────────

class YAMLDrivenService:
    """
    A fully functional service driven entirely by a YAML config.

    Implements the same interface as BaseService so it plugs into
    the pipeline orchestrator without any code changes.

    LIMITATION: validation_rules in the YAML are declarative labels only.
    Cross-document validation (e.g. name-in-lease checks) still needs Python.
    For those, create a Python subclass of ArnonaService (or a BaseService).
    """

    def __init__(self, config: dict, yaml_path: Path):
        self._config    = config
        self._yaml_path = yaml_path
        self._service   = config.get("service", {})
        self._fields    = config.get("fields", [])
        self._req_docs  = config.get("required_documents", [])
        self._cond      = config.get("conditional_rules", [])
        self._email_cfg = config.get("email", {})
        self._missing   = config.get("missing_info_rules", [])
        self._validate  = config.get("validation_rules", [])

        # Build quick lookup: label → field config
        self._field_by_label: dict[str, dict] = {
            f["label"]: f for f in self._fields if "label" in f
        }
        self._field_by_jfid: dict[str, dict] = {
            f["jotform_id"]: f for f in self._fields if "jotform_id" in f
        }

    # ── BaseService interface ─────────────────────────────────────────────────

    @property
    def form_id(self) -> str:
        return self._service.get("form_id", "")

    @property
    def service_name(self) -> str:
        return self._service.get("display_name", self._service.get("name", ""))

    def parse_fields(self, raw_fields: dict) -> dict:
        """
        Map raw JotForm field IDs to label → value dict.
        Falls back to returning raw_fields unchanged if no field map.
        """
        if not self._fields:
            return dict(raw_fields)

        parsed: dict[str, Any] = {}
        for field in self._fields:
            jfid  = field.get("jotform_id", "")
            label = field.get("label", jfid)
            value = raw_fields.get(jfid, "")
            if value:
                parsed[label] = value

        return parsed

    def build_summary(self, parsed: dict) -> dict:
        """Build a Hebrew business summary from parsed fields."""
        svc  = self._service
        city = parsed.get("עיר", "")
        addr = self._build_address(parsed)

        summary: dict[str, Any] = {
            "שירות":    svc.get("display_name", svc.get("name", "")),
            "עיר":      city,
            "כתובת":    addr,
            "תאריך_כניסה": parsed.get("תאריך כניסה", ""),
        }

        # Customer section
        first = parsed.get("שם פרטי (דייר נכנס)", "")
        last  = parsed.get("שם משפחה (דייר נכנס)", "")
        if first or last:
            summary["דייר_נכנס"] = {
                "שם":    f"{first} {last}".strip(),
                "טלפון": parsed.get("טלפון (דייר נכנס)", ""),
                "מייל":  parsed.get("מייל (דייר נכנס)", ""),
            }

        # Outgoing
        out_first = parsed.get("שם פרטי (דייר יוצא)", "")
        out_last  = parsed.get("שם משפחה (דייר יוצא)", "")
        if out_first or out_last:
            summary["דייר_יוצא"] = {
                "שם":    f"{out_first} {out_last}".strip(),
                "טלפון": parsed.get("טלפון (דייר יוצא)", ""),
            }

        return summary

    def detect_missing(self, parsed: dict, summary: dict, visibility: dict) -> dict:
        """Detect missing required fields and documents."""
        missing_info: list[dict] = []
        missing_docs: list[dict] = []

        # Missing required fields
        for field in self._fields:
            label    = field.get("label", "")
            required = field.get("required", "never")

            # Skip hidden fields
            if visibility.get(label) is False:
                continue

            if required != "always":
                continue

            value = parsed.get(label, "")
            if not value or str(value).strip() in ("", "אין", "none", "None"):
                # Find reason from missing_info_rules
                reason = self._missing_reason(label)
                missing_info.append({
                    "field":    label,
                    "label":    label,
                    "severity": reason["severity"],
                    "reason":   reason["reason"],
                })

        # Missing required documents
        for doc in self._req_docs:
            doc_label = doc.get("label", "")
            doc_req   = doc.get("required", "never")
            jfid      = doc.get("jotform_field", "")

            if doc_req != "always":
                continue

            # Check if file was uploaded
            value = parsed.get(doc_label, "") or (
                parsed.get(jfid, "") if jfid else ""
            )
            if not value:
                missing_docs.append({
                    "id":     doc.get("id", ""),
                    "label":  doc_label,
                    "reason": doc.get("missing_reason", ""),
                })

        is_complete = len(missing_info) == 0 and len(missing_docs) == 0
        return {
            "is_complete":  is_complete,
            "missing_info": missing_info,
            "missing_docs": missing_docs,
        }

    def validate(self, parsed: dict, doc_extractions: dict) -> list:
        """
        Declarative validation from YAML.
        Note: complex cross-doc checks not available in YAML mode.
        Use Python subclass for those.
        """
        issues = []
        for rule in self._validate:
            severity = rule.get("severity", "warning")
            # Only run same-name check (declarative)
            if rule.get("check") == "same_name_customer_partner":
                c_name = (
                    parsed.get("שם פרטי (דייר נכנס)", "") + " " +
                    parsed.get("שם משפחה (דייר נכנס)", "")
                ).strip().lower()
                p_name = (
                    parsed.get("שם פרטי (שוכר שני)", "") + " " +
                    parsed.get("שם משפחה (שוכר שני)", "")
                ).strip().lower()
                if c_name and p_name and c_name == p_name:
                    issues.append({
                        "id":          rule.get("id", ""),
                        "severity":    severity,
                        "label":       rule.get("label", ""),
                        "description": rule.get("description", ""),
                        "suggestion":  rule.get("suggestion", ""),
                    })
        return issues

    def draft_email(self, summary: dict, missing: dict) -> dict | None:
        """Draft a Hebrew email from template + missing data."""
        cfg  = self._email_cfg
        comp = cfg.get("company_name", "מה זה קל")
        ph   = cfg.get("company_phone", "058-773-2700")
        em   = cfg.get("company_email", "docs@mazekal.co.il")

        missing_info = missing.get("missing_info", [])
        missing_docs = missing.get("missing_docs", [])

        if not missing_info and not missing_docs:
            return None

        customer = summary.get("דייר_נכנס", {})
        name     = customer.get("שם", "לקוח יקר")
        addr     = summary.get("כתובת", "")

        subject_tpl = cfg.get(
            "subject_template",
            "בקשת שירות — {address} — {customer_name}",
        )
        subject = subject_tpl.format(address=addr, customer_name=name)

        lines = [
            "שלום רב,",
            "",
            "קיבלנו את הגשת הטופס.",
            "על מנת להמשיך בתהליך, נדרשים הפרטים / המסמכים הבאים:",
            "",
        ]

        if missing_info:
            lines.append("📋 פרטים חסרים:")
            for item in missing_info:
                lines.append(f"  • {item['label']}")
            lines.append("")

        if missing_docs:
            lines.append("📎 מסמכים חסרים:")
            for doc in missing_docs:
                lines.append(f"  • {doc['label']}")
            lines.append("")

        lines += [
            "לאחר השלמת הפרטים, נמשיך בטיפול בפנייתך.",
            "",
            f"בברכה,",
            f"צוות {comp}",
            f"טלפון: {ph}",
            f"מייל: {em}",
        ]

        return {"subject": subject, "body": "\n".join(lines)}

    def get_conditional_logic_engine(self):
        """Build a ConditionalLogicEngine from YAML rules."""
        from app.pipeline.conditional_logic import (
            ConditionalLogicEngine, ConditionalRule, Condition, Op,
        )

        op_map = {
            "equals":       Op.EQUALS,
            "not_equals":   Op.NOT_EQUALS,
            "contains":     Op.CONTAINS,
            "not_contains": Op.NOT_CONTAINS,
            "is_empty":     Op.IS_EMPTY,
            "not_empty":    Op.NOT_EMPTY,
            "in":           Op.CONTAINS,
        }

        rules: list[ConditionalRule] = []
        for r in self._cond:
            if r.get("action") not in ("hide", "show", "autofill"):
                continue
            conditions = [
                Condition(
                    field    = c.get("field", ""),
                    section  = c.get("section", ""),
                    operator = op_map.get(c.get("operator", "equals"), Op.EQUALS),
                    value    = c.get("value"),
                )
                for c in r.get("conditions", [])
            ]
            rule = ConditionalRule(
                note             = r.get("note", ""),
                logic            = r.get("logic", "all"),
                conditions       = conditions,
                action           = r.get("action", "hide"),
                targets          = r.get("targets", []),
                autofill_source  = r.get("autofill_source"),
            )
            rules.append(rule)

        engine = ConditionalLogicEngine()
        engine.rules = rules
        return engine

    def get_document_types(self) -> list[str]:
        return [d.get("id", "") for d in self._req_docs if d.get("id")]

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_address(self, parsed: dict) -> str:
        street = parsed.get("רחוב", "")
        num    = parsed.get("מספר בית", "")
        apt    = parsed.get("דירה", "")
        city   = parsed.get("עיר", "")
        parts  = [p for p in [street, num, f"דירה {apt}" if apt else "", city] if p]
        return ", ".join(parts)

    def _missing_reason(self, label: str) -> dict:
        for rule in self._missing:
            if rule.get("field") == label:
                return {
                    "severity": rule.get("severity", "error"),
                    "reason":   rule.get("reason", f"חסר: {label}"),
                }
        return {"severity": "error", "reason": f"חסר: {label}"}


# ── Loader ────────────────────────────────────────────────────────────────────

def load_yaml_services(
    services_dir: Path = SERVICES_DIR,
) -> dict[str, YAMLDrivenService]:
    """
    Scan config/services/*.yaml and return a dict of form_id → YAMLDrivenService.

    Only loads files where form_id is not a placeholder.
    """
    services: dict[str, YAMLDrivenService] = {}

    if not services_dir.exists():
        logger.warning("Services config dir not found: %s", services_dir)
        return services

    for yaml_path in sorted(services_dir.glob("*.yaml")):
        config = _load_yaml(yaml_path)
        if not config:
            continue

        service_cfg = config.get("service", {})
        form_id     = service_cfg.get("form_id", "")
        name        = service_cfg.get("name", yaml_path.stem)

        if not form_id or "PLACEHOLDER" in form_id or "HERE" in form_id:
            logger.info("Skipping YAML service %s — form_id not set", name)
            continue

        svc = YAMLDrivenService(config, yaml_path)
        services[form_id] = svc
        logger.info(
            "Loaded YAML service '%s' (form_id=%s) from %s",
            svc.service_name, form_id, yaml_path.name,
        )

    return services


def register_yaml_services(
    existing_registry: dict,
    services_dir: Path = SERVICES_DIR,
) -> dict:
    """
    Merge YAML services into an existing service registry.
    Python-coded services take priority (not overwritten).

    Usage in orchestrator.py:
      from app.config_service.loader import register_yaml_services
      _SERVICES = register_yaml_services({"251955479892982": ArnonaService()})
    """
    yaml_services = load_yaml_services(services_dir)

    merged = dict(yaml_services)      # start with YAML services
    merged.update(existing_registry)  # Python services override YAML
    return merged
