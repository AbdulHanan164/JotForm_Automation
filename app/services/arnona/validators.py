"""
Business validation rules for the arnona transfer service.

These rules detect inconsistencies ACROSS form + documents.
They are separate from missing-field rules.

Derived from real client issues observed in the client chat:
  - Main user and partner had identical names
  - Lease had two tenants but form showed only one
  - Lease dates differed from form dates by 1 day
  - Outgoing tenant email was "אין" (literal text, not empty)
  - Landlord and outgoing tenant were the same person (valid but notable)
"""
from __future__ import annotations

from typing import Any

from app.pipeline.validator import ValidationIssue, ValidationRule


# ── Helper: get a field from parsed ──────────────────────────────────────────

def _get(parsed: dict, section: str, label: str) -> str:
    return str(parsed.get(section, {}).get(label, "")).strip()


def _full_name(parsed: dict, section: str) -> str:
    first = _get(parsed, section, "שם_פרטי")
    last  = _get(parsed, section, "שם_משפחה")
    full  = _get(parsed, section, "שם_מלא")
    return full or f"{first} {last}".strip()


def _lease_extraction(doc_extractions: dict) -> dict:
    """Get the lease extraction dict (might be empty if not extracted)."""
    return doc_extractions.get("חוזה_שכירות", {})


def _norm_name(name: str) -> str:
    """Normalise a Hebrew name for comparison: lowercase, strip extra spaces."""
    return " ".join(name.strip().split()).lower()


# ── Validation rules ──────────────────────────────────────────────────────────

