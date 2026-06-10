# Summary Layout Review — מה זה קל Operator Summary

**Purpose:** This document defines the fixed operator summary template.
All sections appear in every summary regardless of transaction type.

---

## Section Order

| # | Section (Hebrew) | Section (English) | Always Shown |
|---|-----------------|-------------------|:---:|
| 1 | מידע על העסקה | Transaction Information | ✅ |
| 2 | שירותים מבוקשים | Services Requested | ✅ |
| 3 | פרטי הנכס | Property Information | ✅ |
| 4 | תאריכים | Dates | ✅ |
| 5 | דייר נכנס | Incoming Tenant | ✅ |
| 6 | שוכר שני / שותף | Partner / Second Tenant | ✅ |
| 7 | דייר יוצא | Outgoing Tenant | ✅ |
| 8 | בעל הבית | Landlord | ✅ |
| 9 | חשבון ארנונה | Arnona Account | ✅ |
| 10 | חשבון מים | Water Account | ✅ |
| 11 | חשבון חשמל | Electricity Account | ✅ |
| 12 | מסמכים | Documents | ✅ |
| 13 | פרטי תשלום | Payment Information | ✅ |
| 14 | מידע חסר | Missing Information | ✅ |
| 15 | אזהרות ובעיות | Validation Warnings | ✅ |
| 16 | פעולה מומלצת | Recommended Action | ✅ |
| 17 | מידע פנימי | Internal Information | ✅ |

---

## Fields Per Section

### 1. מידע על העסקה — Transaction Information

| Field | Mandatory | Optional | Source |
|-------|:---------:|:--------:|--------|
| סוג עסקה (transaction type) | ✅ | | Derived from package + move_type |
| חבילת שירות (package name) | ✅ | | Form — selected package |
| עיר (city) | ✅ | | Form — property city |
| סוג לקוח (client type) | ✅ | | Form — person type |
| סוג תשלום (payment type) | | ✅ | Form — payment type field |

**Empty value:** "לא סופק" (Not Provided)

---

### 2. שירותים מבוקשים — Services Requested

| Field | Mandatory | Optional | Source |
|-------|:---------:|:--------:|--------|
| ארנונה — Municipal tax | | ✅ | Form multi-select |
| מים — Water | | ✅ | Form multi-select |
| חשמל — Electricity | | ✅ | Form multi-select |
| גז — Gas | | ✅ | Form multi-select |
| ועד בית — Building committee | | ✅ | Form multi-select |

**Note:** At least one service must be selected. ✅ = Selected, ❌/blank = Not selected.

---

### 3. פרטי הנכס — Property Information

| Field | Mandatory | Optional | Source |
|-------|:---------:|:--------:|--------|
| כתובת מלאה (full address) | ✅ | | Assembled from sub-fields |
| עיר (city) | ✅ | | Form |
| רחוב (street) | ✅ | | Form |
| מספר בניין (building) | ✅ | | Form |
| דירה (apartment) | ✅ | | Form |
| קומה (floor) | | ✅ | Form |
| כניסה (entrance) | | ✅ | Form |

**Empty value:** "לא סופק"

---

### 4. תאריכים — Dates

| Field | Mandatory | Optional | Source |
|-------|:---------:|:--------:|--------|
| תאריך כניסה (move-in date) | ✅ | | Form |
| תאריך יציאה (move-out date) | | ✅ | Form — only for exit flows |
| תאריך סיום חוזה (lease end) | | ✅ | Form |
| משך חוזה (duration) | | ✅ | Calculated |
| תאריך העברה (transfer date) | | ✅ | Form — FHS normalized |

**Empty value:** "לא סופק"

---

### 5. דייר נכנס — Incoming Tenant

| Field | Mandatory | Optional | Source | Generates Missing Request |
|-------|:---------:|:--------:|--------|:---:|
| שם מלא (full name) | ✅ | | Form / FHS | ✅ |
| טלפון (phone) | ✅ | | Form / FHS | ✅ |
| אימייל (email) | ✅ | | Form / FHS | ✅ |
| תעודת זהות (ID number) | ✅* | | Form / FHS | ✅ |
| סוג לקוח (client type) | ✅ | | Form | |

