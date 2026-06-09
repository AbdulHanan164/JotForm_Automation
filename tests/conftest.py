"""
Shared test fixtures — v0.6.0.

Provides:
  - client      : TestClient with no auth key set (auth disabled / dev mode)
  - auth_client  : TestClient with OPERATOR_API_KEY configured
  - webhook_client: TestClient with WEBHOOK_SECRET configured
  - tmp_dirs    : creates isolated temp dirs for submissions/processed/review/docs
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient


# ── Temp directory fixture ────────────────────────────────────────────────────

@pytest.fixture()
def tmp_dirs(tmp_path: Path, monkeypatch):
    """
    Redirect all data directories to a temporary location.
    Ensures tests never touch real data/  directories.
    """
    subs_dir    = tmp_path / "submissions"
    proc_dir    = tmp_path / "processed"
    review_dir  = tmp_path / "review_queue"
    docs_dir    = tmp_path / "documents"
    logs_dir    = tmp_path / "logs"

    for d in (subs_dir, proc_dir, review_dir, docs_dir, logs_dir):
        d.mkdir(parents=True)

    # Patch settings so the app uses tmp dirs
    monkeypatch.setenv("SUBMISSIONS_DIR", str(subs_dir))
    monkeypatch.setenv("PROCESSED_DIR",   str(proc_dir))
    monkeypatch.setenv("REVIEW_DIR",      str(review_dir))
    monkeypatch.setenv("DOCUMENTS_DIR",   str(docs_dir))
    monkeypatch.setenv("LOGS_DIR",        str(logs_dir))

    return {
        "submissions": subs_dir,
        "processed":   proc_dir,
        "review":      review_dir,
        "documents":   docs_dir,
        "logs":        logs_dir,
        "root":        tmp_path,
    }


# ── App / client fixtures ─────────────────────────────────────────────────────

@pytest.fixture()
def no_auth_client(tmp_dirs, monkeypatch) -> Generator:
    """
    TestClient with auth keys NOT set.
    Auth is disabled (dev mode) — all protected routes pass without a key.
    """
    monkeypatch.setenv("OPERATOR_API_KEY", "")
    monkeypatch.setenv("WEBHOOK_SECRET",   "")

    # Re-import with patched env
    from importlib import reload
    import app.config as cfg_mod
    reload(cfg_mod)

    from app.main import app
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture()
def auth_client(tmp_dirs, monkeypatch) -> Generator:
    """
    TestClient with OPERATOR_API_KEY = 'test-key-12345'.
    Passing X-API-Key: test-key-12345 is required on protected routes.
    """
    monkeypatch.setenv("OPERATOR_API_KEY", "test-key-12345")
    monkeypatch.setenv("WEBHOOK_SECRET",   "")

    from importlib import reload
    import app.config as cfg_mod
    reload(cfg_mod)

    from app.main import app
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture()
def webhook_client(tmp_dirs, monkeypatch) -> Generator:
    """
    TestClient with WEBHOOK_SECRET = 'webhook-secret-xyz'.
    Webhook URL must include ?token=webhook-secret-xyz.
    """
    monkeypatch.setenv("OPERATOR_API_KEY", "test-key-12345")
    monkeypatch.setenv("WEBHOOK_SECRET",   "webhook-secret-xyz")

    from importlib import reload
    import app.config as cfg_mod
    reload(cfg_mod)

    from app.main import app
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ── Sample JotForm payload ────────────────────────────────────────────────────

SAMPLE_SUBMISSION_ID = "test-sub-001"

SAMPLE_FORM_PAYLOAD = {
    "formID":      "251955479892982",
    "submissionID": SAMPLE_SUBMISSION_ID,
    "rawRequest":  json.dumps({
        "formID":      "251955479892982",
        "submissionID": SAMPLE_SUBMISSION_ID,
        "3":  "רמת גן",        # city (placeholder field ID)
        "4":  "ארנונה",        # service
        "10": "ישראל",         # customer first name
        "11": "ישראלי",        # customer last name
        "12": "0501234567",    # phone
        "13": "test@test.com", # email
        "14": "123456789",     # ID number
    }),
}
