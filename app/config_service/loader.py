"""
Configuration-Driven Service Loader — v0.6.0.

v0.6 FIX — CRITICAL BUG RESOLVED:
  Previous version: YAMLDrivenService.parse_fields() returned a FLAT dict:
    {"עיר": "רמת גן", "שם פרטי": "..."}

  All downstream components (ConditionalLogicEngine, detect_missing,
  build_summary) expected a SECTION-KEYED dict:
    {"basic": {"עיר": "רמת גן"}, "customer": {...}}

  This caused conditional logic to SILENTLY NEVER FIRE for YAML services,
  meaning fields were never hidden, and wrong missing-field detection.

  FIX: parse_fields() now returns section-keyed format (same as ArnonaService).
  get_conditional_logic_engine() now resolves the correct section for each
  condition field by looking it up from the field definitions.

ADDING A NEW SERVICE (no Python code required):
  1. Create config/services/new_service.yaml with a valid form_id.
  2. Restart — registered automatically.
  3. Verify field IDs via GET /discover/{submission_id}.
  4. Update config/field_maps/{service}.yaml with real IDs.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("config_service.loader")

SERVICES_DIR = Path("config/services")


# ── YAML loader (PyYAML required) ─────────────────────────────────────────────

def _load_yaml(path: Path) -> dict:
    try:
        import yaml  # type: ignore
        with path.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        logger.error(
            "PyYAML not installed — cannot load YAML service %s. "
            "Run: pip install pyyaml",
            path,
        )
        return {}
    except Exception as exc:
        logger.error("Failed to parse YAML %s: %s", path, exc)
        return {}


# ── YAML-driven service ───────────────────────────────────────────────────────

class YAMLDrivenService:
    """
    A fully functional service driven entirely by a YAML config file.
    Implements the same interface as BaseService.

    PARSED DATA FORMAT (v0.6 fix):
    parse_fields() returns a SECTION-KEYED dict, same as Python services:
      {
        "basic":     {"עיר": "רמת גן", "שירותים_נבחרים": ["ארנונה"]},
        "customer":  {"שם_פרטי": "ישראל", "שם_משפחה": "ישראלי"},
        "documents": {"חוזה_שכירות": {"present": True, "url": "...", "local_path": "..."}},
        ...
      }

    This makes ConditionalLogicEngine, detect_missing, and build_summary work
    correctly — they all expect this section-keyed format.
    """

    def __init__(self, config: dict, yaml_path: Path):
        self._config   = config
        self._yaml_path = yaml_path
        self._svc      = config.get("service", {})
        self._fields   = config.get("fields", [])
        self._req_docs = config.get("required_documents", [])
        self._cond     = config.get("conditional_rules", [])
        self._email_cfg = config.get("email", {})
        self._missing_rules = config.get("missing_info_rules", [])

        # Build lookups: label → field config, jotform_id → field config
        self._field_by_label: dict[str, dict] = {}
        self._field_by_jfid:  dict[str, dict] = {}
        for f in self._fields:
            lbl  = f.get("label", "")
            jfid = f.get("jotform_id", "")
            if lbl:
                self._field_by_label[lbl] = f
            if jfid:
                self._field_by_jfid[jfid] = f

    # ── BaseService interface ─────────────────────────────────────────────────

    @property
    def form_id(self) -> str:
        return self._svc.get("form_id", "")

    @property
    def service_name(self) -> str:
        return self._svc.get("display_name", self._svc.get("name", ""))

    def parse_fields(self, raw_fields: dict) -> dict:
        """
        Map raw JotForm field IDs to section-keyed dict.

        Returns:
          {
            "basic":    {"עיר": "...", "שירותים_נבחרים": [...]},
            "customer": {"שם_פרטי": "...", "טלפון": "..."},
            ...
            "_unmapped": {"unknown_field_id": "raw_value"},
          }

        Uses the field's `label` as the dict key within its section.
        This matches the format expected by ConditionalLogicEngine and
        all other downstream pipeline stages.
        """
        # Initialize a dict for every known section
        known_sections = {f.get("section", "other") for f in self._fields}
        parsed: dict[str, Any] = {s: {} for s in known_sections}
        parsed["_unmapped"] = {}

        mapped_jfids = set()

        for field_cfg in self._fields:
            jfid    = field_cfg.get("jotform_id", "")
            label   = field_cfg.get("label", jfid)
            section = field_cfg.get("section", "other")
            ftype   = field_cfg.get("type", "text")

            if not jfid:
                continue

            value = raw_fields.get(jfid)
            if value is None:
                continue  # field not present in this submission

            mapped_jfids.add(jfid)
            coerced = self._coerce(value, ftype)

            if section not in parsed:
                parsed[section] = {}
            parsed[section][label] = coerced

        # Collect unmapped fields (for discovery / debugging)
        for k, v in raw_fields.items():
            if k not in mapped_jfids and isinstance(v, str) and len(v) < 500:
                parsed["_unmapped"][k] = v

        return parsed

    def build_summary(self, parsed: dict) -> dict:
        """Build a Hebrew business summary from the section-keyed parsed dict."""
        basic    = parsed.get("basic", {})
        customer = parsed.get("customer", {})
        outgoing = parsed.get("outgoing", {})
        prop     = parsed.get("property", {})

        city    = basic.get("עיר", "")
        address = self._build_address(parsed)

        summary: dict[str, Any] = {
            "שירות":         self.service_name,
            "עיר":           city,
            "כתובת":         address,
            "תאריך_כניסה":   basic.get("תאריך_כניסה", ""),
        }

        # Customer
        c_first = customer.get("שם_פרטי", "")
        c_last  = customer.get("שם_משפחה", "")
        if c_first or c_last:
            summary["דייר_נכנס"] = {
                "שם":    f"{c_first} {c_last}".strip(),
                "טלפון": customer.get("טלפון", ""),
                "אימייל": customer.get("אימייל", ""),
            }

        # Outgoing
        o_first = outgoing.get("שם_פרטי", "")
        o_last  = outgoing.get("שם_משפחה", "")
        if o_first or o_last:
            summary["דייר_יוצא"] = {
                "שם":    f"{o_first} {o_last}".strip(),
                "טלפון": outgoing.get("טלפון", ""),
            }

        return summary

    def detect_missing(
        self,
        parsed:     dict,
        summary:    dict,
        visibility: dict,
    ) -> dict:
        """
        Detect missing required fields and documents.
        Respects the visibility dict — hidden fields are never flagged missing.
        """
        missing_info: list[dict] = []
        missing_docs: list[dict] = []

        for field_cfg in self._fields:
            label    = field_cfg.get("label", "")
            section  = field_cfg.get("section", "other")
            required = field_cfg.get("required", "never")

            # Skip fields hidden by conditional logic
            if visibility.get(label) is False:
                continue

            if required != "always":
                continue

            section_data = parsed.get(section, {})
            value = section_data.get(label)

            is_missing = (
                value is None or
                (isinstance(value, str) and value.strip() in ("", "אין", "none", "None")) or
                (isinstance(value, dict) and not value.get("present") and not value.get("url") and not value.get("local_path"))
            )

            if is_missing:
                reason = self._missing_reason(label)
                missing_info.append({
                    "field":    f"{section}.{label}",
                    "label":    label,
                    "severity": reason["severity"],
                    "reason":   reason["reason"],
                })

        # Missing required documents
        for doc in self._req_docs:
            doc_label = doc.get("label", "")
            doc_req   = doc.get("required", "never")

            if doc_req != "always":
                continue

            # Look up doc field in documents section
            docs_section = parsed.get("documents", {})
            jfid = doc.get("jotform_field", "")
            value = docs_section.get(doc_label) or (parsed.get("documents", {}).get(jfid) if jfid else None)

            if not value or (isinstance(value, dict) and not value.get("present") and not value.get("url") and not value.get("local_path")):
                missing_docs.append({
                    "id":     doc.get("id", ""),
                    "label":  doc_label,
                    "reason": doc.get("missing_reason", ""),
                })

        return {
            "is_complete":  not missing_info and not missing_docs,
            "missing_info": missing_info,
            "missing_docs": missing_docs,
        }

    def validate(self, parsed: dict, doc_extractions: dict) -> list:
        """Declarative validation from YAML rules."""
        issues = []
        for rule in self._config.get("validation_rules", []):
            if rule.get("check") == "same_name_customer_partner":
                c = parsed.get("customer", {})
                p = parsed.get("partner", {})
                c_name = (f"{c.get('שם_פרטי','')} {c.get('שם_משפחה','')}").strip().lower()
                p_name = (f"{p.get('שם_פרטי','')} {p.get('שם_משפחה','')}").strip().lower()
                if c_name and p_name and c_name == p_name:
                    issues.append({
                        "id":          rule.get("id", ""),
                        "severity":    rule.get("severity", "warning"),
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

        tpl     = cfg.get("subject_template", "בקשת שירות — {address} — {customer_name}")
        subject = tpl.format(address=addr, customer_name=name)

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
        """
        Build a ConditionalLogicEngine from YAML rules.

        v0.6 FIX: Conditions now have the correct section resolved by
        looking up each condition's field label in the field definitions.
        This was the root cause of conditional logic silently never firing.
        """
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

            conditions: list[Condition] = []
            for c in r.get("conditions", []):
                field_label = c.get("field", "")
                # Resolve the section for this condition field.
                # This is the v0.6 fix: previously section was always "".
                section = self._section_for_field(field_label)

                conditions.append(Condition(
                    field    = field_label,
                    section  = section,
                    operator = op_map.get(c.get("operator", "equals"), Op.EQUALS),
                    value    = c.get("value"),
                ))

            rule = ConditionalRule(
                note            = r.get("note", ""),
                logic           = r.get("logic", "all"),
                conditions      = conditions,
                action          = r.get("action", "hide"),
                targets         = r.get("targets", []),
                autofill_source = r.get("autofill_source"),
            )
            rules.append(rule)

        engine = ConditionalLogicEngine(rules)
        return engine if rules else None

    def get_document_types(self) -> list[str]:
        return [d.get("id", "") for d in self._req_docs if d.get("id")]

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _section_for_field(self, label: str) -> str:
        """
        Look up which section a field belongs to, given its label.
        Falls back to 'other' if not found — logs a warning so the
        YAML author can fix the condition field reference.
        """
        field = self._field_by_label.get(label)
        if field:
            return field.get("section", "other")
        logger.warning(
            "Conditional rule references field '%s' which is not in the "
            "field definitions for service '%s'. Check the YAML. "
            "Condition will use section='other' and may not fire correctly.",
            label, self.service_name,
        )
        return "other"

    def _build_address(self, parsed: dict) -> str:
        prop   = parsed.get("property", {})
        basic  = parsed.get("basic", {})
        street = prop.get("רחוב", "")
        num    = prop.get("בניין", "")
        apt    = prop.get("דירה", "")
        city   = basic.get("עיר", "")
        parts  = [p for p in [street, num, f"דירה {apt}" if apt else "", city] if p]
        return ", ".join(parts)

    def _coerce(self, value: Any, ftype: str) -> Any:
        """Basic type coercion matching ArnonaService._coerce() behavior."""
        if value is None:
            return ""
        sv = str(value).strip()
        if ftype == "date":
            try:
                from app.utils.hebrew import format_date
                return format_date(sv)
            except Exception:
                return sv
        if ftype in ("file", "signature"):
            if sv.startswith("http"):
                return {"present": True, "url": sv, "local_path": ""}
            if sv:
                return {"present": True, "url": "", "local_path": sv}
            return {"present": False, "url": "", "local_path": ""}
        if ftype == "bool":
            return sv.lower() in ("accepted", "הוסכם", "true", "1", "yes", "כן")
        if ftype == "multi":
            if isinstance(value, list):
                return [str(v).strip() for v in value if v]
            return [s.strip() for s in sv.split(",") if s.strip()]
        return sv

    def _missing_reason(self, label: str) -> dict:
        for rule in self._missing_rules:
            if rule.get("field") == label:
                return {
                    "severity": rule.get("severity", "error"),
                    "reason":   rule.get("reason", f"חסר: {label}"),
                }
        return {"severity": "error", "reason": f"חסר: {label}"}


# ── Loader ────────────────────────────────────────────────────────────────────

def _validate_yaml_service(config: dict, path: Path) -> list[str]:
    """
    Validate a service YAML structure.
    Returns a list of error messages (empty = valid).
    """
    errors = []
    svc = config.get("service", {})

    if not svc:
        errors.append("Missing 'service:' top-level key")
    if not svc.get("form_id"):
        errors.append("service.form_id is missing or empty")
    if not svc.get("name") and not svc.get("display_name"):
        errors.append("service.name or service.display_name is required")
    if not config.get("fields"):
        errors.append("No 'fields:' defined — service cannot parse submissions")

    return errors


def load_yaml_services(
    services_dir: Path = SERVICES_DIR,
) -> dict[str, "YAMLDrivenService"]:
    """
    Scan config/services/*.yaml and return {form_id: YAMLDrivenService}.
    Skips files where form_id is a placeholder or YAML is invalid.
    Raises ValueError on startup if any YAML has structural errors —
    fail loudly rather than silently misconfiguring.
    """
    services: dict[str, YAMLDrivenService] = {}

    if not services_dir.exists():
        logger.info("Services config dir not found: %s (no YAML services loaded)", services_dir)
        return services

    for yaml_path in sorted(services_dir.glob("*.yaml")):
        config = _load_yaml(yaml_path)
        if not config:
            continue

        # Validate structure
        errors = _validate_yaml_service(config, yaml_path)
        if errors:
            # Fail loudly at startup — don't silently ignore misconfiguration
            raise ValueError(
                f"Invalid service YAML {yaml_path.name}: {'; '.join(errors)}"
            )

        svc_cfg = config.get("service", {})
        form_id = svc_cfg.get("form_id", "")
        name    = svc_cfg.get("name", yaml_path.stem)

        # Skip placeholder form IDs
        if not form_id or any(p in form_id for p in ("PLACEHOLDER", "HERE", "TODO")):
            logger.info("Skipping YAML service '%s' — form_id not set yet", name)
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
    Merge YAML services into an existing registry.
    Python-coded services take priority (not overwritten).
    """
    try:
        yaml_services = load_yaml_services(services_dir)
    except ValueError as exc:
        logger.error("YAML service validation failed: %s", exc)
        raise

    merged = dict(yaml_services)
    merged.update(existing_registry)  # Python services override YAML
    return merged
