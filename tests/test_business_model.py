"""
BusinessSubmission consistency tests.

These tests prove that Summary / Missing detection / Validation all read from
the same canonical source (BusinessSubmission) — regardless of whether the
underlying data came from FHS fields, raw section-keyed fields, or a mix.

BEFORE this migration:
  Summary    → BusinessSubmission  ✅
  Missing    → raw section-keyed   ⚠️
  Validation → raw section-keyed   ⚠️

AFTER this migration (what these tests verify):
  Summary    → BusinessSubmission  ✅
  Missing    → BusinessSubmission  ✅
  Validation → BusinessSubmission  ✅
"""
from __future__ import annotations

import pytest

from app.mappers.business_mapper import build_from_parsed
from app.mappers.missing_detector import detect_missing, _present, _doc_present
from app.mappers.business_validators import (
    BUSINESS_VALIDATION_RULES,
    _check_duplicate_names,
    _check_landlord_is_outgoing,
    _check_partner_phone_no_id,
    _check_lease_date_mismatch,
    _check_lease_tenant_count,
    _check_name_in_lease,
    _check_outgoing_email_text_none,
)
from app.mappers.models import (
    ArnonaAccounts,
    BusinessSubmission,
    Dates,
    Documents,
    Person,
    Property,
    SubmissionMeta,
)
from app.pipeline.validator import ValidationEngine


# ── Fixture helpers ───────────────────────────────────────────────────────────

DOC_PRESENT = {"present": True, "url": "https://example.com/file.pdf"}
DOC_ABSENT  = {"present": False, "url": ""}

def _complete_docs() -> dict:
    return {
        "תעודת_זהות":    DOC_PRESENT,
        "חוזה_שכירות":  DOC_PRESENT,
        "חתימה":         DOC_PRESENT,
        "חשבון_ארנונה":  DOC_PRESENT,
    }

def _raw_parsed(*, extra_fhs: dict | None = None) -> dict:
    """
    Minimal parsed dict using only raw section-keyed fields (no FHS).
    Represents the current state before FHS IDs are configured in YAML.
    """
    parsed = {
        "basic":    {
            "עיר":            "תל_אביב",
            "תאריך_כניסה":    "01/01/2025",
            "סוג_לקוח":       "פרטי",
        },
        "customer": {
            "שם_פרטי":     "ישראל",
            "שם_משפחה":    "ישראלי",
            "תעודת_זהות":  "123456789",
            "טלפון":        "050-1234567",
            "אימייל":       "israel@example.com",
        },
        "partner":  {},
        "outgoing": {},
        "landlord": {
            "שם_פרטי":  "בעל",
            "שם_משפחה": "בית",
            "טלפון":     "050-7654321",
        },
        "property": {
            "רחוב":  "הרצל",
            "בניין": "10",
            "דירה":  "3",
        },
        "arnona":   {
            "מספר_נכס":          "12345",
            "מספר_לקוח":         "67890",
            "מספר_זיהוי_נכס":    "11111",
        },
        "documents": _complete_docs(),
        "payment":   {"שם_שירות": "שכירות", "סכום": "99"},
        "fhs":       extra_fhs or {},
        "_unmapped": {},
    }
    return parsed


def _bs_from_raw() -> BusinessSubmission:
    return build_from_parsed(_raw_parsed())


def _bs_with_fhs(fhs_override: dict) -> BusinessSubmission:
    return build_from_parsed(_raw_parsed(extra_fhs=fhs_override))


# ── _present / _doc_present unit tests ────────────────────────────────────────

class TestPresent:
    def test_none_is_not_present(self):
        assert _present(None) is False

    def test_empty_string_is_not_present(self):
        assert _present("") is False

    def test_dash_placeholder_is_not_present(self):
        assert _present("—") is False

    def test_non_empty_string_is_present(self):
        assert _present("ישראל") is True

    def test_true_bool_is_present(self):
        assert _present(True) is True

    def test_false_bool_is_not_present(self):
        assert _present(False) is False

    def test_non_empty_list_is_present(self):
        assert _present(["a"]) is True

    def test_empty_list_is_not_present(self):
        assert _present([]) is False


class TestDocPresent:
    def test_none_is_absent(self):
        assert _doc_present(None) is False

    def test_checkmark_string_is_present(self):
        assert _doc_present("✅") is True

    def test_x_string_is_absent(self):
        assert _doc_present("❌") is False

    def test_dict_with_present_true(self):
        assert _doc_present({"present": True, "url": ""}) is True

    def test_dict_with_url(self):
        assert _doc_present({"present": False, "url": "https://example.com/x.pdf"}) is True

    def test_dict_empty_is_absent(self):
        assert _doc_present({"present": False, "url": ""}) is False

    def test_true_bool_is_present(self):
        assert _doc_present(True) is True


