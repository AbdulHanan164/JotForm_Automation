"""
Business-centric cross-document validation rules for the arnona transfer service.

Each rule has the same signature as ValidationRule.check — (parsed, doc_extractions)
— so ValidationEngine can run them without changes.

Inside each rule, BusinessSubmission is the canonical source:
  - reads parsed["_business"] → BusinessSubmission
  - falls back to raw section-keyed access if _business is absent
    (covers YAML-driven services and any edge case where the mapper failed)

KEY DIFFERENCE vs validators.py:
  Before:  _full_name(parsed, "customer")
             → reads parsed["customer"]["שם_פרטי"] + ["שם_משפחה"]
             → misses FHS-normalized name when form path is non-standard

  After:   bs.incoming_tenant.full_name
             → uses FHS-resolved name from BusinessSubmission
             → same name the operator sees in the summary
             → prevents false positives on sale/corporate transfers
"""
from __future__ import annotations

from typing import Any

from app.mappers.models import BusinessSubmission
from app.pipeline.validator import ValidationIssue, ValidationRule


# ── Helpers ───────────────────────────────────────────────────────────────────

def _bs(parsed: dict[str, Any]) -> BusinessSubmission | None:
    """Extract and reconstruct BusinessSubmission from parsed["_business"]."""
    bd = parsed.get("_business")
    if not bd:
        return None
    try:
        return BusinessSubmission.from_dict(bd)
    except Exception:
        return None


def _norm(name: str) -> str:
    """Normalize a Hebrew name for comparison: strip, collapse whitespace, lowercase."""
    return " ".join(name.strip().split()).lower()


def _lease(doc_extractions: dict[str, Any]) -> dict[str, Any]:
    return doc_extractions.get("חוזה_שכירות", {})


# ── Raw fallbacks (used only when _business is absent) ────────────────────────

def _raw_full_name(parsed: dict, section: str) -> str:
    first = str(parsed.get(section, {}).get("שם_פרטי", "")).strip()
    last  = str(parsed.get(section, {}).get("שם_משפחה", "")).strip()
    full  = str(parsed.get(section, {}).get("שם_מלא",  "")).strip()
    return full or f"{first} {last}".strip()


def _raw_get(parsed: dict, section: str, label: str) -> str:
    return str(parsed.get(section, {}).get(label, "")).strip()


# ── Rule implementations ──────────────────────────────────────────────────────

def _check_duplicate_names(
    parsed: dict[str, Any],
    docs:   dict[str, Any],
) -> ValidationIssue | None:
    """Main tenant and second tenant have the same name (likely auto-fill error)."""
    bs = _bs(parsed)
    if bs:
        name1 = bs.incoming_tenant.full_name
        name2 = bs.partner.full_name if bs.partner else ""
    else:
        name1 = _raw_full_name(parsed, "customer")
        name2 = _raw_full_name(parsed, "partner")

    if name1 and name2 and _norm(name1) == _norm(name2):
        return ValidationIssue(
            id              = "duplicate_tenant_names",
            severity        = "warning",
            label           = "שם שוכר ראשי זהה לשוכר שני",
            description     = (
                f"שם המשתמש הראשי ({name1}) זהה לשם השוכר השני. "
                "ייתכן שמדובר במילוי אוטומטי שגוי."
            ),
            rule_triggered  = "duplicate_tenant_names",
            affected_fields = ["דייר_נכנס.שם", "שוכר_שני.שם"],
            conflicting_values = {"דייר_נכנס": name1, "שוכר_שני": name2},
            suggestion      = "בדוק את שמו האמיתי של השוכר השני מתוך חוזה השכירות.",
        )
    return None


def _check_landlord_is_outgoing(
    parsed: dict[str, Any],
    docs:   dict[str, Any],
) -> ValidationIssue | None:
    """Landlord and outgoing tenant are the same person (valid, but notable)."""
    bs = _bs(parsed)
    if bs:
        ll_name  = bs.landlord.full_name if bs.landlord else ""
        out_name = bs.outgoing_tenant.full_name if bs.outgoing_tenant else ""
    else:
        ll_name  = _raw_full_name(parsed, "landlord")
        out_name = _raw_full_name(parsed, "outgoing")

    if ll_name and out_name and _norm(ll_name) == _norm(out_name):
        return ValidationIssue(
            id              = "landlord_is_outgoing_tenant",
            severity        = "info",
            label           = "בעל הבית זהה לדייר היוצא",
            description     = (
                f"בעל הבית ({ll_name}) הוא אותו אדם כמו הדייר היוצא. "
                "ייתכן שמדובר בבעל הבית שגר בדירה ומוכר/מוסר אותה."
            ),
            rule_triggered  = "landlord_is_outgoing_tenant",
            affected_fields = ["בעל_הבית.שם", "דייר_יוצא.שם"],
            conflicting_values = {"בעל_הבית": ll_name, "דייר_יוצא": out_name},
            suggestion      = "ודא שההבנה לגבי תפקיד כל צד נכונה.",
        )
    return None