ARNONA_VALIDATION_RULES: list[ValidationRule] = [

    # ── 1. Main user and partner have identical names ─────────────────────────
    # Observed in real submission — likely auto-fill error
    ValidationRule(
        id = "duplicate_tenant_names",
        check = lambda parsed, docs: (
            ValidationIssue(
                id             = "duplicate_tenant_names",
                severity       = "warning",
                label          = "שם שוכר ראשי זהה לשוכר שני",
                description    = (
                    f"שם המשתמש הראשי ({_full_name(parsed, 'customer')}) "
                    f"זהה לשם השוכר השני. "
                    "ייתכן שמדובר במילוי אוטומטי שגוי."
                ),
                rule_triggered = "duplicate_tenant_names",
                affected_fields= ["דייר_נכנס.שם", "שוכר_שני.שם"],
                conflicting_values={
                    "דייר_נכנס": _full_name(parsed, "customer"),
                    "שוכר_שני":  _full_name(parsed, "partner"),
                },
                suggestion = "בדוק את שמו האמיתי של השוכר השני מתוך חוזה השכירות.",
            )
            if (
                _full_name(parsed, "customer") and
                _full_name(parsed, "partner") and
                _norm_name(_full_name(parsed, "customer")) ==
                _norm_name(_full_name(parsed, "partner"))
            ) else None
        ),
    ),

    # ── 2. Landlord is the same person as outgoing tenant ────────────────────
    # Valid scenario (owner moving out), but always worth flagging
    ValidationRule(
        id = "landlord_is_outgoing_tenant",
        check = lambda parsed, docs: (
            ValidationIssue(
                id             = "landlord_is_outgoing_tenant",
                severity       = "info",
                label          = "בעל הבית זהה לדייר היוצא",
                description    = (
                    f"בעל הבית ({_full_name(parsed, 'landlord')}) "
                    "הוא אותו אדם כמו הדייר היוצא. "
                    "ייתכן שמדובר בבעל הבית שגר בדירה ומוכר/מוסר אותה."
                ),
                rule_triggered = "landlord_is_outgoing_tenant",
                affected_fields= ["בעל_הבית.שם", "דייר_יוצא.שם"],
                conflicting_values={
                    "בעל_הבית":  _full_name(parsed, "landlord"),
                    "דייר_יוצא": _full_name(parsed, "outgoing"),
                },
                suggestion = "ודא שההבנה לגבי תפקיד כל צד נכונה.",
            )
            if (
                _full_name(parsed, "landlord") and
                _full_name(parsed, "outgoing") and
                _norm_name(_full_name(parsed, "landlord")) ==
                _norm_name(_full_name(parsed, "outgoing"))
            ) else None
        ),
    ),

    # ── 3. Outgoing tenant email is "אין" (literal text, not empty) ──────────
    # Observed in MZK5203 — user typed "אין" instead of leaving blank
    ValidationRule(
        id = "outgoing_email_is_text_none",
        check = lambda parsed, docs: (
            ValidationIssue(
                id             = "outgoing_email_is_text_none",
                severity       = "info",
                label          = "אימייל דייר יוצא: הוזן 'אין' במקום שדה ריק",
                description    = (
                    "שדה המייל של הדייר היוצא מכיל את הטקסט 'אין' "
                    "במקום להישאר ריק. השדה לא יכלול כתובת מייל תקינה."
                ),
                rule_triggered = "outgoing_email_is_text_none",
                affected_fields= ["דייר_יוצא.אימייל"],
                conflicting_values={"אימייל_שהוזן": _get(parsed, "outgoing", "אימייל")},
                suggestion     = "אין צורך בפעולה — ברור שאין אימייל לדייר היוצא.",
            )
            if _get(parsed, "outgoing", "אימייל").strip() in ("אין", "none", "no", "לא", "—")
            else None
        ),
    ),

    # ── 4. Lease tenant count doesn't match form ──────────────────────────────
    ValidationRule(
        id = "lease_tenant_count_mismatch",
        check = lambda parsed, docs: _check_lease_tenant_count(parsed, docs),
    ),

    # ── 5. Lease start date differs from form move-in date ───────────────────
    ValidationRule(
        id = "lease_date_mismatch",
        check = lambda parsed, docs: _check_lease_date_mismatch(parsed, docs),
    ),

    # ── 6. Form tenant name not found in lease ────────────────────────────────
    ValidationRule(
        id = "form_name_not_in_lease",
        check = lambda parsed, docs: _check_name_in_lease(parsed, docs),
    ),

    # ── 7. Lease has missing signatures ──────────────────────────────────────
    ValidationRule(
        id = "missing_lease_signatures",
        check = lambda parsed, docs: _check_lease_signatures(parsed, docs),
    ),

    # ── 8. Partner has phone but no ID (seen in real submissions) ─────────────
    ValidationRule(
        id = "partner_phone_no_id",
        check = lambda parsed, docs: (
            ValidationIssue(
                id             = "partner_phone_no_id",
                severity       = "warning",
                label          = "שוכר שני: יש טלפון אך חסרה ת.ז",
                description    = (
                    f"שוכר שני ({_full_name(parsed, 'partner')}) "
                    "מולא עם מספר טלפון אך ללא תעודת זהות."
                ),
                rule_triggered = "partner_phone_no_id",
                affected_fields= ["שוכר_שני.תעודת_זהות"],
                suggestion     = "בקש את ת.ז השוכר השני.",
            )
            if (
                _get(parsed, "partner", "טלפון") and
                not _get(parsed, "partner", "תעודת_זהות")
            ) else None
        ),
    ),
]


# ── Multi-step check functions ────────────────────────────────────────────────

def _check_lease_tenant_count(
    parsed: dict, docs: dict
) -> ValidationIssue | None:
    lease = _lease_extraction(docs)
    if not lease or lease.get("state") in ("not_attempted", "mock"):
        return None  # can't validate without real extraction

    lease_tenants = lease.get("tenant_names", [])
    n_lease = len(lease_tenants)
    if n_lease == 0:
        return None  # nothing extracted

    # Count tenants in form
    form_tenants = []
    if _full_name(parsed, "customer"):
        form_tenants.append(_full_name(parsed, "customer"))
    if _full_name(parsed, "partner"):
        form_tenants.append(_full_name(parsed, "partner"))
    n_form = len(form_tenants)

    if n_lease != n_form:
        return ValidationIssue(
            id             = "lease_tenant_count_mismatch",
            severity       = "warning",
            label          = "מספר שוכרים בחוזה שונה מהטופס",
            description    = (
                f"בחוזה מופיעים {n_lease} שוכרים "
                f"אך בטופס צוינו {n_form} שוכרים."
            ),
            rule_triggered = "lease_tenant_count_mismatch",
            affected_fields= ["דייר_נכנס.שם", "שוכר_שני.שם"],
            conflicting_values={
                "שוכרים_בחוזה": ", ".join(lease_tenants),
                "שוכרים_בטופס": ", ".join(form_tenants),
            },
            suggestion = "ודא שכל השוכרים המופיעים בחוזה מולאו בטופס.",
        )
    return None