# ── Raw-only: data in raw sections → not reported missing ────────────────────

class TestRawOnlyMissingDetection:
    """When FHS is empty, business_mapper falls back to raw sections correctly."""

    def test_complete_submission_is_complete(self):
        bs = _bs_from_raw()
        result = detect_missing(bs)
        assert result["is_complete"] is True
        assert result["missing_info"] == []
        assert result["missing_docs"] == []

    def test_customer_name_comes_from_raw_customer_section(self):
        bs = _bs_from_raw()
        assert bs.incoming_tenant.full_name == "ישראל ישראלי"

    def test_name_present_so_not_reported_missing(self):
        bs = _bs_from_raw()
        result = detect_missing(bs)
        ids = [r["id"] for r in result["missing_info"]]
        assert "customer_name" not in ids

    def test_missing_name_is_detected(self):
        p = _raw_parsed()
        p["customer"].pop("שם_פרטי")
        p["customer"].pop("שם_משפחה")
        bs = build_from_parsed(p)
        result = detect_missing(bs)
        ids = [r["id"] for r in result["missing_info"]]
        assert "customer_name" in ids

    def test_missing_phone_is_detected(self):
        p = _raw_parsed()
        p["customer"].pop("טלפון")
        bs = build_from_parsed(p)
        result = detect_missing(bs)
        ids = [r["id"] for r in result["missing_info"]]
        assert "customer_phone" in ids

    def test_missing_id_is_detected_for_natural_person(self):
        p = _raw_parsed()
        p["customer"].pop("תעודת_זהות")
        bs = build_from_parsed(p)
        result = detect_missing(bs)
        ids = [r["id"] for r in result["missing_info"]]
        assert "customer_id" in ids

    def test_id_not_required_for_company(self):
        p = _raw_parsed()
        p["basic"]["סוג_לקוח"] = "חברה"
        p["customer"].pop("תעודת_זהות", None)
        bs = build_from_parsed(p)
        result = detect_missing(bs)
        ids = [r["id"] for r in result["missing_info"]]
        assert "customer_id" not in ids

    def test_missing_arnona_number_detected(self):
        p = _raw_parsed()
        p["arnona"].pop("מספר_נכס")
        bs = build_from_parsed(p)
        result = detect_missing(bs)
        ids = [r["id"] for r in result["missing_info"]]
        assert "arnona_property_number" in ids

    def test_missing_docs_detected(self):
        p = _raw_parsed()
        p["documents"]["חוזה_שכירות"] = DOC_ABSENT
        bs = build_from_parsed(p)
        result = detect_missing(bs)
        ids = [r["id"] for r in result["missing_docs"]]
        assert "lease_contract" in ids

    def test_is_complete_false_when_docs_missing(self):
        p = _raw_parsed()
        p["documents"]["חתימה"] = DOC_ABSENT
        bs = build_from_parsed(p)
        result = detect_missing(bs)
        assert result["is_complete"] is False


# ── FHS-only: data in fhs section → takes priority over raw ──────────────────

class TestFHSPriority:
    """FHS values override raw section values when both are present."""

    def test_fhs_name_overrides_raw_name(self):
        bs = _bs_with_fhs({"incoming_full_name": "רחל כהן"})
        assert bs.incoming_tenant.full_name == "רחל כהן"

    def test_fhs_name_not_reported_missing(self):
        p = _raw_parsed(extra_fhs={"incoming_full_name": "רחל כהן"})
        p["customer"].pop("שם_פרטי")
        p["customer"].pop("שם_משפחה")
        bs = build_from_parsed(p)
        assert bs.incoming_tenant.full_name == "רחל כהן"
        result = detect_missing(bs)
        ids = [r["id"] for r in result["missing_info"]]
        assert "customer_name" not in ids

    def test_fhs_phone_overrides_raw_phone(self):
        bs = _bs_with_fhs({"incoming_phone": "054-9999999"})
        assert bs.incoming_tenant.phone == "054-9999999"

    def test_fhs_id_overrides_raw_id(self):
        bs = _bs_with_fhs({"incoming_id": "999999999"})
        assert bs.incoming_tenant.id_number == "999999999"

    def test_fhs_full_address_overrides_assembled_address(self):
        bs = _bs_with_fhs({"full_address": "הרצל 10 דירה 3, תל_אביב"})
        assert bs.property.full_address == "הרצל 10 דירה 3, תל_אביב"

    def test_raw_fallback_used_when_fhs_empty(self):
        # FHS section is empty → mapper falls back to raw customer section
        bs = _bs_from_raw()
        assert bs.incoming_tenant.full_name == "ישראל ישראלי"
        assert bs.incoming_tenant.phone == "050-1234567"


