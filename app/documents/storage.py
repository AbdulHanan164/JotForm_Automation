"""
Canonical on-disk layout for downloaded submission documents (Group A).

Layout — keyed by ``submission_id`` (always present, always unique):

  data/documents/
    {submission_id}/
      id_photo.png
      signature.png
      lease.pdf
      ...
      _unmapped/
        q412_<label>.pdf        ← files whose field id is not mapped yet
      _manifest.json            ← what was downloaded, when, from where, sha256

Optional human-navigation alias (only when an MZK ref is available):

  data/documents/_by_mzk/{mzk_ref}.json   → {"submission_id": "..."}

Storage is keyed by ``submission_id``, NOT by the MZK ref: the MZK value can
arrive empty or as the literal "לא סופק" placeholder, so it is unsafe as a
primary key. The MZK alias is a convenience pointer only.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from app.documents.contracts import FileAnswer
from app.core import doc_types as _dt

# Canonical vocabulary lives in app/core/doc_types.py (v0.7).
# DOC_TYPES is kept as the summary-facing 6-type view for backward
# compatibility with existing manifests, review-queue JSON, and tests.
DOC_TYPES: dict[str, tuple[str, str]] = {
    ct: _dt.CANONICAL_TYPES[ct] for ct in _dt.SUMMARY_TYPES
}

_MZK_PLACEHOLDER = "לא סופק"


# ── Doc-type mapping (delegates to the canonical vocabulary) ──────────────────

def doc_type_for_label(label: str) -> str:
    """Map a Hebrew document label (or any known spelling) to a canonical
    doc_type. Returns "" if unknown — the caller then stores the file under
    ``_unmapped/``."""
    return _dt.canonicalize(label)


def hebrew_label_for(doc_type: str) -> str:
    return _dt.hebrew_label(doc_type)


def filename_stem_for(doc_type: str) -> str:
    return _dt.filename_stem(doc_type)


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


# ── Paths & atomic writes ─────────────────────────────────────────────────────

def _docs_root() -> Path:
    from app.config import settings
    return settings.documents_dir


def submission_dir(submission_id: str) -> Path:
    d = _docs_root() / submission_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write_bytes(path, text.encode("utf-8"))


def store_file(submission_id: str, fa: FileAnswer, content: bytes, ext: str) -> Path:
    """Persist file bytes under the canonical layout.

    Mapped doc_types → ``{submission}/{stem}{ext}``.
    Unmapped files   → ``{submission}/_unmapped/{qid}_{safe_label}{ext}``.
    """
    base = submission_dir(submission_id)
    if fa.is_mapped:
        path = base / f"{filename_stem_for(fa.doc_type)}{ext}"
    else:
        from app.documents.downloader import _safe_filename
        stem = "_".join(p for p in (fa.question_id, _safe_filename(fa.label)) if p) or "document"
        path = base / "_unmapped" / f"{stem}{ext}"
    _atomic_write_bytes(path, content)
    return path


def write_manifest(submission_id: str, data: dict[str, Any]) -> Path:
    path = submission_dir(submission_id) / "_manifest.json"
    _atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))
    return path


def read_manifest(submission_id: str) -> dict[str, Any]:
    """Load a submission's document manifest; {} when absent/corrupt."""
    if not submission_id:
        return {}
    path = _docs_root() / submission_id / "_manifest.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def manifest_status(submission_id: str, requirement_type: str) -> str:
    """THE single manifest-status lookup (v0.7) — alias-aware.

    Returns the strongest status among every manifest key that satisfies
    `requirement_type` (covering classifier spellings like "tabu_document"
    and substitute types like a sale contract satisfying the contract
    requirement): "present" > "needs_review" > "" (unknown/missing).

    Every consumer (missing detection, summaries, post-merge review updates)
    must use this instead of raw ``manifest["documents"][type]`` access.
    """
    docs = read_manifest(submission_id).get("documents", {})
    if not isinstance(docs, dict):
        return ""
    best = ""
    for key in _dt.manifest_keys_satisfying(requirement_type):
        status = (docs.get(key) or {}).get("status", "")
        if status == "present":
            return "present"
        if status == "needs_review":
            best = "needs_review"
    return best


def manifest_resolves(submission_id: str, requirement_type: str) -> bool:
    """True when the manifest shows the requirement as supplied.

    ``needs_review`` counts as supplied: the customer DID send a file — it must
    not be re-requested; the operator verifies it instead (v0.7 decision, see
    docs/ARCHITECTURE_v0.7.md §document-engine).
    """
    return manifest_status(submission_id, requirement_type) in ("present", "needs_review")


# ── MZK alias (human navigation only — never a primary key) ───────────────────

def _alias_dir() -> Path:
    d = _docs_root() / "_by_mzk"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_mzk_alias(mzk_ref: str, submission_id: str) -> Path | None:
    if not mzk_ref or mzk_ref == _MZK_PLACEHOLDER:
        return None
    path = _alias_dir() / f"{mzk_ref}.json"
    _atomic_write_text(path, json.dumps({"submission_id": submission_id}, ensure_ascii=False))
    return path


def resolve_mzk(mzk_ref: str) -> str | None:
    path = _alias_dir() / f"{mzk_ref}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("submission_id")
    except Exception:
        return None
