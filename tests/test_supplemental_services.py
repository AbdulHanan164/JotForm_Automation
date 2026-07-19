"""
Supplemental services tests (v0.7) — app/mappers/supplemental_services.py.

Locks in the fix for production bug #3 (an address-update add-on never reached
the operator) AND the historical-replay finding of 2026-07-19: the original
``_unmapped`` scan detected address_update on 58/58 production submissions
because JotForm posts static text-widget content (price labels like
"עדכון כתובת בתעודת זהות 79 ₪", QIDs q620/q626/q491) with EVERY submission.
Detection now reads only selection-type sources — the mapped שירותים_נוספים
multi-select (q568/q569/q630) — and honors explicit declines ("לא תודה - ...").

Ground truth from the replay corpus: 12/58 purchased, 20/58 declined by name,
the rest were never shown the option.
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
    def test_purchase_via_mapped_multiselect(self):
        # Exact production answer shape (q568_input568, submission 6575109173857311701)
        p = _parsed()
        p["basic"]["שירותים_נוספים"] = ["עדכון כתובת בתעודת זהות 79 ₪"]
        found = parse_supplemental(p)
        assert [s.key for s in found] == ["address_update"]
        assert found[0].source == "basic.שירותים_נוספים"
        assert found[0].label_he == "עדכון כתובת"

    def test_decline_is_not_a_purchase(self):
        # Exact production decline shape (q568_input568, submission 6572619314413228027)
        p = _parsed()
        p["basic"]["שירותים_נוספים"] = [
            "לא תודה - עדכון כתובת בתעודת זהות",
            "לא תודה - ביטוח ,הוראת קבע ,תו חניה",
        ]
        assert parse_supplemental(p) == []

    def test_static_widget_text_in_unmapped_is_ignored(self):
        # REGRESSION (replay 2026-07-19): q620/q626/q491 static price labels
        # arrive with EVERY submission — must never register as a purchase.
        p = _parsed(_unmapped={
            "q620_input620": "עדכון כתובת בתעודת זהות 79 ₪",
            "q626_input626": "יציאה - עדכון כתובת בתעודת הזהות 79 ₪",
            "q491_input491": "עדכון כתובת",
        })
        assert parse_supplemental(p) == []

    def test_purchase_and_decline_mixed(self):
        p = _parsed()
        p["basic"]["שירותים_נוספים"] = [
            "עדכון כתובת בתעודת זהות 79 ₪",
            "לא תודה - ביטוח",
        ]
        assert [s.key for s in parse_supplemental(p)] == ["address_update"]

    def test_negation_is_word_boundary_aware(self):
        # "אינטרנט" contains the letters of "אין" — must still be detected.
        p = _parsed()
        p["basic"]["שירותים_נוספים"] = ["חיבור אינטרנט וטלוויזיה"]
        assert [s.key for s in parse_supplemental(p)] == ["internet_tv"]

    def test_package_description_detected(self):
        p = _parsed(payment={"שם_שירות": "חבילה + העברת דואר"})
        assert "mail_forwarding" in [s.key for s in parse_supplemental(p)]

    def test_deduplicated_across_sources(self):
        p = _parsed(payment={"שם_שירות": "עדכון כתובת"})
        p["basic"]["שירותים_נוספים"] = ["עדכון כתובת בתעודת זהות 79 ₪"]
        found = [s for s in parse_supplemental(p) if s.key == "address_update"]
        assert len(found) == 1
        assert found[0].source == "basic.שירותים_נוספים"   # most authoritative wins

    def test_nothing_detected(self):
        assert parse_supplemental(_parsed()) == []

    def test_core_transfer_services_are_not_supplemental(self):
        p = _parsed()
        p["basic"]["שירותים_נבחרים"] = ["ארנונה", "מים", "חשמל"]
        assert [s.key for s in parse_supplemental(p)] == []


class TestValidation:
    def test_valid_list(self):
        p = _parsed()
        p["basic"]["שירותים_נוספים"] = ["עדכון כתובת"]
        assert validate_supplemental(parse_supplemental(p)) == []

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
            label_en="Address update", source="basic.שירותים_נוספים",
            raw_value="עדכון כתובת בתעודת זהות 79 ₪",
        )]
        restored = deserialize(serialize(original))
        assert restored == original

    def test_deserialize_garbage(self):
        assert deserialize(None) == []
        assert deserialize("nope") == []
        assert deserialize([1, "x"]) == []


class TestModelIntegration:
    def _purchase(self) -> dict:
        p = _parsed()
        p["basic"]["שירותים_נוספים"] = ["עדכון כתובת בתעודת זהות 79 ₪"]
        return p

    def test_business_submission_carries_supplemental(self):
        bs = build_from_parsed(self._purchase())
        assert bs.supplemental_services
        assert bs.supplemental_services[0]["key"] == "address_update"

    def test_survives_json_round_trip(self):
        from app.mappers.models import BusinessSubmission
        bs = BusinessSubmission.from_dict(build_from_parsed(self._purchase()).to_dict())
        assert bs.supplemental_services[0]["key"] == "address_update"

    def test_summary_section_present(self):
        summary = build_from_parsed(self._purchase()).to_summary_dict()
        assert summary.get("שירותים_נוספים") == {"עדכון כתובת": "✅"}

    def test_summary_section_absent_when_none(self):
        summary = build_from_parsed(_parsed()).to_summary_dict()
        assert "שירותים_נוספים" not in summary

    def test_decliner_summary_has_no_section(self):
        p = _parsed()
        p["basic"]["שירותים_נוספים"] = ["לא תודה - עדכון כתובת בתעודת זהות"]
        summary = build_from_parsed(p).to_summary_dict()
        assert "שירותים_נוספים" not in summary