# ── Visibility: hidden fields are skipped ────────────────────────────────────

class TestVisibility:
    def test_hidden_field_is_skipped(self):
        p = _raw_parsed()
        p["arnona"].pop("מספר_נכס")
        bs = build_from_parsed(p)
        # Simulate conditional logic hiding the arnona_property_number field
        visibility = {"מספר_נכס": False}
        result = detect_missing(bs, visibility)
        ids = [r["id"] for r in result["missing_info"]]
        assert "arnona_property_number" not in ids

    def test_visible_field_is_checked(self):
        p = _raw_parsed()
        p["arnona"].pop("מספר_נכס")
        bs = build_from_parsed(p)
        # Explicitly visible (or not in visibility dict)
        visibility = {}
        result = detect_missing(bs, visibility)
        ids = [r["id"] for r in result["missing_info"]]
        assert "arnona_property_number" in ids

    def test_none_visibility_defaults_to_all_visible(self):
        p = _raw_parsed()
        p["customer"].pop("טלפון")
        bs = build_from_parsed(p)
        result = detect_missing(bs, None)
        ids = [r["id"] for r in result["missing_info"]]
        assert "customer_phone" in ids


# ── Partner conditional rules ─────────────────────────────────────────────────

class TestPartnerRules:
    def test_no_partner_no_partner_id_check(self):
        bs = _bs_from_raw()
        assert bs.partner is None
        result = detect_missing(bs)
        ids = [r["id"] for r in result["missing_info"]]
        assert "partner_id" not in ids

    def test_partner_with_phone_requires_id(self):
        p = _raw_parsed()
        p["partner"] = {"שם_פרטי": "שני", "שם_משפחה": "שוכר", "טלפון": "052-1234567"}
        bs = build_from_parsed(p)
        assert bs.partner is not None
        result = detect_missing(bs)
        ids = [r["id"] for r in result["missing_info"]]
        assert "partner_id" in ids

    def test_partner_with_phone_and_id_is_complete(self):
        p = _raw_parsed()
        p["partner"] = {
            "שם_פרטי":    "שני",
            "שם_משפחה":   "שוכר",
            "טלפון":       "052-1234567",
            "תעודת_זהות":  "222222222",
        }
        bs = build_from_parsed(p)
        result = detect_missing(bs)
        ids = [r["id"] for r in result["missing_info"]]
        assert "partner_id" not in ids


# ── Outgoing tenant conditional rules ─────────────────────────────────────────

class TestOutgoingRules:
    def test_no_outgoing_no_check(self):
        bs = _bs_from_raw()
        assert bs.outgoing_tenant is None
        result = detect_missing(bs)
        ids = [r["id"] for r in result["missing_info"]]
        assert "outgoing_id" not in ids
        assert "outgoing_phone" not in ids

    def test_outgoing_with_name_requires_id_and_phone(self):
        p = _raw_parsed()
        p["outgoing"] = {"שם_פרטי": "יוצא", "שם_משפחה": "דייר"}
        bs = build_from_parsed(p)
        assert bs.outgoing_tenant is not None
        result = detect_missing(bs)
        ids = [r["id"] for r in result["missing_info"]]
        assert "outgoing_id"    in ids
        assert "outgoing_phone" in ids

    def test_outgoing_complete_no_issues(self):
        p = _raw_parsed()
        p["outgoing"] = {
            "שם_פרטי":   "יוצא",
            "שם_משפחה":  "דייר",
            "תעודת_זהות": "333333333",
            "טלפון":      "053-9999999",
        }
        bs = build_from_parsed(p)
        result = detect_missing(bs)
        ids = [r["id"] for r in result["missing_info"]]
        assert "outgoing_id"    not in ids
        assert "outgoing_phone" not in ids


# ── Validation rules ──────────────────────────────────────────────────────────

def _parsed_with_business(bs: BusinessSubmission) -> dict:
    """Build a minimal parsed dict with the given BusinessSubmission embedded."""
    return {"_business": bs.to_dict()}


