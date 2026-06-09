"""
Tests for FIX #2: JotForm webhook token verification.

Verifies:
  - POST /webhook returns 401 when WEBHOOK_SECRET is set and ?token is missing.
  - POST /webhook returns 401 when ?token is wrong.
  - POST /webhook returns 200 when ?token matches WEBHOOK_SECRET.
  - POST /webhook returns 200 regardless of token when WEBHOOK_SECRET is not set (dev mode).
"""
from __future__ import annotations

import json
import pytest

from tests.conftest import SAMPLE_FORM_PAYLOAD


CORRECT_TOKEN = "webhook-secret-xyz"
WRONG_TOKEN   = "totally-wrong-token"


class TestWebhookTokenVerification:
    """FIX #2: Webhook endpoints must reject requests with wrong/missing tokens."""

    def test_missing_token_returns_401(self, webhook_client):
        """No ?token= parameter → 401."""
        r = webhook_client.post(
            "/webhook",
            data=SAMPLE_FORM_PAYLOAD,
        )
        assert r.status_code == 401
        assert "detail" in r.json()

    def test_wrong_token_returns_401(self, webhook_client):
        """Wrong ?token= → 401."""
        r = webhook_client.post(
            f"/webhook?token={WRONG_TOKEN}",
            data=SAMPLE_FORM_PAYLOAD,
        )
        assert r.status_code == 401

    def test_correct_token_returns_200(self, webhook_client):
        """Correct ?token= → 200 accepted."""
        r = webhook_client.post(
            f"/webhook?token={CORRECT_TOKEN}",
            data=SAMPLE_FORM_PAYLOAD,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "received"

    def test_no_secret_set_accepts_any_token(self, no_auth_client):
        """When WEBHOOK_SECRET is empty, any (or no) token is accepted."""
        r = no_auth_client.post(
            "/webhook",    # no ?token at all
            data=SAMPLE_FORM_PAYLOAD,
        )
        assert r.status_code == 200

    def test_no_secret_set_accepts_random_token(self, no_auth_client):
        """Dev mode: random token is still accepted."""
        r = no_auth_client.post(
            "/webhook?token=anything-goes",
            data=SAMPLE_FORM_PAYLOAD,
        )
        assert r.status_code == 200

    def test_token_in_query_not_body(self, webhook_client):
        """
        Token must be in the query string (?token=...).
        JotForm sends the webhook body — token is added to the URL by us.
        """
        # No token in query → 401, even if body contains "token"
        r = webhook_client.post(
            "/webhook",
            data={**SAMPLE_FORM_PAYLOAD, "token": CORRECT_TOKEN},  # token in body only
        )
        assert r.status_code == 401

    def test_response_includes_submission_id(self, webhook_client):
        """Successful webhook response must echo back the submission ID."""
        r = webhook_client.post(
            f"/webhook?token={CORRECT_TOKEN}",
            data=SAMPLE_FORM_PAYLOAD,
        )
        assert r.status_code == 200
        body = r.json()
        assert "submission_id" in body
        assert body["submission_id"] != ""

    def test_response_not_idempotent_replay_on_first_call(self, webhook_client):
        """First submission should NOT be flagged as a replay."""
        r = webhook_client.post(
            f"/webhook?token={CORRECT_TOKEN}",
            data=SAMPLE_FORM_PAYLOAD,
        )
        assert r.status_code == 200
        body = r.json()
        assert body.get("idempotent_replay") is False
