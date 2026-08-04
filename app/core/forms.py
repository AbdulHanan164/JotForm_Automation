"""
Canonical JotForm form registry.

Every form the application knows about is resolved here, from configuration,
so replacing a form is a configuration change and never a code change.

Sources, in precedence order:
  1. settings.main_form_id / settings.missing_docs_form_id  (env-overridable)
  2. form_id declared by each YAML service config  (config/services/*.yaml)
  3. form_id declared by each YAML field map       (config/field_maps/*.yaml)

Placeholder ids (``..._FORM_ID_HERE``, ``TODO``, ``PLACEHOLDER``) are filtered
out so an unfinished service config can never reach the JotForm API.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("webhook")

_PLACEHOLDER_MARKERS = ("placeholder", "here", "todo", "xxx")

_SERVICE_CONFIG_DIR = Path("config/services")
_FIELD_MAP_DIR = Path("config/field_maps")


def is_placeholder(form_id: str) -> bool:
    """True for a not-yet-configured form id."""
    low = (form_id or "").strip().lower()
    return (not low) or any(m in low for m in _PLACEHOLDER_MARKERS)


def _settings():
    from app.config import settings
    return settings


def main_form_id() -> str:
    """The primary intake form (the one customers submit)."""
    return _settings().main_form_id.strip()


def missing_docs_form_id() -> str:
    """The follow-up form customers use to send documents they owe."""
    return _settings().missing_docs_form_id.strip()


def _yaml_form_ids() -> list[str]:
    """Collect form_id from every YAML service config and field map."""
    found: list[str] = []
    try:
        import yaml
    except Exception:                                    # pragma: no cover
        return found
    for directory in (_SERVICE_CONFIG_DIR, _FIELD_MAP_DIR):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.y*ml")):
            try:
                doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except Exception as exc:
                logger.warning("Form registry: could not read %s (%s)", path, exc)
                continue
            candidates = [doc.get("form_id")]
            svc = doc.get("service")
            if isinstance(svc, dict):
                candidates.append(svc.get("form_id"))
            for cand in candidates:
                if isinstance(cand, str) and not is_placeholder(cand):
                    found.append(cand.strip())
    return found


def known_form_ids() -> list[str]:
    """Every real form id the application should keep a cached schema for.

    Derived, never hand-maintained: adding a service YAML (or pointing the
    settings at a replacement form) is enough for it to be synced.
    """
    ordered: list[str] = []
    for fid in [main_form_id(), missing_docs_form_id(), *_yaml_form_ids()]:
        if fid and not is_placeholder(fid) and fid not in ordered:
            ordered.append(fid)
    return ordered


def describe() -> dict:
    """Registry snapshot for the admin API and startup logging."""
    return {
        "main_form_id": main_form_id(),
        "missing_docs_form_id": missing_docs_form_id(),
        "known_form_ids": known_form_ids(),
        "from_yaml": _yaml_form_ids(),
    }