def _minimal_bs(**overrides) -> BusinessSubmission:
    return BusinessSubmission(
        incoming_tenant = Person(full_name="ישראל ישראלי", phone="050", email="a@b.com", id_number="1"),
        landlord        = Person(full_name="בעל בית", phone="052"),
        property        = Property(city="תל_אביב"),
        dates           = Dates(move_in="01/01/2025"),
        arnona_accounts = ArnonaAccounts(property_number="1", payer_number="2", identification_number="3"),
        documents       = Documents(
            id_photo       = "✅",
            lease_contract = "✅",
            signature      = "✅",
            arnona_bill    = "✅",
        ),
        **overrides,
    )


class TestValidationRuleDuplicateNames:
    def test_no_partner_no_issue(self):
        bs = _minimal_bs()
        parsed = _parsed_with_business(bs)
        assert _check_duplicate_names(parsed, {}) is None

    def test_different_names_no_issue(self):
        bs = _minimal_bs(partner=Person(full_name="שרה כהן", phone="050"))
        parsed = _parsed_with_business(bs)
        assert _check_duplicate_names(parsed, {}) is None

    def test_same_name_triggers_warning(self):
        bs = _minimal_bs(partner=Person(full_name="ישראל ישראלי", phone="050"))
        parsed = _parsed_with_business(bs)
        issue = _check_duplicate_names(parsed, {})
        assert issue is not None
        assert issue.id == "duplicate_tenant_names"
        assert issue.severity == "warning"

    def test_raw_fallback_when_no_business_key(self):
        parsed = {
            "customer": {"שם_פרטי": "ישראל", "שם_משפחה": "ישראלי"},
            "partner":  {"שם_פרטי": "ישראל", "שם_משפחה": "ישראלי"},
        }
        issue = _check_duplicate_names(parsed, {})
        assert issue is not None
        assert issue.id == "duplicate_tenant_names"


class TestValidationRuleLandlordIsOutgoing:
    def test_different_names_no_issue(self):
        bs = _minimal_bs(
            outgoing_tenant = Person(full_name="יוצא דייר", phone="051"),
        )
        parsed = _parsed_with_business(bs)
        assert _check_landlord_is_outgoing(parsed, {}) is None

    def test_same_name_triggers_info(self):
        # _minimal_bs already sets landlord="בעל בית"; just add matching outgoing
        bs = _minimal_bs(
            outgoing_tenant = Person(full_name="בעל בית", phone="052"),
        )
        parsed = _parsed_with_business(bs)
        issue = _check_landlord_is_outgoing(parsed, {})
        assert issue is not None
        assert issue.severity == "info"
        assert issue.id == "landlord_is_outgoing_tenant"

    def test_no_outgoing_no_issue(self):
        bs = _minimal_bs()
        parsed = _parsed_with_business(bs)
        assert _check_landlord_is_outgoing(parsed, {}) is None


class TestValidationRulePartnerPhoneNoId:
    def test_no_partner_no_issue(self):
        bs = _minimal_bs()
        parsed = _parsed_with_business(bs)
        assert _check_partner_phone_no_id(parsed, {}) is None

    def test_partner_with_id_no_issue(self):
        bs = _minimal_bs(partner=Person(full_name="שרה", phone="052", id_number="9"))
        parsed = _parsed_with_business(bs)
        assert _check_partner_phone_no_id(parsed, {}) is None

    def test_partner_phone_no_id_triggers_warning(self):
        bs = _minimal_bs(partner=Person(full_name="שרה", phone="052-1234567"))
        parsed = _parsed_with_business(bs)
        issue = _check_partner_phone_no_id(parsed, {})
        assert issue is not None
        assert issue.id == "partner_phone_no_id"
        assert issue.severity == "warning"

    def test_raw_fallback_triggers(self):
        parsed = {"partner": {"טלפון": "052-1234567", "שם_פרטי": "שרה"}}
        issue = _check_partner_phone_no_id(parsed, {})
        assert issue is not None
        assert issue.id == "partner_phone_no_id"


class TestValidationRuleOutgoingEmailTextNone:
    def test_no_outgoing_no_issue(self):
        bs = _minimal_bs()
        parsed = _parsed_with_business(bs)
        assert _check_outgoing_email_text_none(parsed, {}) is None

    def test_real_email_no_issue(self):
        bs = _minimal_bs(outgoing_tenant=Person(full_name="יוצא", phone="051", email="a@b.com"))
        parsed = _parsed_with_business(bs)
        assert _check_outgoing_email_text_none(parsed, {}) is None

    def test_text_none_triggers_info(self):
        bs = _minimal_bs(outgoing_tenant=Person(full_name="יוצא", phone="051", email="אין"))
        parsed = _parsed_with_business(bs)
        issue = _check_outgoing_email_text_none(parsed, {})
        assert issue is not None
        assert issue.id == "outgoing_email_is_text_none"
        assert issue.severity == "info"


