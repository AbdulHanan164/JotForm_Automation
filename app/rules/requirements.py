"""
Canonical requirement engine — THE single source of truth for
Missing Information and Missing Documents (v0.7).

Replaces (and reconciles) the three pre-v0.7 sources:
  * app/mappers/missing_detector.py   (BusinessSubmission rules)
  * app/services/arnona/rules.py      (raw section-keyed rules)   — deleted
  * app/services/arnona/field_map.py  REQUIRED_DOCS (dead config) — deleted

Design
------
Requirements are DATA (the tables at the bottom), evaluated by a small,
generic engine. What is required depends only on the deterministic business
tuple — no AI anywhere:

    (transaction traits, client type, selected services, field visibility)

  * Transaction traits come from app/core/transactions.py — e.g. a rental
    termination has no incoming tenant, so incoming-tenant fields are never
    demanded; a sale has no landlord, so the landlord phone isn't demanded.
  * Service relevance uses SUBSTRING matching ("העברת ארנונה" counts as
    ארנונה), and an EMPTY services list counts as arnona-relevant — this form
    exists to transfer arnona, so an absent multi-select must not silently
    drop the arnona requirements (pre-v0.7 exact-match bug).
  * Visibility keys are the REAL form-field labels used by both conditional
    engines (evaluator.py and the legacy 8-rule engine). Pre-v0.7 the info
    rules checked visibility under display labels like "טלפון (בעל הבית)"
    which no engine ever emits, so hiding never worked.
  * Document presence is resolved through app/documents/storage.manifest_status
    — alias-aware, so a file classified "tabu_document" satisfies the "tabu"
    requirement, and a file awaiting operator review ("needs_review") is NOT
    re-requested from the customer.

Output shape is byte-compatible with the pre-v0.7 detector:
  {"is_complete": bool,
   "missing_info": [{"id","label","reason","rule_triggered","was_field_visible"}],
   "missing_docs": [{"id","label","reason","rule_triggered"}]}
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.core.doc_types import hebrew_label
from app.core.transactions import TransactionTraits, traits_for
from app.mappers.models import BusinessSubmission, Person


# ── Value-presence helpers (moved verbatim from missing_detector) ─────────────

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
    """True if a document field has a file attached (form upload).

    Handles the three shapes a doc field can take:
      dict from raw JotForm: {"present": True, "url": "..."} /
      string after to_dict(): "✅" / None.
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


def _person_has_data(p: Person | None) -> bool:
    return p is not None and (
        _present(p.full_name) or _present(p.phone) or _present(p.id_number)
    )


# ── Evaluation context ────────────────────────────────────────────────────────

@dataclass
class RequirementContext:
    bs:         BusinessSubmission
    traits:     TransactionTraits
    visibility: dict[str, bool]

    @property
    def is_company(self) -> bool:
        return bool(self.bs.incoming_tenant.is_company)

    def service_selected(self, keyword: str) -> bool:
        """Substring service match; an EMPTY selection counts as selected
        (conservative default for the arnona form — see module docstring)."""
        services = self.bs.submission.services_selected
        if not services:
            return True
        return any(keyword in str(s) for s in services)

    def visible(self, form_label: str | None) -> bool:
        """True unless a conditional engine explicitly hid this form field."""
        if not form_label:
            return True
        return self.visibility.get(form_label, True) is not False


# ── Rule specification ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class InfoRule:
    id:             str
    label:          str                                     # output display label (stable)
    reason:         str
    required:       Callable[[RequirementContext], bool]
    present:        Callable[[BusinessSubmission], bool]
    visibility_key: str | None = None                       # REAL form-field label


@dataclass(frozen=True)
class DocRule:
    id:       str                                           # canonical doc type
    reason:   str
    required: Callable[[RequirementContext], bool]
    form_doc: Callable[[BusinessSubmission], Any]           # form-upload field accessor
    label:    str | None = None                             # defaults to Hebrew doc label


# ── Info rules ────────────────────────────────────────────────────────────────

