"""
JotForm Form Sync — keeps local form definitions up to date.

PROBLEM SOLVED:
  When the client edits a JotForm (adds a field, changes a condition),
  the webhook pipeline must reflect that change without a code deploy.

HOW IT WORKS:
  1. On startup, sync all registered form IDs.
  2. Every N hours, re-sync (configurable TTL).
  3. On demand: POST /admin/sync/{form_id}
  4. Converted rules are stored in config/forms/{form_id}_rules.json
  5. The pipeline loads rules from disk, not from hardcoded Python.

WHAT GETS SYNCED:
  - Form title and metadata
  - All question definitions (field_id, label, type, required)
  - All conditional logic rules (hide/show)
  - Auto-generated field map YAML stub (for operator review)

WHAT DOES NOT GET SYNCED (still manual or config-driven):
  - Section assignments (heuristic in converter, human verified in YAML)
  - Business validation rules (these are custom, not from JotForm)
  - Email templates (custom per service)
  - Missing-field reasons (custom business knowledge)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.integrations.jotform.converter import (
    convert_questions, convert_conditions, build_field_map_yaml,
)

logger = logging.getLogger("jotform.sync")

FORMS_DIR = Path("config/forms")
FORMS_DIR.mkdir(parents=True, exist_ok=True)


class FormSync:

    def __init__(self, client):
        self.client = client

    def sync_form(self, form_id: str, force: bool = False) -> "SyncResult":
        """
        Sync a single form from JotForm API.
        Returns a SyncResult with the converted definitions.
        """
        logger.info("Syncing form %s (force=%s)", form_id, force)

        try:
            definition = self.client.get_form_definition(form_id, force=force)
        except Exception as exc:
            logger.error("Sync failed for form %s: %s", form_id, exc)
            return SyncResult(form_id=form_id, success=False, error=str(exc))

        questions_raw  = definition.get("questions", {})
        properties_raw = definition.get("properties", {})
        metadata       = definition.get("metadata", {})

        # Convert
        fields     = convert_questions(questions_raw)
        cond_rules = convert_conditions(properties_raw)

        # Build storable format
        stored = {
            "form_id":     form_id,
            "form_title":  _extract_title(metadata),
            "synced_at":   datetime.now(timezone.utc).isoformat(),
            "field_count": len(fields),
            "rule_count":  len(cond_rules),
            "fields":      fields,
            "conditional_rules": [_rule_to_dict(r) for r in cond_rules],
            "yaml_stub":   build_field_map_yaml(fields),
        }

        # Save converted definition
        out_path = FORMS_DIR / f"{form_id}_synced.json"
        out_path.write_text(
            json.dumps(stored, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(
            "Form %s synced: %d fields, %d conditional rules → %s",
            form_id, len(fields), len(cond_rules), out_path,
        )

        return SyncResult(
            form_id     = form_id,
            success     = True,
            form_title  = stored["form_title"],
            field_count = len(fields),
            rule_count  = len(cond_rules),
            fields      = fields,
            yaml_stub   = stored["yaml_stub"],
        )

    def sync_all(self, form_ids: list[str], force: bool = False) -> list["SyncResult"]:
        """Sync all registered forms."""
        return [self.sync_form(fid, force=force) for fid in form_ids]


def load_synced_definition(form_id: str) -> dict[str, Any] | None:
    """Load the most recent synced definition for a form."""
    path = FORMS_DIR / f"{form_id}_synced.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("Could not load synced definition for %s: %s", form_id, exc)
        return None


def get_synced_conditional_rules(form_id: str) -> list[dict]:
    """Return the converted conditional rules for a form from disk."""
    defn = load_synced_definition(form_id)
    if defn is None:
        return []
    return defn.get("conditional_rules", [])


def get_synced_fields(form_id: str) -> list[dict]:
    """Return field definitions for a form from disk."""
    defn = load_synced_definition(form_id)
    if defn is None:
        return []
    return defn.get("fields", [])


def _extract_title(metadata: dict | list) -> str:
    if isinstance(metadata, dict):
        return metadata.get("title", metadata.get("formTitle", ""))
    return ""


def _rule_to_dict(rule) -> dict:
    """Serialize a ConditionalRule to JSON-compatible dict."""
    return {
        "note":    rule.note,
        "logic":   rule.logic,
        "action":  rule.action,
        "targets": rule.targets,
        "conditions": [
            {
                "field":    c.field,
                "section":  c.section,
                "operator": c.operator,
                "value":    c.value,
            }
            for c in rule.conditions
        ],
    }


class SyncResult:
    def __init__(
        self,
        form_id:     str,
        success:     bool,
        form_title:  str = "",
        field_count: int = 0,
        rule_count:  int = 0,
        fields:      list = None,
        yaml_stub:   str = "",
        error:       str = "",
    ):
        self.form_id     = form_id
        self.success     = success
        self.form_title  = form_title
        self.field_count = field_count
        self.rule_count  = rule_count
        self.fields      = fields or []
        self.yaml_stub   = yaml_stub
        self.error       = error

    def to_dict(self) -> dict:
        return {
            "form_id":     self.form_id,
            "success":     self.success,
            "form_title":  self.form_title,
            "field_count": self.field_count,
            "rule_count":  self.rule_count,
            "error":       self.error,
        }
