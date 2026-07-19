"""
Canonical document vocabulary tests (v0.7) — app/core/doc_types.py and the
alias-aware manifest lookup in app/documents/storage.py.

These lock in the fix for the production bug where a file classified as
"tabu_document" never satisfied the "tabu" requirement and was re-requested
from the customer forever.
"""
from __future__ import annotations

import json

import pytest

from app.core import doc_types as dt
from app.documents import storage


class TestCanonicalize:
    def test_canonical_type_passes_through(self):
        assert dt.canonicalize("tabu") == "tabu"
        assert dt.canonicalize("lease_contract") == "lease_contract"

    def test_classifier_alias_resolves(self):
        assert dt.canonicalize("tabu_document") == "tabu"
        assert dt.canonicalize("corporation_certificate") == "corp_cert"
        assert dt.canonicalize("lease") == "lease_contract"

    def test_hebrew_label_resolves(self):
        assert dt.canonicalize("נסח_טאבו") == "tabu"
        assert dt.canonicalize("חוזה_שכירות") == "lease_contract"
        assert dt.canonicalize("חשבון_מים") == "water_bill"

    def test_unknown_and_empty(self):
        assert dt.canonicalize("") == ""
        assert dt.canonicalize(None) == ""
        assert dt.canonicalize("mystery_doc") == ""

    def test_whitespace_tolerated(self):
        assert dt.canonicalize("  tabu_document  ") == "tabu"


class TestSatisfaction:
    def test_tabu_satisfied_by_alias_spellings(self):
        keys = dt.manifest_keys_satisfying("tabu")
        assert "tabu" in keys
        assert "tabu_document" in keys

    def test_contract_requirement_accepts_sale_and_lease(self):
        keys = dt.manifest_keys_satisfying("lease_contract")
        assert {"lease_contract", "sale_contract", "lease"}.issubset(keys)
        keys = dt.manifest_keys_satisfying("sale_contract")
        assert {"lease_contract", "sale_contract"}.issubset(keys)

    def test_strict_types_not_cross_satisfied(self):
        assert "arnona_bill" not in dt.manifest_keys_satisfying("tabu")
        assert "id_photo" not in dt.manifest_keys_satisfying("signature")


class TestLabelsAndStems:
    def test_hebrew_label_via_alias(self):
        assert dt.hebrew_label("tabu_document") == "נסח_טאבו"

    def test_filename_stem_via_alias(self):
        assert dt.filename_stem("tabu_document") == "tabu"

    def test_storage_delegates(self):
        assert storage.doc_type_for_label("נסח_טאבו") == "tabu"
        assert storage.hebrew_label_for("tabu_document") == "נסח_טאבו"
        assert storage.filename_stem_for("lease_contract") == "lease"

    def test_summary_view_still_six_types(self):
        assert set(storage.DOC_TYPES) == {
            "id_photo", "lease_contract", "signature",
            "arnona_bill", "corp_cert", "tabu",
        }


@pytest.fixture()
def docs_root(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "documents_dir", tmp_path)
    return tmp_path


def _write_manifest(root, sub_id: str, documents: dict) -> None:
    d = root / sub_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "_manifest.json").write_text(
        json.dumps({"submission_id": sub_id, "documents": documents},
                   ensure_ascii=False),
        encoding="utf-8",
    )


class TestManifestStatus:
    def test_alias_key_resolves_requirement(self, docs_root):
        _write_manifest(docs_root, "s1", {"tabu_document": {"status": "present"}})
        assert storage.manifest_status("s1", "tabu") == "present"
        assert storage.manifest_resolves("s1", "tabu") is True

    def test_needs_review_counts_as_supplied(self, docs_root):
        _write_manifest(docs_root, "s2", {"id_photo": {"status": "needs_review"}})
        assert storage.manifest_status("s2", "id_photo") == "needs_review"
        assert storage.manifest_resolves("s2", "id_photo") is True

    def test_present_beats_needs_review(self, docs_root):
        _write_manifest(docs_root, "s3", {
            "lease_contract": {"status": "needs_review"},
            "sale_contract":  {"status": "present"},
        })
        assert storage.manifest_status("s3", "lease_contract") == "present"

    def test_missing_manifest(self, docs_root):
        assert storage.manifest_status("nope", "tabu") == ""
        assert storage.manifest_resolves("nope", "tabu") is False

    def test_empty_submission_id(self, docs_root):
        assert storage.manifest_status("", "tabu") == ""

    def test_corrupt_manifest_is_safe(self, docs_root):
        d = docs_root / "s4"
        d.mkdir()
        (d / "_manifest.json").write_text("{not json", encoding="utf-8")
        assert storage.manifest_status("s4", "tabu") == ""
