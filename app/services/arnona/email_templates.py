"""
RTL Hebrew email templates for the arnona transfer service.

Company: מה זה קל

Style (derived from a real Mazekal email, Step 5A audit):
  - Short, warm, personal, second-person.
  - Natural Hebrew only — NO internal field names, NO underscores, NO
    technical/validation language, NO machine bullet trees.
  - Missing details and documents are presented together (not split into
    "פרטים חסרים" / "מסמכים חסרים" sections).
  - One shared rationale + soft urgency (authority requirement + faster
    handling), not per-item technical reasons.
  - Contact channel is WhatsApp 055-973-2700 (the form's own
    companyPhoneNumber; matches Alexander's real email). The previous
    058-773-2700 / docs@mazekal.co.il values came from form-field prefill
    defaults (q380 "My Phone", q190 "My email") — not a customer contact
    channel — so they are intentionally NOT used here.
  - Fixed closing block.

Per-item presentation (Step 5B decision 4/5): each missing item is rendered
with a human name and a single clear action line. Detection is presence-only,
so document instructions are document-level generic (we name the document and
say what to send) — we never invent which page/part is missing.
"""
from __future__ import annotations

from typing import Any


COMPANY_NAME     = "מה זה קל"
COMPANY_WHATSAPP = "055-973-2700"


# Human-readable presentation for each detection rule, keyed by rule id.
# (name, action) — natural Hebrew, no internal labels, no validation language.
_ITEM_PRESENTATION: dict[str, tuple[str, str]] = {
    # ── Missing information ────────────────────────────────────────────────
    "city":                   ("עיר הנכס",
                               "נא לציין את שם העיר שבה נמצא הנכס."),
    "move_in_date":           ("תאריך הכניסה לנכס",
                               "נא לציין את התאריך שבו נכנסתם לנכס."),
    "move_out_date":          ("תאריך היציאה מהנכס",
                               "נא לציין את התאריך שבו עזבתם/תעזבו את הנכס."),
    "partner_name":           ("שם השוכר הנוסף",
                               "נא לציין שם פרטי ושם משפחה של השוכר הנוסף."),
    "customer_name":          ("שם הדייר הנכנס",
                               "נא לציין שם פרטי ושם משפחה מלאים."),
    "customer_phone":         ("טלפון ליצירת קשר",
                               "נא לציין מספר טלפון נייד."),
    "customer_email":         ("כתובת אימייל",
                               "נא לציין כתובת אימייל לקבלת עדכונים ואישורים."),
    "customer_id":            ("תעודת זהות",
                               "נא לציין את מספר תעודת הזהות."),
    "partner_id":             ("תעודת זהות של השוכר הנוסף",
                               "נא לציין את מספר תעודת הזהות של השוכר הנוסף הרשום בבקשה."),
    "outgoing_id":            ("תעודת זהות של הדייר היוצא",
                               "נדרשת לסגירת החשבון על שמו — נא לציין את מספר תעודת הזהות."),
    "outgoing_phone":         ("טלפון של הדייר היוצא",
                               "נא לציין מספר טלפון ליצירת קשר עם הדייר היוצא."),
    "owner_phone":            ("טלפון של בעל הנכס",
                               "נדרש לאישור ההעברה מול בעל הנכס — נא לציין מספר טלפון."),
    "arnona_property_number": ("מספר נכס בארנונה",
                               "מופיע בחשבון הארנונה — נא לציין את מספר הנכס."),
    "arnona_customer_number": ("מספר משלם בארנונה",
                               "מופיע בחשבון הארנונה — נא לציין את מספר המשלם/לקוח."),
    "arnona_id_number":       ("מספר זיהוי הנכס בארנונה",
                               "מופיע בחשבון הארנונה — נא לציין את מספר זיהוי הנכס."),
    # ── Missing documents ──────────────────────────────────────────────────
    "id_photo":               ("צילום תעודת זהות",
                               "נא לצרף צילום ברור של תעודת הזהות."),
    "lease_contract":         ("חוזה שכירות",
                               "נא לשלוח חוזה שכירות חתום ומלא."),
    "sale_contract":          ("חוזה מכר",
                               "נא לשלוח חוזה מכר חתום ומלא."),
    "signature":              ("חתימה על הבקשה",
                               "נא לחתום על הבקשה."),
    "arnona_bill":            ("חשבון ארנונה",
                               "נא לצרף חשבון ארנונה עדכני של הנכס."),
    "corp_cert":              ("תעודת התאגדות",
                               "נא לצרף תעודת התאגדות של החברה."),
    "tabu":                   ("נסח טאבו",
                               "נא לצרף נסח טאבו עדכני של הנכס."),
}


