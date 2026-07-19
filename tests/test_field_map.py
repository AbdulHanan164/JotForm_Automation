"""
Tests for FIX #3: Field mapping — YAML config + startup warnings.

Verifies:
  - FIELD_MAP loads from config/field_maps/arnona.yaml when present.
  - check_field_map_status() returns correct counts.
  - Unverified entries are flagged with status='warnings'.
  - Verified entries are counted correctly.
  - Missing YAML file falls back to Python defaults gracefully.
  - GET /admin/fieldmap/arnona/status endpoint returns correct structure.
"""
from __future__ import annotations

import pytest
import yaml
from pathlib import Path


# ── Unit tests: _load_yaml_field_map ─────────────────────────────────────────

class TestYamlFieldMapLoading:
    """YAML field map must load from config/field_maps/arnona.yaml."""

    def test_field_map_module_importable(self):
        from app.services.arnona import field_map
        assert hasattr(field_map, "FIELD_MAP")

    def test_field_map_is_dict(self):
        from app.services.arnona.field_map import FIELD_MAP
        assert isinstance(FIELD_MAP, dict)

    def test_field_map_has_entries(self):
        from app.services.arnona.field_map import FIELD_MAP
        assert len(FIELD_MAP) > 0, "FIELD_MAP should have at least one entry"

    def test_check_field_map_status_returns_dict(self):
        from app.services.arnona.field_map import check_field_map_status
        status = check_field_map_status()
        assert isinstance(status, dict)

    def test_check_field_map_status_keys(self):
        from app.services.arnona.field_map import check_field_map_status
        status = check_field_map_status()
        for key in ("total", "verified", "unverified", "unverified_labels", "status"):
            assert key in status, f"Missing key '{key}' in field map status"

    def test_status_is_valid_string(self):
        from app.services.arnona.field_map import check_field_map_status
        status = check_field_map_status()
        # 'ok' = all verified, 'placeholder_ids_present' = some still placeholders
        assert status["status"] in ("ok", "placeholder_ids_present", "not_loaded")

    def test_counts_add_up(self):
        from app.services.arnona.field_map import check_field_map_status
        s = check_field_map_status()
        assert s["verified"] + s["unverified"] == s["total"], (
            "verified + unverified should equal total"
        )

    def test_unverified_labels_is_list(self):
        from app.services.arnona.field_map import check_field_map_status
        s = check_field_map_status()
        assert isinstance(s["unverified_labels"], list)

    def test_unverified_count_matches_list_length(self):
        from app.services.arnona.field_map import check_field_map_status
        s = check_field_map_status()
        assert len(s["unverified_labels"]) == s["unverified"]


class TestYamlFieldMapWithCustomFile:
    """Test field map loading with a controlled temp YAML file."""

    def test_verified_entry_counted(self, tmp_path):
        """_load_yaml_field_map() correctly identifies verified vs unverified entries."""
        yaml_content = {
            "form_id":     "251955479892982",
            "description": "Test",
            "fields": [
                {
                    "jotform_id": "q1_realId",
                    "label":      "עיר",
                    "section":    "basic",
                    "type":       "text",
                    "verified":   True,
                },
                {
                    "jotform_id": "q2_placeholder",
                    "label":      "שם_פרטי",
                    "section":    "customer",
                    "type":       "text",
                    "verified":   False,
                },
            ],
        }
        yaml_file = tmp_path / "arnona.yaml"
        yaml_file.write_text(yaml.dump(yaml_content, allow_unicode=True), encoding="utf-8")

        # Call _load_yaml_field_map directly with a temp path by patching _YAML_CONFIG
        import app.services.arnona.field_map as fm_mod
        original = fm_mod._YAML_CONFIG
        try:
            fm_mod._YAML_CONFIG = yaml_file
            field_map_data, placeholder_labels, unresolved = fm_mod._load_yaml_field_map()
        finally:
            fm_mod._YAML_CONFIG = original

        assert "q1_realId" in field_map_data
        assert field_map_data["q1_realId"]["verified"] is True
        # v0.7: fabricated ids (containing "placeholder") are quarantined —
        # excluded from the active map, reported in the unresolved list.
        assert "q2_placeholder" not in field_map_data
        assert any(u["jotform_id"] == "q2_placeholder" and u["fabricated"] for u in unresolved)
        assert "שם_פרטי" in placeholder_labels
        assert "עיר" not in placeholder_labels   # verified=True → not placeholder

    def test_yaml_file_not_found_returns_empty(self, tmp_path):
        """If YAML file doesn't exist, _load_yaml_field_map returns empty dicts."""
        import app.services.arnona.field_map as fm_mod
        original = fm_mod._YAML_CONFIG
        try:
            fm_mod._YAML_CONFIG = tmp_path / "nonexistent_arnona.yaml"
            field_map_data, placeholder_labels, unresolved = fm_mod._load_yaml_field_map()
        finally:
            fm_mod._YAML_CONFIG = original

        assert field_map_data == {}
        assert placeholder_labels == []
        assert unresolved == []


# ── Integration: admin endpoint ───────────────────────────────────────────────

class TestAdminFieldMapEndpoint:
    """GET /admin/fieldmap/arnona/status must return the correct structure."""

    def test_endpoint_requires_auth(self, auth_client):
        r = auth_client.get("/admin/fieldmap/arnona/status")
        assert r.status_code == 401  # No key provided

    def test_endpoint_returns_200_with_key(self, auth_client):
        r = auth_client.get(
            "/admin/fieldmap/arnona/status",
            headers={"X-API-Key": "test-key-12345"},
        )
        assert r.status_code == 200

    def test_endpoint_response_structure(self, auth_client):
        r = auth_client.get(
            "/admin/fieldmap/arnona/status",
            headers={"X-API-Key": "test-key-12345"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["form_id"] == "251955479892982"
        assert "total_fields" in body
        assert "verified" in body
        assert "unverified" in body
        assert "status" in body
        assert body["status"] in ("ok", "placeholder_ids_present", "not_loaded")

    def test_endpoint_returns_action_needed_for_placeholders(self, auth_client):
        """If unverified fields exist, action_needed should be non-null."""
        r = auth_client.get(
            "/admin/fieldmap/arnona/status",
            headers={"X-API-Key": "test-key-12345"},
        )
        body = r.json()
        # Status is either 'ok' (all verified) or 'placeholder_ids_present'
        if body["status"] in ("placeholder_ids_present", "not_loaded"):
            assert body["action_needed"] is not None
            assert len(body["action_needed"]) > 0
        else:  # status == "ok"
            assert body["action_needed"] is None

    def test_endpoint_status_response_structure(self, auth_client):
        """The status endpoint returns all required keys."""
        r = auth_client.get(
            "/admin/fieldmap/arnona/status",
            headers={"X-API-Key": "test-key-12345"},
        )
        body = r.json()
        # Status must be one of the known values
        assert body["status"] in ("ok", "placeholder_ids_present", "not_loaded")
