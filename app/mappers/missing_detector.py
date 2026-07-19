"""
DEPRECATED compatibility shim (v0.7).

The Missing-Information / Missing-Documents engine moved to
``app.rules.requirements`` — the ONE canonical implementation. This module
re-exports its public names so existing imports (tests, backfill scripts)
keep working. Do not add logic here; new code must import from
``app.rules.requirements`` directly.
"""
from __future__ import annotations

from app.rules.requirements import (  # noqa: F401  (re-exports)
    detect_missing,
    _present,
    _doc_present,
)


def is_doc_resolved_in_manifest(submission_id: str, doc_type: str) -> bool:
    """Deprecated — use app.documents.storage.manifest_resolves (alias-aware)."""
    if not submission_id:
        return False
    try:
        from app.documents.storage import manifest_resolves
        return manifest_resolves(submission_id, doc_type)
    except Exception:
        return False