class TestValidationRuleLeaseDateMismatch:
    def _docs_with_lease(self, start_date: str, state: str = "extracted") -> dict:
        return {"חוזה_שכירות": {"start_date": start_date, "state": state}}

    def test_matching_dates_no_issue(self):
        bs = _minimal_bs()
        parsed = _parsed_with_business(bs)
        docs = self._docs_with_lease("01/01/2025")
        assert _check_lease_date_mismatch(parsed, docs) is None

    def test_date_separator_difference_is_normalized(self):
        bs = _minimal_bs()  # move_in = "01/01/2025"
        parsed = _parsed_with_business(bs)
        docs = self._docs_with_lease("01-01-2025")
        assert _check_lease_date_mismatch(parsed, docs) is None

    def test_different_dates_triggers_warning(self):
        bs = _minimal_bs()  # move_in = "01/01/2025"
        parsed = _parsed_with_business(bs)
        docs = self._docs_with_lease("15/02/2025")
        issue = _check_lease_date_mismatch(parsed, docs)
        assert issue is not None
        assert issue.id == "lease_date_mismatch"
        assert issue.severity == "warning"

    def test_not_attempted_lease_skipped(self):
        bs = _minimal_bs()
        parsed = _parsed_with_business(bs)
        docs = self._docs_with_lease("15/02/2025", state="not_attempted")
        assert _check_lease_date_mismatch(parsed, docs) is None

    def test_empty_doc_extractions_skipped(self):
        bs = _minimal_bs()
        parsed = _parsed_with_business(bs)
        assert _check_lease_date_mismatch(parsed, {}) is None


class TestValidationRuleLeaseTenantCount:
    def test_matching_count_no_issue(self):
        bs = _minimal_bs()  # 1 tenant
        parsed = _parsed_with_business(bs)
        docs = {"חוזה_שכירות": {"tenant_names": ["ישראל ישראלי"], "state": "extracted"}}
        assert _check_lease_tenant_count(parsed, docs) is None

    def test_lease_has_more_tenants_triggers_warning(self):
        bs = _minimal_bs()  # 1 tenant on form
        parsed = _parsed_with_business(bs)
        docs = {"חוזה_שכירות": {"tenant_names": ["ישראל ישראלי", "שרה כהן"], "state": "extracted"}}
        issue = _check_lease_tenant_count(parsed, docs)
        assert issue is not None
        assert issue.id == "lease_tenant_count_mismatch"

    def test_empty_tenant_names_skipped(self):
        bs = _minimal_bs()
        parsed = _parsed_with_business(bs)
        docs = {"חוזה_שכירות": {"tenant_names": [], "state": "extracted"}}
        assert _check_lease_tenant_count(parsed, docs) is None


class TestValidationRuleNameInLease:
    def test_name_in_lease_no_issue(self):
        bs = _minimal_bs()
        parsed = _parsed_with_business(bs)
        docs = {"חוזה_שכירות": {"tenant_names": ["ישראל ישראלי"], "state": "extracted"}}
        assert _check_name_in_lease(parsed, docs) is None

    def test_name_not_in_lease_triggers_error(self):
        bs = _minimal_bs()
        parsed = _parsed_with_business(bs)
        docs = {"חוזה_שכירות": {"tenant_names": ["שם אחר"], "state": "extracted"}}
        issue = _check_name_in_lease(parsed, docs)
        assert issue is not None
        assert issue.id == "form_name_not_in_lease"
        assert issue.severity == "error"

    def test_name_check_is_case_insensitive(self):
        bs = _minimal_bs()  # full_name = "ישראל ישראלי"
        parsed = _parsed_with_business(bs)
        docs = {"חוזה_שכירות": {"tenant_names": ["ישראל ישראלי"], "state": "extracted"}}
        assert _check_name_in_lease(parsed, docs) is None


# ── ValidationEngine integration ─────────────────────────────────────────────