def _check_outgoing_email_text_none(
    parsed: dict[str, Any],
    docs:   dict[str, Any],
) -> ValidationIssue | None:
    """Outgoing tenant typed 'אין' in the email field instead of leaving it blank."""
    bs = _bs(parsed)
    if bs:
        email = bs.outgoing_tenant.email if bs.outgoing_tenant else ""
    else:
        email = _raw_get(parsed, "outgoing", "אימייל")

    if email.strip() in ("אין", "none", "no", "לא", "—"):
        return ValidationIssue(
            id              = "outgoing_email_is_text_none",
            severity        = "info",
            label           = "אימייל דייר יוצא: הוזן 'אין' במקום שדה ריק",
            description     = (
                "שדה המייל של הדייר היוצא מכיל את הטקסט 'אין' "
                "במקום להישאר ריק. השדה לא יכלול כתובת מייל תקינה."
            ),
            rule_triggered  = "outgoing_email_is_text_none",
            affected_fields = ["דייר_יוצא.אימייל"],
            conflicting_values = {"אימייל_שהוזן": email},
            suggestion      = "אין צורך בפעולה — ברור שאין אימייל לדייר היוצא.",
        )
    return None


def _check_lease_tenant_count(
    parsed: dict[str, Any],
    docs:   dict[str, Any],
) -> ValidationIssue | None:
    """Number of tenants in the lease document differs from the form."""
    lease = _lease(docs)
    if not lease or lease.get("state") in ("not_attempted", "mock"):
        return None

    lease_tenants = lease.get("tenant_names", [])
    n_lease = len(lease_tenants)
    if n_lease == 0:
        return None

    bs = _bs(parsed)
    if bs:
        form_tenants = [
            n for n in [
                bs.incoming_tenant.full_name,
                bs.partner.full_name if bs.partner else "",
            ] if n
        ]
    else:
        form_tenants = [
            n for n in [
                _raw_full_name(parsed, "customer"),
                _raw_full_name(parsed, "partner"),
            ] if n
        ]
    n_form = len(form_tenants)

    if n_lease != n_form:
        return ValidationIssue(
            id              = "lease_tenant_count_mismatch",
            severity        = "warning",
            label           = "מספר שוכרים בחוזה שונה מהטופס",
            description     = (
                f"בחוזה מופיעים {n_lease} שוכרים "
                f"אך בטופס צוינו {n_form} שוכרים."
            ),
            rule_triggered  = "lease_tenant_count_mismatch",
            affected_fields = ["דייר_נכנס.שם", "שוכר_שני.שם"],
            conflicting_values = {
                "שוכרים_בחוזה": ", ".join(lease_tenants),
                "שוכרים_בטופס": ", ".join(form_tenants),
            },
            suggestion = "ודא שכל השוכרים המופיעים בחוזה מולאו בטופס.",
        )
    return None


def _check_lease_date_mismatch(
    parsed: dict[str, Any],
    docs:   dict[str, Any],
) -> ValidationIssue | None:
    """Lease start date differs from the move-in date on the form."""
    lease = _lease(docs)
    if not lease or lease.get("state") in ("not_attempted", "mock"):
        return None

    lease_start = str(lease.get("start_date", "")).strip()
    if not lease_start:
        return None

    bs = _bs(parsed)
    form_start = (
        bs.dates.move_in if bs
        else str(parsed.get("basic", {}).get("תאריך_כניסה", "")).strip()
    )
    if not form_start:
        return None

    def _nd(d: str) -> str:
        return d.replace("-", "/").strip()

    if _nd(lease_start) != _nd(form_start):
        return ValidationIssue(
            id              = "lease_date_mismatch",
            severity        = "warning",
            label           = "תאריך כניסה בחוזה שונה מהטופס",
            description     = (
                f"תאריך הכניסה בחוזה ({lease_start}) "
                f"אינו תואם לתאריך שצוין בטופס ({form_start})."
            ),
            rule_triggered  = "lease_date_mismatch",
            affected_fields = ["תאריכים.כניסה"],
            conflicting_values = {
                "תאריך_בחוזה": lease_start,
                "תאריך_בטופס": form_start,
            },
            suggestion = "ודא עם הלקוח מהו התאריך הנכון.",
        )
    return None


