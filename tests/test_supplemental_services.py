"""
Supplemental services tests (v0.7) — app/mappers/supplemental_services.py.

Locks in the fix for production bug #3: an address-update add-on purchased
with the transfer vanished into _unmapped and never reached the operator.
"""
from __future__ import annotations

from app.mappers.business_mapper import build_from_parsed
from app.mappers.supplemental_services import (
    SupplementalService,
    deserialize,
    parse_supplemental,
    serialize,
    validate_supplemental,
)


def _parsed(**overrides) -> dict:
    p = {
        "basic": {"סוג_מעבר": "מתחיל שכירות", "עיר": "תל אביב"},
        "customer": {"שם_פרטי": "ישראל"},
        "partner": {}, "outgoing": {}, "landlord": {},
        "property": {}, "arnona": {}, "documents": {},
        "payment": {}, "fhs": {}, "_unmapped": {},
    }
    for k, v in overrides.items():
        p[k] = v
    return p


class TestParser:
    def test_address_update_in_unmapped(self):
        p = _parsed(_unmapped={"q612_input612": "רכשתי גם עדכון כתובת בדואר"})
        found = parse_supplemental(p)
        assert [s.key for s in found] == ["address_update"]
        assert found[0].source == "_unmapped:q612_input612"
        assert found[0].label_he == "עדכון כתובת"

    def test_address_update_in_selected_services(self):
        p = _parsed()
        p["basic"]["שירותים_נבחרים"] = ["ארנונה", "עדכון כתובת"]
        assert "address_update" in [s.key for s in parse_supplemental(p)]

    def test_dedicated_field_preferred_source(self):
        p = _parsed()
        p["basic"]["שירותים_נוספים"] = ["עדכון כתובת"]
        found = parse_supplemental(p)
        assert found[0].source == "basic.שירותים_נוספים"

    def test_package_description_detected(self):
        p = _parsed(payment={"שם_שירות": "חבילה + העברת דואר"})
        assert "mail_forwarding" in [s.key for s in parse_supplemental(p)]

    def test_deduplicated_across_sources(self):
        p = _parsed(_unmapped={"q1": "עדכון כתובת", "q2": "שינוי כתובת"})
        found = parse_supplemental(p)
        assert len([s for s in found if s.key == "address_update"]) == 1

    def test_nothing_detected(self):
        assert parse_supplemental(_parsed()) == []

    def test_core_transfer_services_are_not_supplemental(self):
        p = _parsed()
        p["basic"]["שירותים_נבחרים"] = ["ארנונה", "מים", "חשמל"]
        # חשמל is a core transfer service — must not surface as internet/gas
        assert [s.key for s in parse_supplemental(p)] == []


class TestValidation:
    def test_valid_list(self):
        found = parse_supplemental(_parsed(_unmapped={"q1": "עדכון כתובת"}))
        assert validate_supplemental(found) == []

    def test_unknown_key(self):
        issues = validate_supplemental([SupplementalService(key="jetpack")])
        assert any("unknown" in i for i in issues)

    def test_duplicate_key(self):
        svc = SupplementalService(key="address_update")
        issues = validate_supplemental([svc, svc])
        assert any("duplicate" in i for i in issues)

    def test_empty_key(self):
        issues = validate_supplemental([SupplementalService(key="")])
        assert any("empty key" in i for i in issues)


class TestSerialization:
    def test_round_trip(self):
        original = [SupplementalService(
            key="address_update", label_he="עדכון כתובת",
            label_en="Address update", source="_unmapped:q1",
            raw_value="עדכון כתובת",
        )]
        restored = deserialize(serialize(original))
        assert restored == original

    def test_deserialize_garbage(self):
        assert deserialize(None) == []
        assert deserialize("nope") == []
        assert deserialize([1, "x"]) == []


class TestModelIntegration:
    def test_business_submission_carries_supplemental(self):
        p = _parsed(_unmapped={"q612": "עדכון כתובת"})
        bs = build_from_parsed(p)
        assert bs.supplemental_services
        assert bs.supplemental_services[0]["key"] == "address_update"

    def test_survives_json_round_trip(self):
        from app.mappers.models import BusinessSubmission
        p = _parsed(_unmapped={"q612": "עדכון כתובת"})
        bs = BusinessSubmission.from_dict(build_from_parsed(p).to_dict())
        assert bs.supplemental_services[0]["key"] == "address_update"

    def test_summary_section_present(self):
        p = _parsed(_unmapped={"q612": "עדכון כתובת"})
        summary = build_from_parsed(p).to_summary_dict()
        assert summary.get("שירותים_נוספים") == {"עדכון כתובת": "✅"}

    def test_summary_section_absent_when_none(self):
        summary = build_from_parsed(_parsed()).to_summary_dict()
        assert "שירותים_נוספים" not in summary
