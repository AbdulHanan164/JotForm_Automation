"""
Conditional logic rules for the arnona transfer form (251955479892982).

These rules are transcribed EXACTLY from the JotForm conditional logic editor.
Each rule mirrors one JotForm rule, with the same condition, action, and targets.

Source (pasted by client):
  Rule 1: IF services CONTAINS "מים" AND city = "רמת גן" → HIDE water fields
  Rule 2: IF services CONTAINS "ארנונה" AND city = "רמת גן" → HIDE arnona fields
  Rule 3: IF city = "אשדוד" OR city = "רמת גן" → AUTOFILL water customer ← arnona customer
  Rule 4: IF city = "אשדוד" OR city = "רמת גן" → AUTOFILL water property ← arnona property

When you get new conditional rules from JotForm, add them here following the same pattern.
"""
from __future__ import annotations

from app.pipeline.conditional_logic import (
    Condition, ConditionalRule, ConditionalLogicEngine, Op,
)

# ── Arnona form conditional rules ────────────────────────────────────────────

ARNONA_CONDITIONAL_RULES: list[ConditionalRule] = [

    # Rule 1 — Hide water account fields for רמת גן
    # "IF services CONTAINS מים AND city = רמת גן → Hide water numbers"
    ConditionalRule(
        note       = "רמת גן: מספרי מים מוסתרים (מתמלאים אוטומטית מארנונה)",
        logic      = "all",
        conditions = [
            Condition(field="שירותים_נבחרים", section="basic", operator=Op.CONTAINS, value="מים"),
            Condition(field="עיר",            section="basic", operator=Op.EQUALS,   value="רמת גן"),
        ],
        action  = "hide",
        targets = ["מספר_לקוח_מים", "מספר_חשבון_חוזה_מים", "מספר_זיהוי_מים"],
    ),

    # Rule 2 — Hide arnona account fields for רמת גן
    # "IF services CONTAINS ארנונה AND city = רמת גן → Hide arnona numbers"
    ConditionalRule(
        note       = "רמת גן: שדות ארנונה מוסתרים (מספר נכס בלבד נדרש)",
        logic      = "all",
        conditions = [
            Condition(field="שירותים_נבחרים", section="basic", operator=Op.CONTAINS, value="ארנונה"),
            Condition(field="עיר",            section="basic", operator=Op.EQUALS,   value="רמת גן"),
        ],
        action  = "hide",
        targets = ["מספר_זיהוי_נכס", "מספר_לקוח", "מספר_חשבון_תושב", "מספר_חשבון_לקוח"],
    ),

    # Rule 3 — Auto-fill water customer number from arnona for רמת גן / אשדוד
    ConditionalRule(
        note       = "רמת גן/אשדוד: מספר לקוח מים = מספר לקוח ארנונה (אוטומטי)",
        logic      = "any",
        conditions = [
            Condition(field="עיר", section="basic", operator=Op.EQUALS, value="רמת גן"),
            Condition(field="עיר", section="basic", operator=Op.EQUALS, value="אשדוד"),
        ],
        action          = "autofill",
        targets         = ["מספר_לקוח_מים"],
        autofill_source = "מספר_לקוח",
    ),

    # Rule 4 — Auto-fill water property number from arnona for רמת גן / אשדוד
    ConditionalRule(
        note       = "רמת גן/אשדוד: מספר נכס מים = מספר נכס ארנונה (אוטומטי)",
        logic      = "any",
        conditions = [
            Condition(field="עיר", section="basic", operator=Op.EQUALS, value="רמת גן"),
            Condition(field="עיר", section="basic", operator=Op.EQUALS, value="אשדוד"),
        ],
        action          = "autofill",
        targets         = ["מספר_נכס_מים"],
        autofill_source = "מספר_נכס",
    ),

    # Rule 5 — Hide corporate identity fields for private persons
    ConditionalRule(
        note       = "לקוח פרטי: שדות חברה מוסתרים",
        logic      = "all",
        conditions = [
            Condition(field="סוג_לקוח", section="basic", operator=Op.NOT_EQUALS, value="חברה"),
            Condition(field="סוג_לקוח", section="basic", operator=Op.NOT_EQUALS, value="תאגיד"),
        ],
        action  = "hide",
        targets = ["שם_חברה", "שם_נציג", "מספר_חפ"],
    ),

    # Rule 6 — Hide personal ID for companies
    ConditionalRule(
        note       = "לקוח חברה: שדות אישיים מוסתרים",
        logic      = "any",
        conditions = [
            Condition(field="סוג_לקוח", section="basic", operator=Op.EQUALS, value="חברה"),
            Condition(field="סוג_לקוח", section="basic", operator=Op.EQUALS, value="תאגיד"),
        ],
        action  = "hide",
        targets = ["תעודת_זהות"],  # personal ID hidden for companies
    ),
]

# Singleton engine instance — used by the arnona service
arnona_logic_engine = ConditionalLogicEngine(ARNONA_CONDITIONAL_RULES)
