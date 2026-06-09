"""
Field map for form ID 250201745267957
"NEW MAIN FORM - 3.1 - Step 1 of 7"

Structure:
  FIELD_MAP = {
      "<jotform_field_id>": {
          "label": "<human readable name>",
          "section": "<section key>",
          "type": "text | date | phone | email | image | signature | multi | bool",
          "required": True | False,
      }
  }

When JotForm renames or renumbers a field, only update this file.
The rest of the pipeline never references raw field IDs.
"""

FORM_ID = "250201745267957"
FORM_VERSION = "3.1"

# ---------------------------------------------------------------------------
# Section keys — used for grouping in the summary
# ---------------------------------------------------------------------------
S_META        = "meta"
S_CUSTOMER    = "customer"
S_PROPERTY    = "property"
S_LEASE       = "lease"
S_SERVICES    = "services"
S_PAYMENT     = "payment"
S_DOCS        = "documents"
S_OUTGOING    = "outgoing_tenant"
S_LANDLORD    = "landlord"
S_SYSTEM      = "system"

FIELD_MAP: dict[str, dict] = {

    # ── Meta / envelope ────────────────────────────────────────────────────
    "q291_uniqueId291":     {"label": "unique_id",          "section": S_META,     "type": "text",      "required": True},
    "q324_uniqueRefund324": {"label": "refund_id",          "section": S_META,     "type": "text",      "required": False},
    "q184_uniqueId":        {"label": "unique_id_alt",      "section": S_META,     "type": "text",      "required": False},
    "q186_uniqueRefund":    {"label": "refund_id_alt",      "section": S_META,     "type": "text",      "required": False},
    "event_id":             {"label": "event_id",           "section": S_META,     "type": "text",      "required": False},

    # ── Customer (incoming tenant) ─────────────────────────────────────────
    "q21_input21":          {"label": "first_name",         "section": S_CUSTOMER, "type": "text",      "required": True},
    "q20_input20":          {"label": "last_name",          "section": S_CUSTOMER, "type": "text",      "required": True},
    "q30_input30":          {"label": "email",              "section": S_CUSTOMER, "type": "email",     "required": True},
    "q32_input32":          {"label": "id_number",          "section": S_CUSTOMER, "type": "text",      "required": True},
    "q208_input208":        {"label": "phone",              "section": S_CUSTOMER, "type": "phone",     "required": True},
    "q3_input3":            {"label": "move_type",          "section": S_CUSTOMER, "type": "text",      "required": True},
    "q6_input6":            {"label": "person_type",        "section": S_CUSTOMER, "type": "text",      "required": True},
    "q10_input10":          {"label": "payment_type",       "section": S_CUSTOMER, "type": "text",      "required": True},
    "q462_typeA462":        {"label": "tenant_status",      "section": S_CUSTOMER, "type": "text",      "required": False},

    # ── Property ───────────────────────────────────────────────────────────
    "q132_input132":        {"label": "city",               "section": S_PROPERTY, "type": "text",      "required": True},
    "q118_input118":        {"label": "street",             "section": S_PROPERTY, "type": "text",      "required": True},
    "q116_input116":        {"label": "building_number",    "section": S_PROPERTY, "type": "text",      "required": True},
    "q115_input115":        {"label": "apartment_number",   "section": S_PROPERTY, "type": "text",      "required": True},
    "q263_FullAddress":     {"label": "full_address",       "section": S_PROPERTY, "type": "text",      "required": False},
    "q135_input135":        {"label": "asset_number",       "section": S_PROPERTY, "type": "text",      "required": False},
    "q136_input136":        {"label": "customer_number",    "section": S_PROPERTY, "type": "text",      "required": False},
    "q532_input532":        {"label": "city_name",          "section": S_PROPERTY, "type": "text",      "required": False},

    # ── Lease ──────────────────────────────────────────────────────────────
    "q12_input12":          {"label": "move_in_date",       "section": S_LEASE,    "type": "date",      "required": True},
    "q13_input13":          {"label": "move_in_date_text",  "section": S_LEASE,    "type": "text",      "required": False},
    "q16_input16":          {"label": "lease_end_date",     "section": S_LEASE,    "type": "date",      "required": True},
    "q207_input207":        {"label": "duration_days",      "section": S_LEASE,    "type": "text",      "required": False},
    "q225_lengthOf":        {"label": "duration_days_calc", "section": S_LEASE,    "type": "text",      "required": False},
    "q530_inOut":           {"label": "direction",          "section": S_LEASE,    "type": "text",      "required": True},
    "q194_input194":        {"label": "return_date",        "section": S_LEASE,    "type": "date",      "required": False},
    "q14_input14":          {"label": "extra_date",         "section": S_LEASE,    "type": "date",      "required": False},

    # ── Utilities / services ───────────────────────────────────────────────
    "q122_input122":        {"label": "utilities_text",     "section": S_SERVICES, "type": "text",      "required": True},
    "q420_mappingField":    {"label": "utilities_csv",      "section": S_SERVICES, "type": "text",      "required": False},
    "q419_multiSelect":     {"label": "utilities_list",     "section": S_SERVICES, "type": "multi",     "required": False},
    "q561_input561":        {"label": "selected_packages",  "section": S_SERVICES, "type": "multi",     "required": True},
    "q527_billsTo527":      {"label": "bills_to",           "section": S_SERVICES, "type": "text",      "required": False},
    "q165_input165":        {"label": "electricity_meter",  "section": S_SERVICES, "type": "text",      "required": False},
    "q164_input164":        {"label": "electricity_reading","section": S_SERVICES, "type": "text",      "required": False},

    # ── Payment ────────────────────────────────────────────────────────────
    "q422_amount":          {"label": "amount",             "section": S_PAYMENT,  "type": "text",      "required": True},
    "q614_input614":        {"label": "coupon_code",        "section": S_PAYMENT,  "type": "text",      "required": False},
    "q615_input615":        {"label": "coupon_discount",    "section": S_PAYMENT,  "type": "text",      "required": False},
    "payment_transaction_uuid": {"label": "transaction_id","section": S_PAYMENT,  "type": "text",      "required": False},
    "payment_total_checksum":   {"label": "total_paid",    "section": S_PAYMENT,  "type": "text",      "required": False},
    "q573_calculationFor":  {"label": "calculated_amount",  "section": S_PAYMENT,  "type": "text",      "required": False},

    # ── Documents ──────────────────────────────────────────────────────────
    "q35_input35":          {"label": "id_photo",           "section": S_DOCS,     "type": "image",     "required": True},
    "q181_input181":        {"label": "signature",          "section": S_DOCS,     "type": "signature", "required": True},
    "q33_input33":          {"label": "id_photo_label",     "section": S_DOCS,     "type": "text",      "required": False},
    "q467_typeA467":        {"label": "terms_accepted",     "section": S_DOCS,     "type": "bool",      "required": True},
    "q341_typeA341":        {"label": "agreement_signed",   "section": S_DOCS,     "type": "bool",      "required": True},
    "q385_termsAnd":        {"label": "terms_and",          "section": S_DOCS,     "type": "text",      "required": False},

    # ── Outgoing tenant ────────────────────────────────────────────────────
    "q94_input94":          {"label": "first_name",         "section": S_OUTGOING, "type": "text",      "required": False},
    "q230_input230":        {"label": "last_name",          "section": S_OUTGOING, "type": "text",      "required": False},
    "q91_outboundTenant91": {"label": "email",              "section": S_OUTGOING, "type": "email",     "required": False},
    "q92_input92":          {"label": "id_number",          "section": S_OUTGOING, "type": "text",      "required": False},
    "q93_input93":          {"label": "phone",              "section": S_OUTGOING, "type": "phone",     "required": False},
    "q243_input243":        {"label": "full_name",          "section": S_OUTGOING, "type": "text",      "required": False},

    # ── Landlord ───────────────────────────────────────────────────────────
    "q110_input110":        {"label": "first_name",         "section": S_LANDLORD, "type": "text",      "required": False},
    "q236_input236":        {"label": "last_name",          "section": S_LANDLORD, "type": "text",      "required": False},
    "q107_input107":        {"label": "email",              "section": S_LANDLORD, "type": "email",     "required": False},
    "q108_input108":        {"label": "id_number",          "section": S_LANDLORD, "type": "text",      "required": False},
    "q109_input109":        {"label": "phone",              "section": S_LANDLORD, "type": "phone",     "required": False},
    "q248_input248":        {"label": "full_name",          "section": S_LANDLORD, "type": "text",      "required": False},

    # ── System / internal ──────────────────────────────────────────────────
    "q427_typeA427":        {"label": "user_agent",         "section": S_SYSTEM,   "type": "text",      "required": False},
    "q185_typeA":           {"label": "form_url",           "section": S_SYSTEM,   "type": "text",      "required": False},
    "q190_myEmail":         {"label": "company_email",      "section": S_SYSTEM,   "type": "email",     "required": False},
    "q192_business":        {"label": "company_name",       "section": S_SYSTEM,   "type": "text",      "required": False},
    "q193_moveType":        {"label": "move_type_full",     "section": S_SYSTEM,   "type": "text",      "required": False},
    "q344_mainUser":        {"label": "main_user_phone",    "section": S_SYSTEM,   "type": "text",      "required": False},
    "q345_mainUser345":     {"label": "main_user_email",    "section": S_SYSTEM,   "type": "email",     "required": False},
    "q480_dealName":        {"label": "deal_name",          "section": S_SYSTEM,   "type": "text",      "required": False},
    "q479_contactType479":  {"label": "contact_type",       "section": S_SYSTEM,   "type": "text",      "required": False},
    "visitedPages":         {"label": "visited_pages",      "section": S_SYSTEM,   "type": "text",      "required": False},
    "timeToSubmit":         {"label": "time_to_submit_sec", "section": S_SYSTEM,   "type": "text",      "required": False},
}

# ---------------------------------------------------------------------------
# Required document field IDs — used by the rule engine
# ---------------------------------------------------------------------------
REQUIRED_DOCS: dict[str, str] = {
    "id_photo":         "q35_input35",
    "signature":        "q181_input181",
    "terms_accepted":   "q467_typeA467",
    "agreement_signed": "q341_typeA341",
}

# ---------------------------------------------------------------------------
# Utility labels (Hebrew values that appear in q122_input122 / q419_multiSelect)
# ---------------------------------------------------------------------------
UTILITY_LABELS: dict[str, str] = {
    "גז":    "gas",
    "חשמל":  "electricity",
    "ארנונה": "municipality",
    "מים":   "water",
    "ועד":   "building_committee",
}