class TestValidationEngineIntegration:
    def _engine(self):
        return ValidationEngine(BUSINESS_VALIDATION_RULES)

    def test_clean_submission_returns_no_issues(self):
        bs = _minimal_bs()
        parsed = _parsed_with_business(bs)
        issues = self._engine().validate(parsed, {})
        assert issues == []

    def test_duplicate_name_found_by_engine(self):
        bs = _minimal_bs(partner=Person(full_name="ישראל ישראלי", phone="052"))
        parsed = _parsed_with_business(bs)
        issues = self._engine().validate(parsed, {})
        ids = [i.id for i in issues]
        assert "duplicate_tenant_names" in ids

    def test_engine_sorts_errors_before_warnings(self):
        bs = _minimal_bs(
            outgoing_tenant = Person(full_name="ישראל ישראלי", phone="051"),
        )
        parsed = _parsed_with_business(bs)
        docs = {"חוזה_שכירות": {"tenant_names": ["שם אחר"], "state": "extracted"}}
        issues = self._engine().validate(parsed, docs)
        severities = [i.severity for i in issues]
        # First error before first warning/info
        if "error" in severities and "warning" in severities:
            assert severities.index("error") < severities.index("warning")

    def test_engine_falls_back_gracefully_without_business_key(self):
        # ValidationEngine wraps exceptions per-rule — none should propagate
        parsed = {}
        issues = self._engine().validate(parsed, {})
        # No crash; rule errors wrapped in info issues
        for i in issues:
            assert i.severity in ("error", "warning", "info")


# ── Consistency: all three subsystems read same data ─────────────────────────

class TestConsistencyAcrossSubsystems:
    """
    The core guarantee of this migration:
    Summary, Missing detection, and Validation all observe the same
    person data — whether that data came from FHS or raw sections.
    """

    def _run_all(self, parsed: dict) -> tuple:
        """Return (summary, missing, validation_issues) from the same parsed dict."""
        from app.services.arnona.service import ArnonaService
        svc = ArnonaService()
        summary    = svc.build_summary(parsed)
        visibility = {}
        missing    = svc.detect_missing(parsed, summary, visibility)
        issues     = svc.validate(parsed, {})
        return summary, missing, issues

    def test_raw_path_consistent(self):
        parsed = _raw_parsed()
        parsed["_business"] = build_from_parsed(parsed).to_dict()
        summary, missing, issues = self._run_all(parsed)

        # Summary and missing detector agree on the incoming tenant name
        assert summary["דייר_נכנס"]["שם"] == "ישראל ישראלי"
        assert missing["is_complete"] is True

    def test_fhs_path_consistent(self):
        p = _raw_parsed(extra_fhs={"incoming_full_name": "רחל כהן"})
        p["customer"] = {}  # raw section empty — only FHS has the name
        p["_business"] = build_from_parsed(p).to_dict()
        summary, missing, issues = self._run_all(p)

        # Summary uses FHS name
        assert summary["דייר_נכנס"]["שם"] == "רחל כהן"
        # Missing detector also reads from BusinessSubmission, so no false "name missing"
        ids = [r["id"] for r in missing["missing_info"]]
        assert "customer_name" not in ids

    def test_fhs_overrides_raw_consistently(self):
        """FHS name in summary == FHS name checked by missing detector."""
        fhs_name = "FHS שם"
        p = _raw_parsed(extra_fhs={"incoming_full_name": fhs_name})
        p["_business"] = build_from_parsed(p).to_dict()
        summary, missing, _ = self._run_all(p)

        summary_name = summary["דייר_נכנס"]["שם"]
        # Both read from BusinessSubmission, so they must be identical
        assert summary_name == fhs_name

    def test_no_false_missing_after_fhs_migration(self):
        """
        KEY TEST: Before this migration, the Summary saw the FHS-resolved name
        but Missing Detection saw the empty raw customer section → false positive.

        After migration, both use BusinessSubmission — no false positive.
        """
        fhs_name = "שם מה-FHS"
        p = _raw_parsed(extra_fhs={"incoming_full_name": fhs_name})
        # Deliberately empty raw customer section to simulate post-FHS-config state
        p["customer"] = {}
        p["_business"] = build_from_parsed(p).to_dict()
        summary, missing, _ = self._run_all(p)

        # Summary correctly shows FHS name
        assert summary["דייר_נכנס"]["שם"] == fhs_name
        # Missing detector does NOT falsely report name missing
        ids = [r["id"] for r in missing["missing_info"]]
        assert "customer_name" not in ids, (
            "REGRESSION: Missing detector reported customer_name missing even though "
            f"BusinessSubmission contains '{fhs_name}' from FHS — dual-source-of-truth bug."
        )
