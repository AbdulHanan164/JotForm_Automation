"""
Canonical requirement engine tests (v0.7) — app/rules/requirements.py.

Locks in the fixes for production bug #4 ("requesting things that are not
required, missing things that are required, re-requesting supplied docs"):
  * requirements conditioned on transaction traits
  * substring service matching (empty selection = arnona-relevant)
  * alias-aware, needs_review-aware manifest resolution
"""
from __future__ import annotations

import json

import pytest

from app.mappers.business_mapper import build_from_parsed
from app.rules.requirements import detect_missing


DOC_PRESENT = {"present": True, "url": "https://example.com/f.pdf"}


def _parsed(move="מתחיל שכירות", *, services=None, docs=True, **overrides) -> dict:
    p = {
        "basic": {
            "סוג_מעבר": move,
            "עיר": "תל אביב",
            "תאריך_כניסה": "01/01/2026",
            "סוג_לקוח": "פרטי",
        },
        "customer": {"שם_פרטי": "ישראל", "שם_משפחה": "ישראלי",
                     "תעודת_זהות": "123456789", "טלפון": "0501234567",
                     "אימייל": "israel@example.com"},
        "partner": {}, "outgoing": {},
        "landlord": {"שם_פרטי": "בעל", "שם_משפחה": "בית", "טלפון": "0507654321"},
        "property": {"רחוב": "הרצל"},
        "arnona": {"מספר_נכס": "1", "מספר_לקוח": "2", "מספר_זיהוי_נכס": "3"},
        "documents": {
            "תעודת_זהות": DOC_PRESENT, "חוזה_שכירות": DOC_PRESENT,
            "חתימה": DOC_PRESENT, "חשבון_ארנונה": DOC_PRESENT,
        } if docs else {},
        "payment": {}, "fhs": {}, "_unmapped": {},
    }
    if services is not None:
        p["basic"]["שירותים_נבחרים"] = services
    for section, values in overrides.items():
        p.setdefault(section, {}).update(values)
    return p


def _missing(parsed, visibility=None):
    return detect_missing(build_from_parsed(parsed), visibility)


def _info_ids(result):
    return [r["id"] for r in result["missing_info"]]


def _doc_ids(result):
    return [r["id"] for r in result["missing_docs"]]


class TestRentalStartComplete:
    def test_complete_submission_is_complete(self):
        result = _missing(_parsed())
        assert result["missing_info"] == []
        assert result["missing_docs"] == []
        assert result["is_complete"] is True

    def test_landlord_phone_required(self):
        p = _parsed()
        p["landlord"] = {}
        assert "owner_phone" in _info_ids(_missing(p))

    def test_output_shape_is_stable(self):
        p = _parsed()
        p["customer"].pop("טלפון")
        item = [r for r in _missing(p)["missing_info"] if r["id"] == "customer_phone"][0]
        assert set(item) == {"id", "label", "reason", "rule_triggered", "was_field_visible"}
        assert item["label"] == "טלפון"


class TestServiceRelevance:
    def test_empty_services_requires_arnona(self):
        p = _parsed()
        p["arnona"].pop("מספר_נכס")
        assert "arnona_property_number" in _info_ids(_missing(p))

    def test_substring_service_match(self):
        p = _parsed(services=["העברת ארנונה"])
        p["arnona"].pop("מספר_נכס")
        assert "arnona_property_number" in _info_ids(_missing(p))

    def test_non_arnona_services_skip_arnona_requirements(self):
        p = _parsed(services=["מים", "חשמל"])
        p["arnona"] = {}
        p["documents"].pop("חשבון_ארנונה")
        result = _missing(p)
        assert "arnona_property_number" not in _info_ids(result)
        assert "arnona_bill" not in _doc_ids(result)

    def test_arnona_bill_required_when_relevant(self):
        p = _parsed()
        p["documents"].pop("חשבון_ארנונה")
        assert "arnona_bill" in _doc_ids(_missing(p))


class TestVisibility:
    def test_hidden_field_not_flagged(self):
        p = _parsed()
        p["arnona"].pop("מספר_נכס")
        result = _missing(p, {"מספר_נכס": False})
        assert "arnona_property_number" not in _info_ids(result)

    def test_visible_field_flagged(self):
        p = _parsed()
        p["arnona"].pop("מספר_נכס")
        assert "arnona_property_number" in _info_ids(_missing(p, {}))


class TestTermination:
    """Rental termination has NO incoming tenant — pre-v0.7 every termination
    was flagged with four false 'missing incoming tenant' items."""

    def test_no_incoming_requirements(self):
        p = _parsed(move="מסיים שכירות")
        ids = _info_ids(_missing(p))
        for rid in ("customer_name", "customer_phone", "customer_email", "customer_id"):
            assert rid not in ids

    def test_outgoing_contact_required(self):
        # Router maps the customer section to the outgoing role, so a complete
        # submission passes; strip the customer ID to see the outgoing rule.
        p = _parsed(move="מסיים שכירות")
        p["customer"].pop("תעודת_זהות")
        assert "outgoing_id" in _info_ids(_missing(p))

    def test_move_out_required(self):
        p = _parsed(move="מסיים שכירות")
        assert "move_out_date" in _info_ids(_missing(p))
        p["basic"]["תאריך_יציאה"] = "01/02/2026"
        assert "move_out_date" not in _info_ids(_missing(p))

    def test_move_in_not_required(self):
        p = _parsed(move="מסיים שכירות")
        p["basic"].pop("תאריך_כניסה")
        assert "move_in_date" not in _info_ids(_missing(p))


