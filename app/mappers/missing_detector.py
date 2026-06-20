"""
Business-centric missing-field detector for the arnona transfer service.

Reads exclusively from BusinessSubmission — the FHS-normalized model.
This is the canonical replacement for the section-keyed rules in
app/services/arnona/rules.py.

KEY DIFFERENCE — before vs after:
  Before:  _has(parsed, "customer", "שם_פרטי")
             → misses FHS-normalized names in parsed["fhs"]
             → false "missing" alert once FHS IDs are configured

  After:   bool(bs.incoming_tenant.full_name)
             → uses FHS if populated, raw customer section as fallback
             → consistent with what build_summary() shows the operator

Called by ArnonaService.detect_missing() when parsed["_business"] is present.
Falls back to the original rules.py for YAML-driven services that don't build
a BusinessSubmission.
"""
from __future__ import annotations

from typing import Any

from app.mappers.models import BusinessSubmission, Documents


# ── Helpers ───────────────────────────────────────────────────────────────────

def _present(value: Any) -> bool:
    """True if value is a non-empty, non-placeholder string/value."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (list, tuple)):
        return len(value) > 0
    s = str(value).strip()
    return bool(s) and s not in ("—", "❌", "none", "null", "")


def _doc_present(doc: Any) -> bool:
    """
    True if a document field has a file attached.
    Handles three forms the field can take:
      - dict from raw JotForm:   {"present": True, "url": "..."}
      - string after to_dict():  "✅" or "❌"
      - None when absent
    """
    if doc is None:
        return False
    if isinstance(doc, str):
        return doc == "✅"
    if isinstance(doc, bool):
        return doc
    if isinstance(doc, dict):
        return bool(doc.get("present") or doc.get("url") or doc.get("local_path"))
    return False


def _visible(label: str, visibility: dict[str, bool]) -> bool:
    """True unless ConditionalLogicEngine explicitly hid this field."""
    return visibility.get(label, True) is not False


# ── Public API ────────────────────────────────────────────────────────────────

def detect_missing(
    bs: BusinessSubmission,
    visibility: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """
    Detect missing required fields from a BusinessSubmission.

    Args:
        bs:         Normalized business model (FHS-aware, built by business_mapper).
        visibility: Field visibility from ConditionalLogicEngine.evaluate().
                    Fields explicitly hidden (visibility[label] == False) are skipped.

    Returns:
        {
            "is_complete":  bool,
            "missing_info": [{"id", "label", "reason", "rule_triggered", "was_field_visible"}],
            "missing_docs": [{"id", "label", "reason", "rule_triggered"}],
        }
    """
    vis = visibility or {}
    missing_info = _detect_info(bs, vis)
    missing_docs = _detect_docs(bs)
    return {
        "is_complete":  not missing_info and not missing_docs,
        "missing_info": missing_info,
        "missing_docs": missing_docs,
    }


# ── Info rules ────────────────────────────────────────────────────────────────

def _detect_info(bs: BusinessSubmission, vis: dict[str, bool]) -> list[dict]:
    items: list[dict] = []

    def _flag(rule_id: str, label: str, reason: str) -> None:
        if _visible(label, vis):
            items.append({
                "id":                rule_id,
                "label":             label,
                "reason":            reason,
                "rule_triggered":    rule_id,
                "was_field_visible": vis.get(label, True),
            })

    # ── Property / transaction ────────────────────────────────────────────────

    if not _present(bs.property.city):
        _flag("city", "עיר", "נדרש לצורך קביעת שדות הארנונה הרלוונטיים")

    if not _present(bs.dates.move_in):
        _flag("move_in_date", "תאריך_כניסה", "נדרש לצורך עיבוד ההעברה")

    # ── Incoming tenant ───────────────────────────────────────────────────────
    # full_name is resolved via FHS → raw fallback in business_mapper,
    # so this check is accurate regardless of which path populated the data.

    if not _present(bs.incoming_tenant.full_name):
        _flag("customer_name", "שם הדייר הנכנס", "נדרש לפתיחת תיק")

    if not _present(bs.incoming_tenant.phone):
        _flag("customer_phone", "טלפון", "נדרש ליצירת קשר")

    if not _present(bs.incoming_tenant.email):
        _flag("customer_email", "אימייל", "נדרש לשליחת אישורים")

    if not bs.incoming_tenant.is_company and not _present(bs.incoming_tenant.id_number):
        _flag("customer_id", "תעודת_זהות", "נדרש לרישום מול הרשויות")

    # ── Partner / second tenant (conditional) ─────────────────────────────────

    if bs.partner and (_present(bs.partner.full_name) or _present(bs.partner.phone)):
        if not _present(bs.partner.id_number):
            _flag("partner_id", "תעודת_זהות (שוכר שני)", "שוכר שני מופיע בטופס — נדרשת ת.ז")

    # ── Outgoing tenant (conditional) ─────────────────────────────────────────

    if bs.outgoing_tenant and (
        _present(bs.outgoing_tenant.full_name)
        or _present(bs.outgoing_tenant.phone)
        or _present(bs.outgoing_tenant.id_number)
    ):
        if not _present(bs.outgoing_tenant.id_number):
            _flag("outgoing_id", "תעודת_זהות (דייר יוצא)", "נדרש לביטול החשבון על שם הדייר היוצא")
        if not _present(bs.outgoing_tenant.phone):
            _flag("outgoing_phone", "טלפון (דייר יוצא)", "נדרש ליצירת קשר עם הדייר היוצא")

    # ── Landlord ──────────────────────────────────────────────────────────────
    # Phone is always required — needed to confirm transfer with property owner.

    landlord_phone = bs.landlord.phone if bs.landlord else ""
    if not _present(landlord_phone):
        _flag("owner_phone", "טלפון (בעל הבית)", "נדרש לאישור ההעברה מול בעל הבית")

    # ── Arnona account numbers ────────────────────────────────────────────────
    # Only required when ארנונה is among the selected services.
    # Fields hidden by city-specific conditional logic (e.g. Ramat Gan rule 2,
    # Jerusalem rule, Cholon rule) are caught by the visibility check in _flag()
    # and silently skipped.

    if "ארנונה" in bs.submission.services_selected:
        if not _present(bs.arnona_accounts.property_number):
            _flag("arnona_property_number", "מספר_נכס",
                  "נדרש לרישום חשבון הארנונה")

        if not _present(bs.arnona_accounts.payer_number):
            _flag("arnona_customer_number", "מספר_לקוח",
                  "מספר לקוח/משלם ארנונה — מופיע בחשבון הארנונה")

        if not _present(bs.arnona_accounts.identification_number):
            _flag("arnona_id_number", "מספר_זיהוי_נכס",
                  "מספר זיהוי הנכס — מופיע בחשבון הארנונה")

    return items


def is_doc_resolved_in_manifest(submission_id: str, doc_type: str) -> bool:
    if not submission_id:
        return False
    try:
        import json
        from pathlib import Path
        from app.config import settings
        manifest_path = settings.documents_dir / submission_id / "_manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            status = manifest.get("documents", {}).get(doc_type, {}).get("status")
            return status == "present"
    except Exception:
        pass
    return False


# ── Document rules ────────────────────────────────────────────────────────────

def _detect_docs(bs: BusinessSubmission) -> list[dict]:
    items: list[dict] = []
    docs = bs.documents
    sub_id = bs.submission_id

    def _flag(rule_id: str, label: str, reason: str) -> None:
        items.append({
            "id":             rule_id,
            "label":          label,
            "reason":         reason,
            "rule_triggered": rule_id,
        })

    def _is_present(doc: Any, doc_type: str) -> bool:
        if _doc_present(doc):
            return True
        if sub_id and is_doc_resolved_in_manifest(sub_id, doc_type):
            return True
        return False

    if not bs.incoming_tenant.is_company and not _is_present(docs.id_photo, "id_photo"):
        _flag("id_photo", "תעודת_זהות", "נדרש לצורך אימות זהות")

    if not _is_present(docs.lease_contract, "lease_contract"):
        _flag("lease_contract", "חוזה_שכירות", "נדרש להוכחת זכאות לדירה")

    if not _is_present(docs.signature, "signature"):
        _flag("signature", "חתימה", "נדרש לאישור הבקשה")

    if not _is_present(docs.arnona_bill, "arnona_bill"):
        _flag("arnona_bill", "חשבון_ארנונה",
              "נדרש לאימות מספר הנכס ופרטי חשבון הארנונה")

    if bs.incoming_tenant.is_company:
        if not _is_present(docs.corp_cert, "corp_cert"):
            _flag("corp_cert", "תעודת_התאגדות", "נדרש לאימות חברה")
        if not _is_present(docs.tabu, "tabu"):
            _flag("tabu", "נסח_טאבו", "נדרש לאימות בעלות")

    return items
