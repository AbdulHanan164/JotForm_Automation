"""
Tests for FIX #1: Authentication on all protected endpoints.

Verifies:
  - Protected routes return 401 when OPERATOR_API_KEY is set and no key is provided.
  - Protected routes return 401 when wrong key is provided.
  - Protected routes return 200 (or non-401) when correct key is provided.
  - Public routes (/, /health) are always accessible without auth.
  - Auth is disabled (dev mode) when OPERATOR_API_KEY is empty.
"""
from __future__ import annotations

import pytest


PROTECTED_ROUTES = [
    ("GET",  "/review"),
    ("GET",  "/review/all"),
    ("GET",  "/submissions"),
    ("GET",  "/discover/nonexistent"),
    ("GET",  "/admin/services"),
    ("GET",  "/admin/fieldmap/arnona/status"),
    ("GET",  "/admin/forms"),
]

PUBLIC_ROUTES = [
    ("GET", "/"),
    ("GET", "/health"),
]

CORRECT_API_KEY  = "test-key-12345"
WRONG_API_KEY    = "wrong-key-000"


class TestPublicRoutes:
    """Public routes must never require auth."""

    def test_root_no_auth(self, no_auth_client):
        r = no_auth_client.get("/")
        assert r.status_code == 200

    def test_health_no_auth(self, no_auth_client):
        r = no_auth_client.get("/health")
        assert r.status_code == 200

    def test_root_with_auth_set(self, auth_client):
        """Public routes stay public even when auth is enabled globally."""
        r = auth_client.get("/")
        assert r.status_code == 200

    def test_health_with_auth_set(self, auth_client):
        r = auth_client.get("/health")
        assert r.status_code == 200


class TestAuthDisabledDevMode:
    """When OPERATOR_API_KEY is not set, all routes pass without a key."""

    @pytest.mark.parametrize("method,path", PROTECTED_ROUTES)
    def test_protected_routes_pass_without_key_in_dev_mode(
        self, no_auth_client, method, path
    ):
        r = no_auth_client.request(method, path)
        # Should NOT be 401 — dev mode bypasses auth
        assert r.status_code != 401, (
            f"{method} {path} returned 401 in dev mode (OPERATOR_API_KEY='') "
            f"— auth should be disabled"
        )


class TestAuthRequired:
    """When OPERATOR_API_KEY is set, protected routes must enforce auth."""

    @pytest.mark.parametrize("method,path", PROTECTED_ROUTES)
    def test_no_key_returns_401(self, auth_client, method, path):
        r = auth_client.request(method, path)
        assert r.status_code == 401, (
            f"{method} {path} should return 401 when no key provided, got {r.status_code}"
        )

    @pytest.mark.parametrize("method,path", PROTECTED_ROUTES)
    def test_wrong_key_returns_401(self, auth_client, method, path):
        r = auth_client.request(
            method, path,
            headers={"X-API-Key": WRONG_API_KEY},
        )
        assert r.status_code == 401, (
            f"{method} {path} should return 401 for wrong key, got {r.status_code}"
        )

    @pytest.mark.parametrize("method,path", PROTECTED_ROUTES)
    def test_correct_key_passes(self, auth_client, method, path):
        r = auth_client.request(
            method, path,
            headers={"X-API-Key": CORRECT_API_KEY},
        )
        # Should NOT be 401/403 — may be 404 if data not found, that's fine
        assert r.status_code not in (401, 403), (
            f"{method} {path} returned {r.status_code} with correct key"
        )

    def test_bearer_token_accepted(self, auth_client):
        """Authorization: Bearer <key> is also accepted."""
        r = auth_client.get(
            "/review",
            headers={"Authorization": f"Bearer {CORRECT_API_KEY}"},
        )
        assert r.status_code != 401

    def test_bearer_token_wrong_rejected(self, auth_client):
        r = auth_client.get(
            "/review",
            headers={"Authorization": f"Bearer wrongkey"},
        )
        assert r.status_code == 401

    def test_response_body_on_401(self, auth_client):
        """401 response must include a meaningful detail message."""
        r = auth_client.get("/review")
        assert r.status_code == 401
        body = r.json()
        assert "detail" in body
        assert len(body["detail"]) > 0