class TestCoupleRequirements:
    def test_couple_without_partner_data_flags_partner(self):
        p = _parsed()
        p["basic"]["שותפים"] = "זוג נשוי"
        ids = _info_ids(_missing(p))
        assert "partner_name" in ids
        assert "partner_id" in ids

    def test_partner_data_without_id_flags_id_only(self):
        p = _parsed(partner={"שם_פרטי": "דנה", "טלפון": "0521112233"})
        ids = _info_ids(_missing(p))
        assert "partner_id" in ids
        assert "partner_name" not in ids

    def test_complete_couple_passes(self):
        p = _parsed(partner={"שם_פרטי": "דנה", "שם_משפחה": "כהן",
                             "תעודת_זהות": "087654321", "טלפון": "0521112233"})
        p["basic"]["שותפים"] = "זוג נשוי"
        ids = _info_ids(_missing(p))
        assert "partner_id" not in ids
        assert "partner_name" not in ids


class TestSaleAndOwnerFlows:
    def test_sale_purchase_needs_sale_contract_not_landlord(self):
        p = _parsed(move="בעל בית", docs=False)
        p["basic"]["סוג_משכיר"] = "קונה"
        result = _missing(p)
        assert "owner_phone" not in _info_ids(result)
        doc_ids = _doc_ids(result)
        assert "sale_contract" in doc_ids
        assert "lease_contract" not in doc_ids

    def test_sale_contract_satisfied_by_form_contract_upload(self):
        p = _parsed(move="בעל בית")
        p["basic"]["סוג_משכיר"] = "קונה"
        assert "sale_contract" not in _doc_ids(_missing(p))

    def test_owner_return_needs_tabu_not_contract(self):
        p = _parsed(move="בעל בית", docs=False)
        p["basic"]["סוג_משכיר"] = "חוזר לנכס"
        result = _missing(p)
        doc_ids = _doc_ids(result)
        assert "tabu" in doc_ids
        assert "lease_contract" not in doc_ids
        assert "sale_contract" not in doc_ids
        assert "owner_phone" not in _info_ids(result)


class TestCompany:
    def test_company_requirements(self):
        p = _parsed(docs=False)
        p["basic"]["סוג_לקוח"] = "חברה"
        result = _missing(p)
        doc_ids = _doc_ids(result)
        assert "corp_cert" in doc_ids
        assert "tabu" in doc_ids
        assert "id_photo" not in doc_ids
        assert "customer_id" not in _info_ids(result)


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


class TestManifestResolution:
    """Documents supplied via the Missing-Documents form must never be
    re-requested — including alias spellings and needs_review files."""

    def _parsed_with_id(self, sub_id: str, **kw) -> dict:
        p = _parsed(docs=False, **kw)
        p["system"] = {"submission_id": sub_id}
        return p

    def test_alias_manifest_key_resolves(self, docs_root):
        p = self._parsed_with_id("m1")
        p["basic"]["סוג_לקוח"] = "חברה"
        _write_manifest(docs_root, "m1", {
            "tabu_document": {"status": "present"},
            "corp_cert": {"status": "present"},
            "lease_contract": {"status": "present"},
            "signature": {"status": "present"},
            "arnona_bill": {"status": "present"},
        })
        assert _doc_ids(_missing(p)) == []

    def test_needs_review_not_rerequested(self, docs_root):
        p = self._parsed_with_id("m2")
        _write_manifest(docs_root, "m2", {"id_photo": {"status": "needs_review"}})
        assert "id_photo" not in _doc_ids(_missing(p))

    def test_missing_status_still_requested(self, docs_root):
        p = self._parsed_with_id("m3")
        _write_manifest(docs_root, "m3", {"id_photo": {"status": "missing"}})
        assert "id_photo" in _doc_ids(_missing(p))

    def test_sale_contract_manifest_satisfies_lease_requirement(self, docs_root):
        p = self._parsed_with_id("m4")
        _write_manifest(docs_root, "m4", {"sale_contract": {"status": "present"}})
        assert "lease_contract" not in _doc_ids(_missing(p))


class TestEngineErrorPath:
    def test_service_reports_engine_error_loudly(self):
        """ArnonaService.detect_missing must never silently switch rule sets;
        on engine failure it marks the submission incomplete with a marker."""
        from app.services.arnona.service import ArnonaService
        svc = ArnonaService()
        result = svc.detect_missing({"_business": {"submission": "not-a-dict"}}, {}, {})
        assert result["is_complete"] is False
        assert "engine_error" in result
