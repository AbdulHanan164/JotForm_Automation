"""
Tests for FIX #7: Webhook idempotency — duplicate submissions are handled.

Verifies:
  - Second POST with same submission_id returns idempotent_replay: true.
  - Second POST returns 200 (not an error).
  - Response header X-Idempotent-Replay: true is set on replays.
  - Third POST is also flagged as replay (not just the second).
  - Different submission IDs are treated as independent submissions.
  - JotForm retry behavior (same ID, same payload) is safely handled.
"""
from __future__ import annotations

import json
import pytest

from tests.conftest import SAMPLE_FORM_PAYLOAD, SAMPLE_SUBMISSION_ID

CORRECT_TOKEN = "webhook-secret-xyz"


def _post_webhook(client, payload=None, token=CORRECT_TOKEN):
    """Helper: POST to /webhook with given payload."""
    if payload is None:
        payload = SAMPLE_FORM_PAYLOAD
    return client.post(f"/webhook?token={token}", data=payload)


class TestIdempotency:
    """FIX #7: Repeated webhook calls with same submission_id must not duplicate."""

    def test_first_call_not_replay(self, webhook_client):
        """First submission is normal — not a replay."""
        r = _post_webhook(webhook_client)
        assert r.status_code == 200
        body = r.json()
        assert body["idempotent_replay"] is False

    def test_second_call_is_replay(self, webhook_client):
        """Second POST with same submission_id → idempotent_replay: true."""
        _post_webhook(webhook_client)  # First call
        r = _post_webhook(webhook_client)  # Duplicate
        assert r.status_code == 200
        body = r.json()
        assert body["idempotent_replay"] is True

    def test_replay_has_header(self, webhook_client):
        """Replay response includes X-Idempotent-Replay header."""
        _post_webhook(webhook_client)
        r = _post_webhook(webhook_client)
        assert r.headers.get("X-Idempotent-Replay") == "true"

    def test_third_call_also_replay(self, webhook_client):
        """Third and further calls with same ID are all replays."""
        _post_webhook(webhook_client)
        _post_webhook(webhook_client)
        r = _post_webhook(webhook_client)  # third
        assert r.status_code == 200
        body = r.json()
        assert body["idempotent_replay"] is True

    def test_different_submission_ids_are_independent(self, webhook_client):
        """Two different submission IDs are both treated as first-time submissions."""
        payload_a = {**SAMPLE_FORM_PAYLOAD, "submissionID": "sub-aaa-111"}
        payload_b = {**SAMPLE_FORM_PAYLOAD, "submissionID": "sub-bbb-222"}

        # Update rawRequest to match the submissionID too
        rr_a = json.loads(SAMPLE_FORM_PAYLOAD["rawRequest"])
        rr_b = json.loads(SAMPLE_FORM_PAYLOAD["rawRequest"])
        rr_a["submissionID"] = "sub-aaa-111"
        rr_b["submissionID"] = "sub-bbb-222"
        payload_a["rawRequest"] = json.dumps(rr_a)
        payload_b["rawRequest"] = json.dumps(rr_b)

        r_a = _post_webhook(webhook_client, payload=payload_a)
        r_b = _post_webhook(webhook_client, payload=payload_b)

        assert r_a.json()["idempotent_replay"] is False
        assert r_b.json()["idempotent_replay"] is False

    def test_replay_returns_submission_id(self, webhook_client):
        """Replay response still echoes back the submission_id."""
        _post_webhook(webhook_client)
        r = _post_webhook(webhook_client)
        body = r.json()
        assert body["submission_id"] == SAMPLE_SUBMISSION_ID

    def test_replay_message_describes_cache(self, webhook_client):
        """Replay response includes an informative message."""
        _post_webhook(webhook_client)
        r = _post_webhook(webhook_client)
        body = r.json()
        assert "message" in body
        msg = body["message"].lower()
        # Should mention 'already' or 'cached' or 'processed'
        assert any(w in msg for w in ("already", "cached", "processed", "replay"))