def _check_lease_date_mismatch(
    parsed: dict, docs: dict
) -> ValidationIssue | None:
    lease = _lease_extraction(docs)
    if not lease or lease.get("state") in ("not_attempted", "mock"):
        return None

    lease_start = str(lease.get("start_date", "")).strip()
    form_start  = _get(parsed, "basic", "תאריך_כניסה")

    if not lease_start or not form_start:
        return None

    # Normalise: replace - with /
    def _norm(d: str) -> str:
        return d.replace("-", "/").strip()

    if _norm(lease_start) != _norm(form_start):
        return ValidationIssue(
            id             = "lease_date_mismatch",
            severity       = "warning",
            label          = "תאריך כניסה בחוזה שונה מהטופס",
            description    = (
                f"תאריך הכניסה בחוזה ({lease_start}) "
                f"אינו תואם לתאריך שצוין בטופס ({form_start})."
            ),
            rule_triggered = "lease_date_mismatch",
            affected_fields= ["תאריכים.כניסה"],
            conflicting_values={
                "תאריך_בחוזה": lease_start,
                "תאריך_בטופס": form_start,
            },
            suggestion = "ודא עם הלקוח מהו התאריך הנכון.",
        )
    return None


def _check_name_in_lease(
    parsed: dict, docs: dict
) -> ValidationIssue | None:
    lease = _lease_extraction(docs)
    if not lease or lease.get("state") in ("not_attempted", "mock"):
        return None

    lease_tenants = [_norm_name(n) for n in lease.get("tenant_names", [])]
    if not lease_tenants:
        return None

    main_name = _full_name(parsed, "customer")
    if not main_name:
        return None

    if _norm_name(main_name) not in lease_tenants:
        return ValidationIssue(
            id             = "form_name_not_in_lease",
            severity       = "error",
            label          = "שם השוכר הראשי לא נמצא בחוזה",
            description    = (
                f"השם '{main_name}' (מהטופס) לא מופיע ברשימת "
                f"השוכרים בחוזה ({', '.join(lease.get('tenant_names', []))})."
            ),
            rule_triggered = "form_name_not_in_lease",
            affected_fields= ["דייר_נכנס.שם"],
            conflicting_values={
                "שם_בטופס":  main_name,
                "שמות_בחוזה": ", ".join(lease.get("tenant_names", [])),
            },
            suggestion = "בדוק את שם השוכר בטופס ובחוזה — ייתכן שגוי כתיב או שם אחר.",
        )
    return None


def _check_lease_signatures(
    parsed: dict, docs: dict
) -> ValidationIssue | None:
    lease = _lease_extraction(docs)
    if not lease or lease.get("state") in ("not_attempted", "mock"):
        return None

    if not lease.get("is_landlord_signed", True):
        return ValidationIssue(
            id             = "missing_lease_signatures",
            severity       = "error",
            label          = "חוזה: חתימת בעל הבית חסרה",
            description    = "לא נמצאה חתימת בעל הבית בחוזה השכירות.",
            rule_triggered = "missing_lease_signatures",
            affected_fields= ["מסמכים.חוזה_שכירות"],
            suggestion     = "דרוש חוזה חתום על ידי שני הצדדים.",
        )

    found  = lease.get("tenant_signatures_found", 0)
    needed = lease.get("tenant_signatures_needed", 0)
    if needed > 0 and found < needed:
        return ValidationIssue(
            id             = "missing_lease_signatures",
            severity       = "warning",
            label          = f"חוזה: חסרות {needed - found} חתימות שוכר",
            description    = (
                f"החוזה מציין {needed} שוכרים אך נמצאו רק {found} חתימות."
            ),
            rule_triggered = "missing_lease_signatures",
            affected_fields= ["מסמכים.חוזה_שכירות"],
            conflicting_values={
                "חתימות_נמצאו": str(found),
                "חתימות_נדרשות": str(needed),
            },
            suggestion = "ודא שכל השוכרים חתמו על החוזה.",
        )
    return None
