"""
Production-form replay acceptance test — v0.8.2.

Replays the REAL preserved submission MZK6852 (form 250201745267957,
received 2026-06-09) through the full pipeline and asserts every stage
produces meaningful output. This is the proof that the production form
is wired into the system.

Ground truth: data/processed/20260609_122910_*_summary.json — the output
of the v0.3 parser that processed this exact submission correctly.

If this test fails after a form change, run GET /discover/{submission_id}
and update config/field_maps/arnona.yaml.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

RAW_FILE = Path("data/submissions/20260609_122910_6568173356277189497_raw.json")

PRODUCTION_FORM_ID = "250201745267957"
SUBMISSION_ID      = "6568173356277189497"


def _load_real_payload() -> dict:
    """Reconstruct the webhook fields exactly as JotForm POSTed them."""
    raw = json.loads(RAW_FILE.read_text(encoding="utf-8"))
    envelope    = raw["parsed"]["_raw"]["envelope"]
    raw_request = raw["parsed"]["_raw"]["raw_request"]
    fields = dict(envelope)
    fields["rawRequest"] = json.dumps(raw_request, ensure_ascii=False)
    return fields


needs_real_data = pytest.mark.skipif(
    not RAW_FILE.exists(),
    reason="real production submission not present (data/ is not committed)",
)


@needs_real_data
class TestProductionReplay:

    @pytest.fixture(scope="class")
    def result(self):
        from app.pipeline.orchestrator import run_pipeline
        fields = _load_real_payload()
        return run_pipeline(fields, "multipart/form-data", {})

    # ── 1. Service resolves ───────────────────────────────────────────────────

    def test_service_resolves(self, result):
        assert result.form_id == PRODUCTION_FORM_ID
        assert result.service_name == "arnona_transfer", (
            f"production form not routed — got {result.service_name!r}"
        )

    # ── 2. Parsed sections populated ──────────────────────────────────────────

    def test_parsed_customer(self, result):
        customer = result.parsed["customer"]
        assert customer["שם_פרטי"] == "אבנר"
        assert customer["שם_משפחה"] == "שבו"
        assert customer["תעודת_זהות"] == "028721819"
        assert customer["אימייל"] == "avner@microdiuk.co.il"

    def test_parsed_basic(self, result):
        basic = result.parsed["basic"]
        assert basic["עיר"] == "חולון"
        assert basic["תאריך_כניסה"] == "11-06-2026"
        assert basic["תאריך_סיום_חוזה"] == "10-06-2027"
        assert basic["תאריך_יציאה"] == ""          # empty date widget → ""
        assert set(basic["שירותים_נבחרים"]) == {"מים", "חשמל", "ארנונה"}
        assert basic["מספר_מונה_חשמל"] == "19010202"
        assert basic["קריאת_מונה_חשמל"] == "094498"

    def test_parsed_other_parties(self, result):
        outgoing = result.parsed["outgoing"]
        assert outgoing["שם_פרטי"] == "רן"
        assert outgoing["תעודת_זהות"] == "308346311"
        assert outgoing["אימייל"] == ""             # genuinely absent

        landlord = result.parsed["landlord"]
        assert landlord["שם_פרטי"] == "ראובן"
        assert landlord["טלפון"] == "0525011146"

    def test_parsed_documents_presence(self, result):
        docs = result.parsed["documents"]
        # v0.3 ground truth: pending-submissions paths = upload never finalized
        assert docs["תעודת_זהות"]["present"] is False
        assert docs["חתימה"]["present"] is False
        assert docs["תנאים"] is True
        assert docs["הסכם_שירות"] is True

    # ── 3. BusinessSubmission populated ───────────────────────────────────────

    def test_business_submission(self, result):
        bd = result.business_data
        assert bd, "BusinessSubmission was not built"
        assert bd["incoming_tenant"]["full_name"] == "אבנר שבו"
        assert bd["submission"]["amount_paid"] == 199.0
        assert set(bd["submission"]["services_selected"]) == {"מים", "חשמל", "ארנונה"}
        assert "צבי תדמור" in bd["property"]["full_address"]
        assert bd["outgoing_tenant"]["full_name"] == "רן בנישתי"
        assert bd["landlord"]["full_name"] == "ראובן שמש"
        assert bd["dates"]["move_in"] == "11-06-2026"

    # ── 4. Missing detection executes ─────────────────────────────────────────

    def test_missing_detection(self, result):
        missing = result.missing
        assert missing["is_complete"] is False
        all_ids = {m["id"] for m in missing["missing_info"] + missing["missing_docs"]}
        # v0.3 ground truth for MZK6852: id photo and signature were missing
        assert "id_photo" in all_ids
        assert "signature" in all_ids

    # ── 5. Validation executes ────────────────────────────────────────────────

    def test_validation_executes(self, result):
        assert isinstance(result.validation_issues, list)

    # ── 6. Email draft generated ──────────────────────────────────────────────

    def test_email_draft(self, result):
        assert result.email is not None, "missing items exist — chase draft required"
        assert result.email.get("subject")
        assert "אבנר" in result.email.get("body", "")

    # ── 7. Operator summary (Layer A) generated ───────────────────────────────

    def test_operator_summary(self, result):
        from app.review.queue import build_from_pipeline
        from app.mappers.models import BusinessSubmission
        from app.services.arnona.summary import build_layer_a

        item = build_from_pipeline(result)
        assert item.mzk_ref == "MZK6852"

        bs = BusinessSubmission.from_dict(item.business_data)
        layer_a = build_layer_a(
            bs,
            missing_info      = item.missing_info,
            missing_docs      = item.missing_docs,
            validation_issues = item.validation_issues,
            mzk_ref           = item.mzk_ref,
        )
        assert layer_a["header"] == "הנה סיכום ההגשה MZK6852"
        assert layer_a["status"] in ("ok", "warning", "error")
        assert layer_a["sections"], "Layer A produced no sections"

        section_ids = {s["id"] for s in layer_a["sections"]}
        assert "transaction" in section_ids
        assert "incoming_tenant" in section_ids