def _first_name(summary: dict[str, Any]) -> str:
    customer = summary.get("דייר_נכנס", {})
    full = customer.get("שם", "")
    return full.split()[0] if full and full != "—" else ""


def _present_item(item: dict[str, Any]) -> tuple[str, str]:
    """Map a detection item to (human name, action). Falls back gracefully."""
    rid = item.get("id") or item.get("rule_triggered") or ""
    if rid in _ITEM_PRESENTATION:
        return _ITEM_PRESENTATION[rid]
    # Fallback: de-underscore the label, no technical reason text.
    name = str(item.get("label", "")).replace("_", " ").strip() or "פרט חסר"
    return name, "נא להשלים פרט זה."


def _greeting(first_name: str) -> str:
    # Real Mazekal style: "{name} שלום" — name first, no comma.
    return f"{first_name} שלום" if first_name else "שלום רב"


def _closing_lines() -> list[str]:
    return [
        "אפשר לשלוח הכל במענה למייל הזה או בוואטסאפ " + COMPANY_WHATSAPP,
        "",
        "לכל שאלה, אנחנו כאן בשבילך",
        "תודה מראש על שיתוף הפעולה",
        f"צוות {COMPANY_NAME}",
    ]


def draft_missing_info_email(
    summary: dict[str, Any],
    missing_info: list[dict],
    missing_docs: list[dict],
) -> dict[str, str] | None:
    """
    Generate a warm, human Hebrew RTL email requesting the missing items.
    Missing details and documents are presented together. Returns None if
    nothing is missing.
    """
    if not missing_info and not missing_docs:
        return None

    first_name = _first_name(summary)

    subject = f"השלמת פרטים לבקשתך | {COMPANY_NAME}"

    lines: list[str] = []
    lines.append(_greeting(first_name))
    lines.append("")
    lines.append("תודה על השימוש במערכת להעברת חשבונות של מה זה קל")
    lines.append("")
    lines.append("יש לנו כמה פרטים/מסמכים שעדיין חסרים בקשר לחשבונות שביקשת שנעביר")
    lines.append("")
    lines.append(
        "חשוב להתייחס לכל פרט — כל אחד הינו דרישה של הרשויות "
        "וגם מקצר את זמני הטיפול 🙏🙏"
    )
    lines.append("")

    # Combined list: details + documents, each as a name + one action line.
    for item in list(missing_info) + list(missing_docs):
        name, action = _present_item(item)
        lines.append(name)
        lines.append(action)
        lines.append("")

    lines.extend(_closing_lines())

    return {
        "subject": subject,
        "body":    "\n".join(lines),
    }


def draft_complete_confirmation_email(
    summary: dict[str, Any],
) -> dict[str, str]:
    """Confirmation email when nothing is missing — same warm Mazekal style."""
    first_name = _first_name(summary)

    subject = f"קיבלנו את בקשתך | {COMPANY_NAME}"

    lines = [
        _greeting(first_name),
        "",
        "תודה על השימוש במערכת להעברת חשבונות של מה זה קל",
        "",
        "קיבלנו את כל הפרטים והמסמכים הנדרשים, והבקשה מועברת לטיפול.",
        "נעדכן אותך בהמשך 🙏",
        "",
        "לכל שאלה, אנחנו כאן בשבילך",
        f"אפשר להשיב למייל הזה או בוואטסאפ {COMPANY_WHATSAPP}",
        f"צוות {COMPANY_NAME}",
    ]

    return {
        "subject": subject,
        "body":    "\n".join(lines),
    }
