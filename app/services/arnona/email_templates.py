"""
RTL Hebrew email templates for the arnona transfer service.

Company: מה זה קל
Phone:   058-773-2700
Email:   docs@mazekal.co.il

Rules:
  - Always RTL Hebrew
  - Company name: "מה זה קל" (NOT מזכ"ל)
  - Addressed to the main applicant by first name
  - List each missing item clearly with instructions on where to find it
  - Polite and professional tone
"""
from __future__ import annotations

from typing import Any


COMPANY_NAME  = "מה זה קל"
COMPANY_PHONE = "058-773-2700"
COMPANY_EMAIL = "docs@mazekal.co.il"


def _first_name(summary: dict[str, Any]) -> str:
    customer = summary.get("דייר_נכנס", {})
    full = customer.get("שם", "")
    return full.split()[0] if full and full != "—" else "לקוח יקר"


def _ref_number(summary: dict[str, Any]) -> str:
    internal = summary.get("מידע_פנימי", {})
    ref = internal.get("מספר_פנייה", "")
    return "" if not ref or ref == "לא סופק" else ref


def _address(summary: dict[str, Any]) -> str:
    prop = summary.get("פרטי_נכס", {})
    return prop.get("כתובת", "הנכס שצוין בטופס")


def draft_missing_info_email(
    summary: dict[str, Any],
    missing_info: list[dict],
    missing_docs: list[dict],
) -> dict[str, str] | None:
    """
    Generate a Hebrew RTL email requesting missing information and/or documents.
    Returns None if nothing is missing.
    """
    if not missing_info and not missing_docs:
        return None

    first_name = _first_name(summary)
    ref_number = _ref_number(summary)
    address    = _address(summary)
    txn = summary.get("סוג_עסקה", {})
    services = (
        txn.get("לאן_מעבירים")
        or txn.get("שירותים")
        or txn.get("שירות")
        or "העברת חשבון"
    )
    if services == "לא סופק":
        services = "העברת חשבון"

    ref_line = f"(מספר פנייה: {ref_number})" if ref_number else ""

    # ── Subject ───────────────────────────────────────────────────────────────
    subject = f"השלמת פרטים — בקשתך ל{services} | {COMPANY_NAME}"

    # ── Body ──────────────────────────────────────────────────────────────────
    lines: list[str] = []

    lines.append(f"שלום {first_name},")
    lines.append("")
    lines.append(f"תודה על פנייתך לשירות {services}.")
    lines.append("")

    if ref_line:
        lines.append(
            f"בבדיקת הטופס שמילאת {ref_line} עבור הנכס ברחוב {address},"
            " נמצא כי חסרים הפרטים הבאים:"
        )
    else:
        lines.append(
            f"בבדיקת הטופס שמילאת עבור הנכס ברחוב {address},"
            " נמצא כי חסרים הפרטים הבאים:"
        )
    lines.append("")

    # Missing info
    if missing_info:
        lines.append("פרטים חסרים:")
        for item in missing_info:
            label  = item.get("label", "")
            reason = item.get("reason", "")
            if reason:
                lines.append(f"  • {label} — {reason}")
            else:
                lines.append(f"  • {label}")
        lines.append("")

    # Missing documents
    if missing_docs:
        lines.append("מסמכים חסרים:")
        for item in missing_docs:
            label  = item.get("label", "")
            reason = item.get("reason", "")
            if reason:
                lines.append(f"  • {label} — {reason}")
            else:
                lines.append(f"  • {label}")
        lines.append("")

    lines.append("אנא השב/י למייל זה עם הפרטים החסרים, ונמשיך בטיפול בהקדם.")
    lines.append("")
    lines.append("לכל שאלה אנחנו כאן,")
    lines.append(f"צוות {COMPANY_NAME}")
    lines.append(f"📞 {COMPANY_PHONE}")
    lines.append(f"📧 {COMPANY_EMAIL}")

    return {
        "subject": subject,
        "body":    "\n".join(lines),
    }


def draft_complete_confirmation_email(
    summary: dict[str, Any],
) -> dict[str, str]:
    """
    Optional: confirmation email when submission is complete.
    """
    first_name = _first_name(summary)
    ref_number = _ref_number(summary)
    address    = _address(summary)
    txn = summary.get("סוג_עסקה", {})
    services = (
        txn.get("לאן_מעבירים")
        or txn.get("שירותים")
        or txn.get("שירות")
        or "העברת חשבון"
    )
    if services == "לא סופק":
        services = "העברת חשבון"

    ref_line = f"(מספר פנייה: {ref_number})" if ref_number else ""

    subject = f"קיבלנו את בקשתך — {services} | {COMPANY_NAME}"

    lines = [
        f"שלום {first_name},",
        "",
        f"תודה על פנייתך לשירות {services} {ref_line}.",
        "",
        f"קיבלנו את כל המסמכים הנדרשים עבור הנכס ברחוב {address}.",
        "הבקשה מועברת לטיפול ונעדכן אותך בהמשך.",
        "",
        "לכל שאלה אנחנו כאן,",
        f"צוות {COMPANY_NAME}",
        f"📞 {COMPANY_PHONE}",
        f"📧 {COMPANY_EMAIL}",
    ]

    return {
        "subject": subject,
        "body":    "\n".join(lines),
    }
