"""
Canonical transaction classifier tests (v0.7) — app/rules/transaction.py.

Locks in the fix for the production bug where a married couple was classified
as "Rental - Move In (Single)" because the classifier demanded the EXACT
string "זוג נשוי" in one specific mapped field.
"""
from __future__ import annotations

import pytest

from app.rules.transaction import (
    detect_transaction_type,
    normalize,
    partner_kind,
    role_routing,
)
from app.mappers.business_mapper import build_from_parsed


def _basic(move="מתחיל שכירות", **kw) -> dict:
    b = {"סוג_מעבר": move}
    b.update(kw)
    return b


class TestNormalize:
    def test_strips_bidi_marks(self):
        assert normalize("‏זוג נשוי‎") == "זוג נשוי"

    def test_collapses_whitespace_and_punctuation(self):
        assert normalize("  זוג   נשוי ") == "זוג נשוי"
        assert normalize('ת"ז') == "ת ז"

    def test_none_and_empty(self):
        assert normalize(None) == ""
        assert normalize("") == ""


class TestPartnerKind:
    @pytest.mark.parametrize("value", [
        "זוג נשוי", "בני זוג", "נשואים", "זוג", "נשוי",
        "‏זוג נשוי", "זוג-נשוי",
    ])
    def test_couple_variants(self, value):
        assert partner_kind(value) == "couple"

    @pytest.mark.parametrize("value", ["שותפים", "שותף", "שותפות"])
    def test_roommate_variants(self, value):
        assert partner_kind(value) == "roommates"

    def test_unknown_is_empty(self):
        assert partner_kind("לא") == ""
        assert partner_kind("") == ""


class TestRentalStart:
    def test_exact_couple_string(self):
        assert detect_transaction_type(_basic(שותפים="זוג נשוי")) == "rental_start_couple"

    def test_couple_variant_string(self):
        # THE production bug: any variance from the exact literal fell to single
        assert detect_transaction_type(_basic(שותפים="בני זוג")) == "rental_start_couple"

    def test_roommates(self):
        assert detect_transaction_type(_basic(שותפים="שותפים")) == "rental_start_roommates"

    def test_single_when_truly_alone(self):
        assert detect_transaction_type(_basic()) == "rental_start_single"

    def test_company_wins(self):
        t = detect_transaction_type(_basic(סוג_לקוח="חברה בע\"מ", שותפים="זוג נשוי"))
        assert t == "rental_start_company"

    def test_partner_data_corroboration(self):
        # No marital string anywhere, but partner details were filled in —
        # must NOT be classified single.
        t = detect_transaction_type(
            _basic(),
            partner_section={"שם_פרטי": "דנה", "תעודת_זהות": "012345678"},
        )
        assert t == "rental_start_couple"

    def test_unmapped_scan_recovers_couple(self):
        # Marital answer arrived under an unmapped QID (form revision)
        t = detect_transaction_type(
            _basic(),
            unmapped={"q999_input999": "זוג נשוי"},
        )
        assert t == "rental_start_couple"

    def test_unmapped_scan_recovers_roommates(self):
        t = detect_transaction_type(_basic(), unmapped={"q77": "שותפים"})
        assert t == "rental_start_roommates"


class TestTermination:
    def test_single(self):
        assert detect_transaction_type(_basic(move="מסיים שכירות")) == "rental_termination_single"

    def test_couple_with_partner_data(self):
        t = detect_transaction_type(
            _basic(move="מסיים שכירות"),
            partner_section={"טלפון": "0501112233"},
        )
        assert t == "rental_termination_couple"

    def test_company(self):
        t = detect_transaction_type(_basic(move="מסיים שכירות", סוג_לקוח="עסק"))
        assert t == "rental_termination_company"