INFO_RULES: tuple[InfoRule, ...] = (
    InfoRule(
        id="city", label="עיר",
        reason="נדרש לצורך קביעת שדות הארנונה הרלוונטיים",
        required=lambda c: True,
        present=lambda bs: _present(bs.property.city),
        visibility_key="עיר",
    ),
    InfoRule(
        id="move_in_date", label="תאריך_כניסה",
        reason="נדרש לצורך עיבוד ההעברה",
        required=lambda c: c.traits.has_incoming,
        present=lambda bs: _present(bs.dates.move_in),
        visibility_key="תאריך_כניסה",
    ),
    InfoRule(
        id="move_out_date", label="תאריך_יציאה",
        reason="נדרש לסגירת החשבון במועד הנכון",
        required=lambda c: c.traits.has_outgoing and not c.traits.has_incoming,
        present=lambda bs: _present(bs.dates.move_out) or _present(bs.dates.lease_end),
        visibility_key="תאריך_יציאה",
    ),
    # ── Incoming tenant — only for transactions that HAVE one ────────────────
    InfoRule(
        id="customer_name", label="שם הדייר הנכנס",
        reason="נדרש לפתיחת תיק",
        required=lambda c: c.traits.has_incoming,
        present=lambda bs: _present(bs.incoming_tenant.full_name),
    ),
    InfoRule(
        id="customer_phone", label="טלפון",
        reason="נדרש ליצירת קשר",
        required=lambda c: c.traits.has_incoming,
        present=lambda bs: _present(bs.incoming_tenant.phone),
        visibility_key="טלפון",
    ),
    InfoRule(
        id="customer_email", label="אימייל",
        reason="נדרש לשליחת אישורים",
        required=lambda c: c.traits.has_incoming,
        present=lambda bs: _present(bs.incoming_tenant.email),
        visibility_key="אימייל",
    ),
    InfoRule(
        id="customer_id", label="תעודת_זהות",
        reason="נדרש לרישום מול הרשויות",
        required=lambda c: c.traits.has_incoming and not c.is_company,
        present=lambda bs: _present(bs.incoming_tenant.id_number),
        visibility_key="תעודת_זהות",
    ),
    # ── Partner / second tenant ───────────────────────────────────────────────
    # Required when partner data was supplied OR the transaction type itself
    # says there is a second person (couple/roommates) — the second half is
    # what catches a married-couple submission whose partner fields were lost.
    InfoRule(
        id="partner_name", label="שם (שוכר שני)",
        reason="סוג העסקה כולל שוכר שני — נדרש שם מלא",
        required=lambda c: c.traits.partner_expected and not _person_has_data(c.bs.partner),
        present=lambda bs: bs.partner is not None and _present(bs.partner.full_name),
    ),
    InfoRule(
        id="partner_id", label="תעודת_זהות (שוכר שני)",
        reason="שוכר שני מופיע בטופס — נדרשת ת.ז",
        required=lambda c: _person_has_data(c.bs.partner) or c.traits.partner_expected,
        present=lambda bs: bs.partner is not None and _present(bs.partner.id_number),
    ),
    # ── Outgoing tenant ───────────────────────────────────────────────────────
    InfoRule(
        id="outgoing_id", label="תעודת_זהות (דייר יוצא)",
        reason="נדרש לביטול החשבון על שם הדייר היוצא",
        required=lambda c: c.traits.has_outgoing or _person_has_data(c.bs.outgoing_tenant),
        present=lambda bs: bs.outgoing_tenant is not None and _present(bs.outgoing_tenant.id_number),
    ),
    InfoRule(
        id="outgoing_phone", label="טלפון (דייר יוצא)",
        reason="נדרש ליצירת קשר עם הדייר היוצא",
        required=lambda c: c.traits.has_outgoing or _person_has_data(c.bs.outgoing_tenant),
        present=lambda bs: bs.outgoing_tenant is not None and _present(bs.outgoing_tenant.phone),
    ),
    # ── Landlord — only for transactions that HAVE a landlord ────────────────
    InfoRule(
        id="owner_phone", label="טלפון (בעל הבית)",
        reason="נדרש לאישור ההעברה מול בעל הבית",
        required=lambda c: c.traits.has_landlord,
        present=lambda bs: bs.landlord is not None and _present(bs.landlord.phone),
    ),
    # ── Arnona account numbers — only when ארנונה is a selected service ──────
    InfoRule(
        id="arnona_property_number", label="מספר_נכס",
        reason="נדרש לרישום חשבון הארנונה",
        required=lambda c: c.service_selected("ארנונה"),
        present=lambda bs: _present(bs.arnona_accounts.property_number),
        visibility_key="מספר_נכס",
    ),
    InfoRule(
        id="arnona_customer_number", label="מספר_לקוח",
        reason="מספר לקוח/משלם ארנונה — מופיע בחשבון הארנונה",
        required=lambda c: c.service_selected("ארנונה"),
        present=lambda bs: _present(bs.arnona_accounts.payer_number),
        visibility_key="מספר_לקוח",
    ),
    InfoRule(
        id="arnona_id_number", label="מספר_זיהוי_נכס",
        reason="מספר זיהוי הנכס — מופיע בחשבון הארנונה",
        required=lambda c: c.service_selected("ארנונה"),
        present=lambda bs: _present(bs.arnona_accounts.identification_number),
        visibility_key="מספר_זיהוי_נכס",
    ),
)


