"""
Field map for form 251955479892982 — "העברת חשבון ארנונה" (Arnona account transfer).

HOW TO FILL IN FIELD IDs:
  1. Receive a real submission.
  2. Open the _raw JSON in data/submissions/
  3. Look inside "_raw_request" — that's your rawRequest dict.
  4. Each key like "q5_input5" maps to a form field.
  5. Match the value to the Hebrew label you see in JotForm builder.
  6. Add/update the FIELD_MAP entries below.

You can also use:  GET /discover/{submission_id}
which shows all raw field IDs alongside their values.

Current status:
  Fields marked with # VERIFIED have been confirmed from real submissions.
  Fields marked with # TODO need verification from actual submission JSON.
"""
from __future__ import annotations

# ── Section constants ─────────────────────────────────────────────────────────
S_BASIC     = "basic"       # move type, city, service selection
S_CUSTOMER  = "customer"    # main applicant
S_PARTNER   = "partner"     # second tenant / spouse
S_OUTGOING  = "outgoing"    # outgoing tenant
S_LANDLORD  = "landlord"    # property owner / landlord
S_PROPERTY  = "property"    # address details
S_ARNONA    = "arnona"      # arnona account numbers
S_WATER     = "water"       # water account numbers
S_DOCS      = "documents"   # file uploads
S_PAYMENT   = "payment"     # payment info
S_SYSTEM    = "system"      # internal MZK IDs, deal type


# ── Field map ─────────────────────────────────────────────────────────────────
# Format: "jotform_field_id": {"label": str, "section": str, "type": str}
#
# Types:
#   text     — plain string
#   date     — will be formatted to DD/MM/YYYY
#   phone    — plain text (no normalisation yet)
#   email    — plain text
#   id_num   — Israeli ID number (plain text)
#   file     — uploaded file (URL stored)
#   signature— digital signature (URL stored)
#   bool     — checkbox / terms accepted
#   multi    — multi-select (list)
#   select   — single dropdown / radio