class TestLandlordFlows:
    def test_landlord_rental(self):
        t = detect_transaction_type(_basic(move="בעל בית", סוג_משכיר="משכיר"))
        assert t == "landlord_rental_single"

    def test_landlord_partner_section_is_the_tenant_not_a_couple(self):
        # In the בעל בית flow the partner section holds the TENANT's details;
        # its presence must NOT flip the classification to couple.
        t = detect_transaction_type(
            _basic(move="בעל בית", סוג_משכיר="משכיר"),
            partner_section={"שם_פרטי": "ליאור", "טלפון": "0524043365"},
        )
        assert t == "landlord_rental_single"

    def test_buyer(self):
        assert detect_transaction_type(_basic(move="בעל בית", סוג_משכיר="קונה")) == "sale_purchase"

    def test_seller(self):
        assert detect_transaction_type(_basic(move="בעל בית", סוג_משכיר="מוכר")) == "sale_transfer"

    def test_owner_return(self):
        assert detect_transaction_type(_basic(move="בעל בית", סוג_משכיר="חוזר לנכס")) == "owner_return"


class TestLegacyFallback:
    def test_account_closure_from_package(self):
        assert detect_transaction_type({}, package="חבילת גמר חשבון") == "account_closure"

    def test_sale_from_package(self):
        assert detect_transaction_type({}, package="קניה ומכירה") == "sale_transfer"

    def test_owner_transfer_from_transfer_to(self):
        assert detect_transaction_type({}, transfer_to="בעל הנכס") == "owner_transfer"

    def test_default(self):
        assert detect_transaction_type({}) == "rental_transfer"


class TestRoleRouting:
    def test_rental_start_default(self):
        assert role_routing("מתחיל שכירות") == ("customer", "partner", "outgoing", "landlord")

    def test_termination_customer_is_outgoing(self):
        assert role_routing("מסיים שכירות") == (None, "partner", "customer", "landlord")

    def test_landlord_lessor(self):
        assert role_routing("בעל בית", "משכיר") == ("partner", None, "outgoing", "customer")

    def test_seller(self):
        assert role_routing("בעל בית", "מוכר") == ("outgoing", "partner", "customer", None)

    def test_owner_return_landlord_is_customer(self):
        assert role_routing("בעל בית", "חוזר לנכס") == ("customer", "partner", "outgoing", "customer")

    def test_unknown_gets_default(self):
        assert role_routing("", "") == ("customer", "partner", "outgoing", "landlord")
        assert role_routing("בעל בית", "אחר") == ("customer", "partner", "outgoing", "landlord")


class TestMapperIntegration:
    def test_married_couple_end_to_end(self):
        """A realistic married-couple submission classifies as couple and the
        partner's contact details reach the business model."""
        parsed = {
            "basic": {
                "סוג_מעבר": "מתחיל שכירות",
                "עיר": "תל אביב",
                "שותפים": "נשואים",          # variant spelling
            },
            "customer": {"שם_פרטי": "אבי", "שם_משפחה": "כהן",
                         "תעודת_זהות": "012345678", "טלפון": "0501234567",
                         "אימייל": "avi@example.com"},
            "partner":  {"שם_פרטי": "דנה", "שם_משפחה": "כהן",
                         "תעודת_זהות": "087654321", "טלפון": "0527654321",
                         "אימייל": "dana@example.com"},
            "outgoing": {}, "landlord": {}, "property": {}, "arnona": {},
            "documents": {}, "payment": {}, "fhs": {}, "_unmapped": {},
        }
        bs = build_from_parsed(parsed)
        assert bs.submission.transaction_type == "rental_start_couple"
        assert bs.partner is not None
        assert bs.partner.phone == "0527654321"
        assert bs.partner.email == "dana@example.com"

    def test_couple_without_marital_string(self):
        """Partner data present, marital field lost → still not single."""
        parsed = {
            "basic": {"סוג_מעבר": "מתחיל שכירות"},
            "customer": {"שם_פרטי": "אבי"},
            "partner":  {"שם_פרטי": "דנה", "תעודת_זהות": "087654321"},
            "outgoing": {}, "landlord": {}, "property": {}, "arnona": {},
            "documents": {}, "payment": {}, "fhs": {}, "_unmapped": {},
        }
        bs = build_from_parsed(parsed)
        assert bs.submission.transaction_type == "rental_start_couple"