*Not mandatory for corporate clients — company registration number required instead.

---

### 6. שוכר שני / שותף — Partner / Second Tenant

| Field | Mandatory | Optional | Source | Generates Missing Request |
|-------|:---------:|:--------:|--------|:---:|
| שם מלא | | ✅ | Form / FHS | If phone present but no ID |
| טלפון | | ✅ | Form / FHS | |
| אימייל | | ✅ | Form / FHS | |
| תעודת זהות | | ✅ | Form / FHS | ✅ If partner has phone |

**Empty value when no partner:** "לא סופק" — section always shown.

**Triggers validation warning:** Partner phone provided without ID number.

---

### 7. דייר יוצא — Outgoing Tenant

| Field | Mandatory | Optional | Source | Generates Missing Request |
|-------|:---------:|:--------:|--------|:---:|
| שם מלא | ✅* | | Form / FHS | ✅ |
| טלפון | ✅* | | Form / FHS | ✅ |
| אימייל | ✅* | | Form / FHS | ✅ |
| תעודת זהות | ✅* | | Form / FHS | ✅ |

*Required only when an outgoing tenant exists (rental transfer, not account_closure).

**Empty value when no outgoing tenant:** "לא סופק" — section always shown.

---

### 8. בעל הבית — Landlord

| Field | Mandatory | Optional | Source | Generates Missing Request |
|-------|:---------:|:--------:|--------|:---:|
| שם מלא | | ✅ | Form / FHS | |
| טלפון | ✅ | | Form / FHS | ✅ Always required |
| אימייל | | ✅ | Form / FHS | ✅ |
| תעודת זהות | | ✅ | Form / FHS | ✅ |

**Empty value when no landlord:** "לא סופק" — section always shown.

---

### 9. חשבון ארנונה — Arnona Information

| Field | Mandatory | Optional | Notes |
|-------|:---------:|:--------:|-------|
| מספר נכס (property number) | ✅ | | Required for municipality registration |
| מספר לקוח (payer number) | ✅ | | Required |
| מספר זיהוי נכס (identification) | ✅ | | Required |
| מספר חשבון תושב | | ✅ | Ramat Gan specific |
| מספר חשבון לקוח | | ✅ | Ramat Gan specific |

**New registrations:** All fields will show "לא סופק" — this is expected.
**Existing account transfers:** All mandatory fields must be provided.

---

### 10. חשבון מים — Water Information

| Field | Mandatory | Optional | Notes |
|-------|:---------:|:--------:|-------|
| מספר נכס | ✅* | | *Only if Water was selected |
| מספר לקוח | ✅* | | *Only if Water was selected |

**Empty value:** "לא סופק" — shown even when water was not selected.

---

### 11. חשבון חשמל — Electricity Information

| Field | Mandatory | Optional | Notes |
|-------|:---------:|:--------:|-------|
| מספר מונה (meter number) | ✅* | | Required when electricity selected |
| קריאת מונה (meter reading) | ✅* | | Required when electricity selected |
| מספר נכס | | ✅ | For existing accounts |
| מספר לקוח | | ✅ | For existing accounts |

**Note:** Form currently collects meter number and reading. Account numbers (IEC registration) are created after submission.

---

### 12. מסמכים — Documents

| Document | Individual | Corporate | Generates Missing Request |
|----------|:---------:|:---------:|:---:|
| תעודת זהות (ID photo) | ✅ Required | — replaced by corp cert | ✅ |
| חתימה (signature) | ✅ Required | ✅ Required | ✅ |
| חוזה שכירות (lease) | ✅ Required | ✅ Required | ✅ |
| חשבון ארנונה (arnona bill) | ✅ Required | ✅ Required | ✅ |
| תעודת התאגדות (corp cert) | — | ✅ Required | ✅ If corporate |
| נסח טאבו (tabu) | — | ✅ Required | ✅ If corporate |
| אישור תנאים (terms) | ✅ Required | ✅ Required | ✅ |
| הסכם שירות (agreement) | ✅ Required | ✅ Required | ✅ |

