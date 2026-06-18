"""
Acceptance tests for the document-acquisition infrastructure (Group A + B1).

Covers, with NO live JotForm calls and NO production webhook changes:
  - storage   : doc-type mapping, canonical + unmapped layout, manifest, MZK alias
  - download  : download_files happy path, size limit, per-file isolation, sha256
  - jobs      : enqueue (idempotent), run_job, review upgrade, fetch/download
                failures, reconcile, retry cap, done-idempotency
  - model     : ReviewItem.documents_status round-trips
  - adapter   : get_submission_files parses a JotForm-shaped fixture (B1)

The file SOURCE is injected as a synthetic callable, and downloads are stubbed
at app.documents.downloader._fetch_bytes — so nothing here assumes the real
JotForm API response shape.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.documents.contracts import FileAnswer
from app.documents import storage
from app.documents import downloader
from app.documents import jobs
from app.documents.jobs import DocumentJob, JobStatus
from app.review.models import ReviewItem, ReviewStatus
from app.review import queue as Q


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def doc_dirs(tmp_path, monkeypatch):
    """Point documents_dir / document_jobs_dir / review_dir at temp locations."""
    docs = tmp_path / "documents"
    jobsd = tmp_path / "document_jobs"
    review = tmp_path / "review_queue"
    for d in (docs, jobsd, review):
        d.mkdir(parents=True)
    monkeypatch.setattr("app.config.settings.documents_dir", docs)
    monkeypatch.setattr("app.config.settings.document_jobs_dir", jobsd)
    monkeypatch.setattr("app.config.settings.review_dir", review)
    monkeypatch.setattr("app.config.settings.doc_max_attempts", 3)
    return {"documents": docs, "jobs": jobsd, "review": review}


def _stub_fetch(monkeypatch, mapping):
    """Patch _fetch_bytes: mapping is url -> (bytes, content_type) or Exception."""
    def fake(url):
        val = mapping.get(url)
        if isinstance(val, Exception):
            raise val
        if val is None:
            raise ValueError(f"unexpected url {url}")
        return val
    monkeypatch.setattr(downloader, "_fetch_bytes", fake)


def _fa(qid, doc_type, label, url):
    return FileAnswer(question_id=qid, doc_type=doc_type, label=label, url=url)


# ── Storage ───────────────────────────────────────────────────────────────────

class TestStorage:
    def test_doc_type_for_known_hebrew_label(self):
        assert storage.doc_type_for_label("תעודת_זהות") == "id_photo"
        assert storage.doc_type_for_label("חתימה") == "signature"

    def test_doc_type_for_canonical_passthrough(self):
        assert storage.doc_type_for_label("id_photo") == "id_photo"

    def test_doc_type_unknown_is_empty(self):
        assert storage.doc_type_for_label("משהו אחר") == ""

    def test_mapped_file_uses_canonical_filename(self, doc_dirs):
        fa = _fa("q35", "id_photo", "תעודת_זהות", "http://x/id.png")
        path = storage.store_file("sub1", fa, b"data", ".png")
        assert path.name == "id_photo.png"
        assert path.read_bytes() == b"data"

    def test_unmapped_file_goes_to_unmapped_dir(self, doc_dirs):
        fa = _fa("q412", "", "מסמך_לא_ידוע", "http://x/y.pdf")
        path = storage.store_file("sub1", fa, b"d", ".pdf")
        assert "_unmapped" in str(path)
        assert path.exists()

    def test_manifest_written(self, doc_dirs):
        storage.write_manifest("sub1", {"submission_id": "sub1", "downloaded": 0, "failed": 0, "files": {}})
        mpath = doc_dirs["documents"] / "sub1" / "_manifest.json"
        assert mpath.exists()
        assert json.loads(mpath.read_text(encoding="utf-8"))["submission_id"] == "sub1"

    def test_mzk_alias_round_trip(self, doc_dirs):
        storage.write_mzk_alias("MZK6853", "sub-xyz")
        assert storage.resolve_mzk("MZK6853") == "sub-xyz"

    def test_mzk_alias_skips_placeholder(self, doc_dirs):
        assert storage.write_mzk_alias("לא סופק", "sub-xyz") is None
        assert storage.write_mzk_alias("", "sub-xyz") is None


# ── download_files ──────────────────────────────────────────────────────────

class TestDownloadFiles:
    def test_happy_path_persists_and_hashes(self, doc_dirs, monkeypatch):
        url = "http://x/id.png"
        _stub_fetch(monkeypatch, {url: (b"PNGDATA", "image/png")})
        manifest = downloader.download_files("sub1", [_fa("q35", "id_photo", "תעודת_זהות", url)])

        assert manifest["downloaded"] == 1
        assert manifest["failed"] == 0
        entry = manifest["files"]["q35"]
        assert entry["local_path"].endswith("id_photo.png")
        assert entry["size_bytes"] == len(b"PNGDATA")
        assert entry["sha256"]  # non-empty
        assert Path(entry["local_path"]).exists()

    def test_per_file_isolation(self, doc_dirs, monkeypatch):
        ok = "http://x/ok.png"
        bad = "http://x/bad.pdf"
        _stub_fetch(monkeypatch, {ok: (b"d", "image/png"), bad: RuntimeError("boom")})
        manifest = downloader.download_files("sub1", [
            _fa("q35", "id_photo", "תעודת_זהות", ok),
            _fa("q60", "lease_contract", "חוזה_שכירות", bad),
        ])
        assert manifest["downloaded"] == 1
        assert manifest["failed"] == 1
        assert manifest["files"]["q60"]["error"]

    def test_manifest_persisted_to_disk(self, doc_dirs, monkeypatch):
        url = "http://x/id.png"
        _stub_fetch(monkeypatch, {url: (b"d", "image/png")})
        downloader.download_files("subM", [_fa("q35", "id_photo", "תעודת_זהות", url)])
        assert (doc_dirs["documents"] / "subM" / "_manifest.json").exists()


# ── Jobs ──────────────────────────────────────────────────────────────────────

class TestJobs:
    def test_enqueue_is_idempotent(self, doc_dirs):
        j1 = jobs.enqueue("subE")
        j2 = jobs.enqueue("subE")
        assert j1.submission_id == j2.submission_id == "subE"
        assert j2.status == JobStatus.QUEUED
        assert len(jobs.list_jobs()) == 1

    def test_run_job_happy_path(self, doc_dirs, monkeypatch):
        url = "http://x/id.png"
        _stub_fetch(monkeypatch, {url: (b"d", "image/png")})
        source = lambda sid: [_fa("q35", "id_photo", "תעודת_זהות", url)]
        job = jobs.run_job("subR", source, update_review=False)
        assert job.status == JobStatus.DONE
        assert job.downloaded == 1 and job.failed == 0
        assert (doc_dirs["documents"] / "subR" / "id_photo.png").exists()

    def test_run_job_upgrades_review_item(self, doc_dirs, monkeypatch):
        # Seed a review item with documents absent
        item = ReviewItem(
            submission_id="subUP", service_name="arnona_transfer",
            form_title="t", received_at="now", mzk_ref="MZK1",
            summary={"מסמכים": {"תעודת_זהות": "❌", "חתימה": "❌"}},
            business_data={"documents": {"id_photo": "❌", "signature": "❌"}},
        )
        Q.save(item)

        url = "http://x/id.png"
        _stub_fetch(monkeypatch, {url: (b"d", "image/png")})
        source = lambda sid: [_fa("q35", "id_photo", "תעודת_זהות", url)]
        jobs.run_job("subUP", source)

        reloaded = Q.load("subUP")
        assert reloaded.documents_status == "ready"
        assert reloaded.business_data["documents"]["id_photo"] == "✅"
        assert reloaded.summary["מסמכים"]["תעודת_זהות"] == "✅"
        # untouched doc stays absent
        assert reloaded.business_data["documents"]["signature"] == "❌"
        # MZK alias created
        assert storage.resolve_mzk("MZK1") == "subUP"

    def test_partial_when_some_fail(self, doc_dirs, monkeypatch):
        item = ReviewItem(
            submission_id="subP", service_name="s", form_title="t", received_at="now",
            summary={"מסמכים": {"תעודת_זהות": "❌"}},
            business_data={"documents": {"id_photo": "❌", "lease_contract": "❌"}},
        )
        Q.save(item)
        ok, bad = "http://x/ok.png", "http://x/bad.pdf"
        _stub_fetch(monkeypatch, {ok: (b"d", "image/png"), bad: RuntimeError("x")})
        source = lambda sid: [
            _fa("q35", "id_photo", "תעודת_זהות", ok),
            _fa("q60", "lease_contract", "חוזה_שכירות", bad),
        ]
        jobs.run_job("subP", source)
        assert Q.load("subP").documents_status == "partial"

    def test_fetch_failure_marks_failed(self, doc_dirs):
        def boom(sid):
            raise RuntimeError("API down")
        job = jobs.run_job("subF", boom, update_review=False)
        assert job.status == JobStatus.FAILED
        assert "fetch failed" in job.last_error
        assert job.attempts == 1

    def test_done_job_is_idempotent(self, doc_dirs, monkeypatch):
        url = "http://x/id.png"
        calls = {"n": 0}
        def fetch(u):
            calls["n"] += 1
            return (b"d", "image/png")
        monkeypatch.setattr(downloader, "_fetch_bytes", fetch)
        source = lambda sid: [_fa("q35", "id_photo", "תעודת_זהות", url)]
        jobs.run_job("subD", source, update_review=False)
        first = calls["n"]
        jobs.run_job("subD", source, update_review=False)  # should no-op
        assert calls["n"] == first

    def test_reconcile_reruns_failed_under_cap(self, doc_dirs, monkeypatch):
        # A previously failed job, 1 attempt, under cap
        jobs.save_job(DocumentJob(submission_id="subRC", status=JobStatus.FAILED, attempts=1, max_attempts=3))
        url = "http://x/id.png"
        _stub_fetch(monkeypatch, {url: (b"d", "image/png")})
        source = lambda sid: [_fa("q35", "id_photo", "תעודת_זהות", url)]
        summary = jobs.reconcile(source)
        assert "subRC" in summary["rerun"]
        assert jobs.load_job("subRC").status == JobStatus.DONE

    def test_reconcile_skips_exhausted(self, doc_dirs):
        jobs.save_job(DocumentJob(submission_id="subX", status=JobStatus.FAILED, attempts=3, max_attempts=3))
        summary = jobs.reconcile(lambda sid: [])
        assert "subX" in summary["exhausted"]
        assert "subX" not in summary["rerun"]


# ── ReviewItem model ──────────────────────────────────────────────────────────

class TestReviewModel:
    def test_documents_status_round_trips(self):
        item = ReviewItem(
            submission_id="s", service_name="x", form_title="t", received_at="now",
            documents_status="ready",
        )
        restored = ReviewItem.from_dict(item.to_dict())
        assert restored.documents_status == "ready"

    def test_legacy_item_defaults_documents_status_empty(self):
        # A dict without the new key (old on-disk file) must still load
        legacy = {"submission_id": "s", "service_name": "x", "form_title": "t", "received_at": "now"}
        restored = ReviewItem.from_dict(legacy)
        assert restored.documents_status == ""


# ── B1 adapter (fixture only — live validation deferred to Group C) ──────────

class TestGetSubmissionFilesAdapter:
    def _client(self, monkeypatch, submission_payload):
        from app.integrations.jotform.client import JotFormClient
        c = JotFormClient("dummy-key")
        monkeypatch.setattr(c, "get_submission", lambda sid: submission_payload)
        return c

    def test_parses_file_answer_and_ignores_text(self, doc_dirs, monkeypatch):
        payload = {
            "answers": {
                "35": {"type": "control_fileupload", "name": "תעודת_זהות",
                       "answer": "https://www.jotform.com/uploads/u/f/s/id.png"},
                "30": {"type": "control_textbox", "name": "אימייל", "answer": "a@b.com"},
            }
        }
        client = self._client(monkeypatch, payload)
        files = client.get_submission_files("sub1")
        assert len(files) == 1
        assert files[0].url.endswith("id.png")
        assert files[0].doc_type == "id_photo"
        assert files[0].question_id == "q35"

    def test_handles_list_of_urls(self, doc_dirs, monkeypatch):
        payload = {
            "answers": {
                "60": {"type": "control_fileupload", "name": "חוזה_שכירות",
                       "answer": ["https://www.jotform.com/uploads/u/f/s/a.pdf",
                                  "https://www.jotform.com/uploads/u/f/s/b.pdf"]},
            }
        }
        client = self._client(monkeypatch, payload)
        files = client.get_submission_files("sub2")
        assert len(files) == 2
        assert all(f.label == "חוזה_שכירות" for f in files)

    def test_ignores_non_url_answer(self, doc_dirs, monkeypatch):
        payload = {"answers": {"99": {"type": "control_widget", "name": "חתימה", "answer": "BASE64BLOB=="}}}
        client = self._client(monkeypatch, payload)
        assert client.get_submission_files("sub3") == []

    def test_signature_widget_with_jotform_upload_is_kept(self, doc_dirs, monkeypatch):
        # Real production shape: q181 is a control_widget whose answer is a
        # finalized JotForm upload URL — must be captured as the signature.
        payload = {
            "answers": {
                "181": {"type": "control_widget", "name": "input181",
                        "answer": "https://www.jotform.com/uploads/Acc/250201745267957/sub/sig_base64_181.png"},
            }
        }
        client = self._client(monkeypatch, payload)
        files = client.get_submission_files("sub4")
        assert len(files) == 1
        assert files[0].doc_type == "signature"

    def test_widget_marketing_link_is_excluded(self, doc_dirs, monkeypatch):
        # Real production shape: q185 typeA widget answer is a website link,
        # NOT a document — must be excluded (regression guard for the live bug).
        payload = {
            "answers": {
                "185": {"type": "control_widget", "name": "typeA",
                        "answer": "https://mazekal.co.il/some-marketing-page/"},
            }
        }
        client = self._client(monkeypatch, payload)
        assert client.get_submission_files("sub5") == []
