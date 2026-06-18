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


# canonical doc_type : (Hebrew label as used in summary["מסמכים"], filename stem)
DOC_TYPES: dict[str, tuple[str, str]] = {
    "id_photo":       ("תעודת_זהות",     "id_photo"),
    "lease_contract": ("חוזה_שכירות",    "lease"),
    "signature":      ("חתימה",          "signature"),
    "arnona_bill":    ("חשבון_ארנונה",   "arnona_bill"),
    "corp_cert":      ("תעודת_התאגדות",  "corporation_certificate"),
    "tabu":           ("נסח_טאבו",       "tabu"),
}

_LABEL_TO_TYPE = {heb: ct for ct, (heb, _) in DOC_TYPES.items()}
_FILENAME_STEM = {ct: stem for ct, (_, stem) in DOC_TYPES.items()}

_MZK_PLACEHOLDER = "לא סופק"


# ── Doc-type mapping ──────────────────────────────────────────────────────────

def doc_type_for_label(label: str) -> str:
    """Map a Hebrew document label (or a canonical key) to a canonical doc_type.

    Returns "" if unknown — the caller then stores the file under ``_unmapped/``.
    """
    if not label:
        return ""
    label = label.strip()
    if label in DOC_TYPES:
        return label
    return _LABEL_TO_TYPE.get(label, "")


def hebrew_label_for(doc_type: str) -> str:
    entry = DOC_TYPES.get(doc_type)
    return entry[0] if entry else ""


def filename_stem_for(doc_type: str) -> str:
    return _FILENAME_STEM.get(doc_type, doc_type or "document")


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