FIELD_MAP: dict[str, dict] = {

    # ── Basic / Transaction Info ──────────────────────────────────────────────
    # TODO: verify field IDs from actual submission JSON
    "q3_moveType3":      {"label": "סוג_מעבר",         "section": S_BASIC,    "type": "select"},
    "q4_cityName4":      {"label": "עיר",               "section": S_BASIC,    "type": "text"},
    "q5_services5":      {"label": "שירותים_נבחרים",    "section": S_BASIC,    "type": "multi"},
    "q6_moveOutDate6":   {"label": "תאריך_יציאה",       "section": S_BASIC,    "type": "date"},
    "q7_moveInDate7":    {"label": "תאריך_כניסה",       "section": S_BASIC,    "type": "date"},
    "q8_leaseEnd8":      {"label": "תאריך_סיום_חוזה",   "section": S_BASIC,    "type": "date"},
    "q9_transferDate9":  {"label": "תאריך_העברה",       "section": S_BASIC,    "type": "date"},
    "q10_personType10":  {"label": "סוג_לקוח",          "section": S_BASIC,    "type": "select"},

    # ── Main Customer ─────────────────────────────────────────────────────────
    "q21_firstName21":   {"label": "שם_פרטי",           "section": S_CUSTOMER, "type": "text"},
    "q22_lastName22":    {"label": "שם_משפחה",           "section": S_CUSTOMER, "type": "text"},
    "q23_phone23":       {"label": "טלפון",              "section": S_CUSTOMER, "type": "phone"},
    "q24_email24":       {"label": "אימייל",             "section": S_CUSTOMER, "type": "email"},
    "q25_idNumber25":    {"label": "תעודת_זהות",         "section": S_CUSTOMER, "type": "id_num"},

    # ── Partner / Second Tenant ───────────────────────────────────────────────
    # From the chat: input104 = first name, input235 = last name, input103 = phone
    # These are likely q-IDs but without the exact form we use generic placeholders
    "q104_input104":     {"label": "שם_פרטי",           "section": S_PARTNER,  "type": "text"},
    "q235_input235":     {"label": "שם_משפחה",           "section": S_PARTNER,  "type": "text"},
    "q103_input103":     {"label": "טלפון",              "section": S_PARTNER,  "type": "phone"},
    "q105_email105":     {"label": "אימייל",             "section": S_PARTNER,  "type": "email"},
    "q106_idNumber106":  {"label": "תעודת_זהות",         "section": S_PARTNER,  "type": "id_num"},

    # ── Outgoing Tenant ───────────────────────────────────────────────────────
    "q30_outFirstName30":{"label": "שם_פרטי",           "section": S_OUTGOING, "type": "text"},
    "q31_outLastName31": {"label": "שם_משפחה",           "section": S_OUTGOING, "type": "text"},
    "q32_outId32":       {"label": "תעודת_זהות",         "section": S_OUTGOING, "type": "id_num"},
    "q33_outPhone33":    {"label": "טלפון",              "section": S_OUTGOING, "type": "phone"},
    "q34_outEmail34":    {"label": "אימייל",             "section": S_OUTGOING, "type": "email"},

    # ── Property Owner / Landlord ─────────────────────────────────────────────
    "q40_ownerName40":   {"label": "שם_מלא",            "section": S_LANDLORD, "type": "text"},
    "q41_ownerPhone41":  {"label": "טלפון",              "section": S_LANDLORD, "type": "phone"},
    "q42_ownerEmail42":  {"label": "אימייל",             "section": S_LANDLORD, "type": "email"},
    "q43_ownerId43":     {"label": "תעודת_זהות",         "section": S_LANDLORD, "type": "id_num"},

    # ── Property Address ──────────────────────────────────────────────────────
    "q50_street50":      {"label": "רחוב",              "section": S_PROPERTY, "type": "text"},
    "q51_building51":    {"label": "בניין",             "section": S_PROPERTY, "type": "text"},
    "q52_apartment52":   {"label": "דירה",              "section": S_PROPERTY, "type": "text"},
    "q53_floor53":       {"label": "קומה",              "section": S_PROPERTY, "type": "text"},
    "q54_entrance54":    {"label": "כניסה",             "section": S_PROPERTY, "type": "text"},

    # ── Arnona Account Numbers ────────────────────────────────────────────────
    # Note: most are HIDDEN by JotForm conditional logic for רמת גן
    "q60_arnonaProperty60": {"label": "מספר_נכס",       "section": S_ARNONA,   "type": "text"},
    "q61_arnonaCust61":     {"label": "מספר_לקוח",      "section": S_ARNONA,   "type": "text"},
    "q62_arnonaId62":       {"label": "מספר_זיהוי_נכס", "section": S_ARNONA,   "type": "text"},
    "q63_arnonaTenant63":   {"label": "מספר_חשבון_תושב","section": S_ARNONA,   "type": "text"},
    "q64_arnonaCustomer64": {"label": "מספר_חשבון_לקוח","section": S_ARNONA,   "type": "text"},

    # ── Water Account Numbers ─────────────────────────────────────────────────
    # For רמת גן these are auto-filled from arnona numbers via conditional logic
    "q70_waterProperty70":  {"label": "מספר_נכס",       "section": S_WATER,    "type": "text"},
    "q71_waterCust71":      {"label": "מספר_לקוח",      "section": S_WATER,    "type": "text"},

    # ── Documents / File Uploads ──────────────────────────────────────────────
    "q80_idPhoto80":         {"label": "תעודת_זהות",    "section": S_DOCS,     "type": "file"},
    "q81_arnonaBill81":      {"label": "חשבון_ארנונה",  "section": S_DOCS,     "type": "file"},
    "q82_leaseContract82":   {"label": "חוזה_שכירות",  "section": S_DOCS,     "type": "file"},
    "q83_signature83":       {"label": "חתימה",         "section": S_DOCS,     "type": "signature"},
    "q84_tabu84":            {"label": "נסח_טאבו",      "section": S_DOCS,     "type": "file"},
    "q85_corpCert85":        {"label": "תעודת_התאגדות", "section": S_DOCS,     "type": "file"},
    "q86_deliveryProto86":   {"label": "פרוטוקול_מסירה","section": S_DOCS,     "type": "file"},
    "q87_terms87":           {"label": "תנאים",         "section": S_DOCS,     "type": "bool"},

    # ── Payment ───────────────────────────────────────────────────────────────
    "q90_amount90":          {"label": "סכום",          "section": S_PAYMENT,  "type": "text"},
    "q91_serviceName91":     {"label": "שם_שירות",      "section": S_PAYMENT,  "type": "text"},

    # ── System / Internal ─────────────────────────────────────────────────────
    "q100_mzkId100":         {"label": "מזהה_מזכ",      "section": S_SYSTEM,   "type": "text"},
    "q101_refundId101":      {"label": "מזהה_החזר",     "section": S_SYSTEM,   "type": "text"},
    "q102_dealType102":      {"label": "סוג_עסקה",      "section": S_SYSTEM,   "type": "text"},
    "q103_business103":      {"label": "עסק",           "section": S_SYSTEM,   "type": "text"},
    "q104_sourceUrl104":     {"label": "מקור_כתובת",    "section": S_SYSTEM,   "type": "text"},
}


# ── Conditional logic: city-specific rules ────────────────────────────────────
# These mirror the JotForm conditional logic exactly.
# Used by the rules engine to determine what is EXPECTED vs. HIDDEN.

CITY_HIDDEN_FIELDS: dict[str, dict[str, list[str]]] = {
    "רמת גן": {
        # Fields hidden when city = רמת גן + service contains ארנונה
        "ארנונה": [
            "מספר_זיהוי_נכס",
            "מספר_לקוח",           # arnona customer number
            "מספר_חשבון_תושב",
            "מספר_חשבון_לקוח",
        ],
        # Fields hidden when city = רמת גן + service contains מים
        "מים": [
            "מספר_לקוח_מים",       # auto-filled from arnona
            "מספר_חשבון_חוזה_מים",
            "מספר_זיהוי_מים",
        ],
    },
    "אשדוד": {
        # Asdod shares arnona→water auto-fill
        "מים": [
            "מספר_לקוח_מים",
            "מספר_זיהוי_מים",
        ],
    },
}

# ── Required documents per service type ──────────────────────────────────────
# Key = service label from שירותים_נבחרים
REQUIRED_DOCS: dict[str, list[str]] = {
    "ארנונה":  ["תעודת_זהות", "חוזה_שכירות", "חתימה"],
    "חשמל":    ["תעודת_זהות", "חוזה_שכירות", "חתימה"],
    "מים":     ["תעודת_זהות", "חוזה_שכירות", "חתימה"],
    "default": ["תעודת_זהות", "חוזה_שכירות", "חתימה"],
}

# ── Service direction labels ──────────────────────────────────────────────────
# Used to generate Hebrew summary line
SERVICE_DIRECTION_LABELS: dict[str, str] = {
    "IN":  "רישום על שם הדייר הנכנס",
    "OUT": "ביטול על שם הדייר היוצא",
}