**Display:** ✅ = Received, ❌ = Missing, "לא רלוונטי" = Not applicable for this client type.

---

### 13. פרטי תשלום — Payment Information

| Field | Mandatory | Notes |
|-------|:---------:|-------|
| חבילה (package name) | ✅ | Human-readable name |
| סכום (amount) | ✅ | In ₪ |
| סטטוס תשלום (payment status) | ✅ | ✅ שולם / ❌ לא שולם |
| תאריך תשלום | ✅ | Submission date |

**No technical IDs** (Stripe IDs, transaction hashes) appear here.

---

### 14. מידע חסר — Missing Information

Auto-generated from missing detection engine. Each item shows:
- Field name (Hebrew)
- Importance level: **חובה** (mandatory) / **נדרש** (required) / **מומלץ** (recommended)
- Reason why it is needed

**Empty state:** "אין פרטים חסרים — הבקשה מלאה ✅"

---

### 15. אזהרות ובעיות — Validation Warnings

Auto-generated from cross-document validation engine. Types of warnings:

| Severity | Icon | Description |
|----------|:----:|-------------|
| שגיאה (error) | ❌ | Blocks processing — must be resolved |
| אזהרה (warning) | ⚠️ | Requires operator attention |
| מידע (info) | ℹ️ | Notable but no action needed |

**Empty state:** "אין אזהרות — הבקשה תקינה ✅"

---

### 16. פעולה מומלצת — Recommended Action

Auto-generated based on missing items + validation warnings.

| Condition | Action |
|-----------|--------|
| Missing mandatory docs | 📧 Send email requesting missing items |
| All complete, no warnings | ✅ Ready to process — submit to municipality |
| Validation errors | 🔍 Manual review required before sending |
| Payment not received | 💳 Follow up on payment |

---

### 17. מידע פנימי — Internal Information

| Field | Mandatory | Notes |
|-------|:---------:|-------|
| מספר פנייה (MZK reference) | ✅ | Internal case number |
| מזהה החזר (refund ID) | ✅ | For refund tracking |
| תאריך הגשה | ✅ | Submission date |
| שעת הגשה | ✅ | Submission time |
| שם לקוח | ✅ | For quick identification |

**No JotForm IDs, webhook URLs, IP addresses, or system metadata appear here.**

---

## Field Classification Summary

### Always Mandatory (Blocks Processing if Missing)
- Incoming tenant: name, phone, email, ID (individuals only)
- Landlord: phone
- Move-in date
- Property: city, street, building, apartment
- At least one service selected
- Arnona account numbers (transfer only — not new registrations)
- Documents: ID photo, signature, lease contract, arnona bill

### Conditional Mandatory (Required Only When Applicable)
- Outgoing tenant fields — only for rental/sale transfers
- Water account numbers — only when water service selected
- Electricity meter number — only when electricity selected
- Corporate docs (corp cert, tabu) — only for corporate clients
- Partner ID — only when partner has phone number

### Optional (Improves Processing Speed)
- Floor, entrance, building number
- Move-out date
- Lease end date
- All email fields (landlord, outgoing tenant)
- Landlord ID number

### Always Shown (Fixed Template — Never Hidden)
All 17 sections above are always present in every operator summary.
Empty sections display "לא סופק" (Not Provided) rather than being removed.

---

## What Never Appears in Operator Summary

The following technical data is **never** shown to operators:

- JotForm field IDs (q21_firstName21, etc.)
- Webhook URLs or endpoint information
- IP addresses or browser information
- Stripe transaction IDs or payment method IDs
- Raw JSON field names or system keys
- Internal validation scores or debug flags
- HubSpot contact IDs
- jsExecutionTracker or similar metadata

---

*Document version: v0.7.0 | מה זה קל Webhook Architecture*
