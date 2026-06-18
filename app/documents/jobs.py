"""
Durable document-acquisition jobs (Group A).

A job record persists the lifecycle of fetching + downloading a submission's
documents, so the work survives process restarts/deploys and can be retried.

  queued → fetching → downloading → done
                                 ↘ failed   (retryable up to max_attempts)

Execution mechanism is FastAPI ``BackgroundTasks`` (injected by the webhook);
this module owns only the record, the run logic, and reconciliation.

The file SOURCE is injected as ``Callable[[str], list[FileAnswer]]``:
  - Group A tests inject a synthetic source.
  - Group B (production, flag-gated) injects the JotForm API adapter.
So this module makes NO assumption about the JotForm response shape.

Records live at: ``data/document_jobs/{submission_id}.json`` (atomic writes).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.documents import storage
from app.documents.contracts import FileAnswer
from app.documents.downloader import download_files

logger = logging.getLogger("documents.jobs")

FileSource = Callable[[str], list[FileAnswer]]


class JobStatus:
    QUEUED      = "queued"
    FETCHING    = "fetching"
    DOWNLOADING = "downloading"
    DONE        = "done"
    FAILED      = "failed"


# statuses eligible to be (re-)run by reconcile()
_RETRYABLE = {
    JobStatus.QUEUED,
    JobStatus.FETCHING,
    JobStatus.DOWNLOADING,
    JobStatus.FAILED,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class DocumentJob:
    submission_id: str
    status:        str = JobStatus.QUEUED
    attempts:      int = 0
    max_attempts:  int = 3
    created_at:    str = field(default_factory=_now)
    updated_at:    str = field(default_factory=_now)
    last_error:    str = ""
    downloaded:    int = 0
    failed:        int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DocumentJob":
        return cls(
            submission_id = data["submission_id"],
            status        = data.get("status", JobStatus.QUEUED),
            attempts      = data.get("attempts", 0),
            max_attempts  = data.get("max_attempts", 3),
            created_at    = data.get("created_at", _now()),
            updated_at    = data.get("updated_at", _now()),
            last_error    = data.get("last_error", ""),
            downloaded    = data.get("downloaded", 0),
            failed        = data.get("failed", 0),
        )


# ── Persistence ───────────────────────────────────────────────────────────────

def _jobs_dir() -> Path:
    from app.config import settings
    d = settings.document_jobs_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


def _job_path(submission_id: str) -> Path:
    return _jobs_dir() / f"{submission_id}.json"


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def save_job(job: DocumentJob) -> Path:
    job.updated_at = _now()
    path = _job_path(job.submission_id)
    _atomic_write_text(path, json.dumps(job.to_dict(), ensure_ascii=False, indent=2))
    return path


def load_job(submission_id: str) -> DocumentJob | None:
    path = _job_path(submission_id)
    if not path.exists():
        return None
    try:
        return DocumentJob.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception as exc:
        logger.error("Failed to load job %s: %s", submission_id, exc)
        return None


def list_jobs(status: str | None = None) -> list[DocumentJob]:
    out: list[DocumentJob] = []
    for p in sorted(_jobs_dir().glob("*.json")):
        try:
            j = DocumentJob.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
        if status is None or j.status == status:
            out.append(j)
    return out


# ── Lifecycle ───────────────────────────────────────────────────────────────

def enqueue(submission_id: str, max_attempts: int | None = None) -> DocumentJob:
    """Create (or return existing) a queued job record. Idempotent."""
    existing = load_job(submission_id)
    if existing is not None:
        return existing

    from app.config import settings
    job = DocumentJob(
        submission_id = submission_id,
        status        = JobStatus.QUEUED,
        max_attempts  = max_attempts if max_attempts is not None else settings.doc_max_attempts,
    )
    save_job(job)
    logger.info("Document job queued: %s", submission_id)
    return job


def run_job(
    submission_id: str,
    fetch_files:   FileSource,
    *,
    update_review: bool = True,
) -> DocumentJob:
    """Execute one attempt of a document job. Never raises.

    Idempotent on success: a job already in ``done`` is returned untouched.
    On exception the job is marked ``failed`` (retryable if under the cap).
    """
    job = load_job(submission_id) or enqueue(submission_id)
    if job.status == JobStatus.DONE:
        return job

    job.attempts += 1
    job.status = JobStatus.FETCHING
    save_job(job)

    # ── Fetch finalized file list (the injected, shape-agnostic source) ────────
    try:
        files = list(fetch_files(submission_id))
    except Exception as exc:
        job.status = JobStatus.FAILED
        job.last_error = f"fetch failed: {exc}"
        save_job(job)
        logger.warning("Document job %s fetch failed: %s", submission_id, exc)
        return job

    # ── Download ───────────────────────────────────────────────────────────────
    job.status = JobStatus.DOWNLOADING
    save_job(job)
    try:
        manifest = download_files(submission_id, files)
    except Exception as exc:
        job.status = JobStatus.FAILED
        job.last_error = f"download failed: {exc}"
        save_job(job)
        logger.warning("Document job %s download failed: %s", submission_id, exc)
        return job

    job.downloaded = manifest.get("downloaded", 0)
    job.failed     = manifest.get("failed", 0)
    job.status     = JobStatus.DONE
    job.last_error = "" if job.failed == 0 else f"{job.failed} file(s) failed to download"
    save_job(job)

    if update_review:
        try:
            _update_review_documents(submission_id, manifest)
        except Exception as exc:
            logger.warning(
                "Review update after job %s failed (non-fatal): %s", submission_id, exc
            )

    logger.info(
        "Document job done: %s (%d ok, %d failed)",
        submission_id, job.downloaded, job.failed,
    )
    return job


def retry(submission_id: str, fetch_files: FileSource) -> DocumentJob:
    """Force a re-run regardless of current status (manual operator action)."""
    job = load_job(submission_id)
    if job is not None and job.status == JobStatus.DONE:
        job.status = JobStatus.QUEUED  # allow re-run; attempts history preserved
        save_job(job)
    return run_job(submission_id, fetch_files)


def reconcile(fetch_files: FileSource) -> dict[str, Any]:
    """Re-run incomplete jobs still under their attempt cap.

    Intended for startup, to recover jobs lost to a restart/deploy.
    """
    rerun: list[str] = []
    exhausted: list[str] = []
    for job in list_jobs():
        if job.status not in _RETRYABLE:
            continue
        if job.attempts < job.max_attempts:
            run_job(job.submission_id, fetch_files)
            rerun.append(job.submission_id)
        else:
            exhausted.append(job.submission_id)
    if rerun or exhausted:
        logger.info("Job reconcile: %d re-run, %d exhausted", len(rerun), len(exhausted))
    return {"rerun": rerun, "exhausted": exhausted}


# ── Review item upgrade ───────────────────────────────────────────────────────

def _update_review_documents(submission_id: str, manifest: dict[str, Any]) -> None:
    """Flip document presence on the review item once files are on disk.

    Data-only update — touches no rendering logic. Sets ``documents_status``
    and marks present docs ✅ in both business_data (English keys) and the
    Hebrew summary.
    """
    from app.review import queue as Q

    item = Q.load(submission_id)
    if item is None:
        return

    present_types = {
        e.get("doc_type")
        for e in manifest.get("files", {}).values()
        if e.get("local_path") and e.get("doc_type")
    }

    docs_bd = item.business_data.get("documents")
    if isinstance(docs_bd, dict):
        for ct in present_types:
            if ct in docs_bd:
                docs_bd[ct] = "✅"

    heb = item.summary.get("מסמכים")
    if isinstance(heb, dict):
        for ct in present_types:
            label = storage.hebrew_label_for(ct)
            if label and label in heb:
                heb[label] = "✅"

    failed = manifest.get("failed", 0)
    if present_types and failed == 0:
        item.documents_status = "ready"
    elif present_types:
        item.documents_status = "partial"
    else:
        item.documents_status = "failed"

    try:
        storage.write_mzk_alias(getattr(item, "mzk_ref", ""), submission_id)
    except Exception:
        pass

    Q.save(item)