def _check_name_in_lease(
    parsed: dict[str, Any],
    docs:   dict[str, Any],
) -> ValidationIssue | None:
    """Main tenant name from the form is not found in the lease document."""
    lease = _lease(docs)
    if not lease or lease.get("state") in ("not_attempted", "mock"):
        return None

    lease_tenants = [_norm(n) for n in lease.get("tenant_names", [])]
    if not lease_tenants:
        return None

    bs = _bs(parsed)
    main_name = (
        bs.incoming_tenant.full_name if bs
        else _raw_full_name(parsed, "customer")
    )
    if not main_name:
        return None

    if _norm(main_name) not in lease_tenants:
        return ValidationIssue(
            id              = "form_name_not_in_lease",
            severity        = "error",
            label           = "שם השוכר הראשי לא נמצא בחוזה",
            description     = (
                f"השם '{main_name}' (מהטופס) לא מופיע ברשימת "
                f"השוכרים בחוזה ({', '.join(lease.get('tenant_names', []))})."
            ),
            rule_triggered  = "form_name_not_in_lease",
            affected_fields = ["דייר_נכנס.שם"],
            conflicting_values = {
                "שם_בטופס":   main_name,
                "שמות_בחוזה": ", ".join(lease.get("tenant_names", [])),
            },
            suggestion = "בדוק את שם השוכר בטופס ובחוזה — ייתכן שגוי כתיב או שם אחר.",
        )
    return None


def _check_lease_signatures(
    parsed: dict[str, Any],
    docs:   dict[str, Any],
) -> ValidationIssue | None:
    """Lease is missing required signatures."""
    lease = _lease(docs)
    if not lease or lease.get("state") in ("not_attempted", "mock"):
        return None

    if not lease.get("is_landlord_signed", True):
        return ValidationIssue(
            id              = "missing_lease_signatures",
            severity        = "error",
            label           = "חוזה: חתימת בעל הבית חסרה",
            description     = "לא נמצאה חתימת בעל הבית בחוזה השכירות.",
            rule_triggered  = "missing_lease_signatures",
            affected_fields = ["מסמכים.חוזה_שכירות"],
            suggestion      = "דרוש חוזה חתום על ידי שני הצדדים.",
        )

    found  = lease.get("tenant_signatures_found", 0)
    needed = lease.get("tenant_signatures_needed", 0)
    if needed > 0 and found < needed:
        return ValidationIssue(
            id              = "missing_lease_signatures",
            severity        = "warning",
            label           = f"חוזה: חסרות {needed - found} חתימות שוכר",
            description     = (
                f"החוזה מציין {needed} שוכרים אך נמצאו רק {found} חתימות."
            ),
            rule_triggered  = "missing_lease_signatures",
            affected_fields = ["מסמכים.חוזה_שכירות"],
            conflicting_values = {
                "חתימות_נמצאו":   str(found),
                "חתימות_נדרשות":  str(needed),
            },
            suggestion = "ודא שכל השוכרים חתמו על החוזה.",
        )
    return None


def _check_partner_phone_no_id(
    parsed: dict[str, Any],
    docs:   dict[str, Any],
) -> ValidationIssue | None:
    """Second tenant has a phone number but no ID number."""
    bs = _bs(parsed)
    if bs:
        partner = bs.partner
        phone  = partner.phone     if partner else ""
        id_num = partner.id_number if partner else ""
        name   = partner.full_name if partner else ""
    else:
        phone  = _raw_get(parsed, "partner", "טלפון")
        id_num = _raw_get(parsed, "partner", "תעודת_זהות")
        name   = _raw_full_name(parsed, "partner")

    if phone and not id_num:
        return ValidationIssue(
            id              = "partner_phone_no_id",
            severity        = "warning",
            label           = "שוכר שני: יש טלפון אך חסרה ת.ז",
            description     = (
                f"שוכר שני ({name}) מולא עם מספר טלפון אך ללא תעודת זהות."
            ),
            rule_triggered  = "partner_phone_no_id",
            affected_fields = ["שוכר_שני.תעודת_זהות"],
            suggestion      = "בקש את ת.ז השוכר השני.",
        )
    return None


# ── Rule list ─────────────────────────────────────────────────────────────────

BUSINESS_VALIDATION_RULES: list[ValidationRule] = [
    ValidationRule(id="duplicate_tenant_names",      check=_check_duplicate_names),
    ValidationRule(id="landlord_is_outgoing_tenant", check=_check_landlord_is_outgoing),
    ValidationRule(id="outgoing_email_is_text_none", check=_check_outgoing_email_text_none),
    ValidationRule(id="lease_tenant_count_mismatch", check=_check_lease_tenant_count),
    ValidationRule(id="lease_date_mismatch",         check=_check_lease_date_mismatch),
    ValidationRule(id="form_name_not_in_lease",      check=_check_name_in_lease),
    ValidationRule(id="missing_lease_signatures",    check=_check_lease_signatures),
    ValidationRule(id="partner_phone_no_id",         check=_check_partner_phone_no_id),
]