# ── Document rules ────────────────────────────────────────────────────────────

DOC_RULES: tuple[DocRule, ...] = (
    DocRule(
        id="id_photo",
        reason="נדרש לצורך אימות זהות",
        required=lambda c: not c.is_company,
        form_doc=lambda bs: bs.documents.id_photo,
    ),
    DocRule(
        id="lease_contract",
        reason="נדרש להוכחת זכאות לדירה",
        required=lambda c: c.traits.needs_contract and c.traits.contract_kind == "lease",
        form_doc=lambda bs: bs.documents.lease_contract,
    ),
    DocRule(
        id="sale_contract",
        reason="נדרש להוכחת הבעלות/הרכישה",
        required=lambda c: c.traits.needs_contract and c.traits.contract_kind == "sale",
        # a sale contract is uploaded through the same form field as a lease
        form_doc=lambda bs: bs.documents.lease_contract,
    ),
    DocRule(
        id="signature",
        reason="נדרש לאישור הבקשה",
        required=lambda c: True,
        form_doc=lambda bs: bs.documents.signature,
    ),
    DocRule(
        id="arnona_bill",
        reason="נדרש לאימות מספר הנכס ופרטי חשבון הארנונה",
        required=lambda c: c.service_selected("ארנונה"),
        form_doc=lambda bs: bs.documents.arnona_bill,
    ),
    DocRule(
        id="corp_cert",
        reason="נדרש לאימות חברה",
        required=lambda c: c.is_company,
        form_doc=lambda bs: bs.documents.corp_cert,
    ),
    DocRule(
        id="tabu",
        reason="נדרש לאימות בעלות",
        required=lambda c: c.is_company or c.traits.needs_tabu,
        form_doc=lambda bs: bs.documents.tabu,
    ),
)


# ── Engine ────────────────────────────────────────────────────────────────────

def detect_missing(
    bs: BusinessSubmission,
    visibility: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Evaluate all requirement rules against a BusinessSubmission.

    THE canonical entry point for missing detection — the webhook pipeline,
    the post-merge review update, and the backfill scripts all call this.
    """
    ctx = RequirementContext(
        bs=bs,
        traits=traits_for(bs.submission.transaction_type),
        visibility=visibility or {},
    )

    missing_info: list[dict] = []
    for rule in INFO_RULES:
        if not rule.required(ctx):
            continue
        if not ctx.visible(rule.visibility_key):
            continue
        if rule.present(bs):
            continue
        missing_info.append({
            "id":                rule.id,
            "label":             rule.label,
            "reason":            rule.reason,
            "rule_triggered":    rule.id,
            "was_field_visible": ctx.visibility.get(rule.visibility_key, True)
                                 if rule.visibility_key else True,
        })

    missing_docs: list[dict] = []
    for rule in DOC_RULES:
        if not rule.required(ctx):
            continue
        if _doc_present(rule.form_doc(bs)):
            continue
        if _manifest_resolves(bs.submission_id, rule.id):
            continue
        missing_docs.append({
            "id":             rule.id,
            "label":          rule.label or hebrew_label(rule.id),
            "reason":         rule.reason,
            "rule_triggered": rule.id,
        })

    return {
        "is_complete":  not missing_info and not missing_docs,
        "missing_info": missing_info,
        "missing_docs": missing_docs,
    }


def _manifest_resolves(submission_id: str, requirement_type: str) -> bool:
    """Alias-aware manifest check; isolated for testability/import safety."""
    if not submission_id:
        return False
    try:
        from app.documents.storage import manifest_resolves
        return manifest_resolves(submission_id, requirement_type)
    except Exception:
        return False
