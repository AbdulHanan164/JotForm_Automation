# Architecture: מה זה קל — JotForm Webhook Pipeline v0.6.0

**Company:** מה זה קל  
**Contact:** 058-773-2700 | docs@mazekal.co.il  
**Rule:** Email is NEVER sent automatically — always requires human operator approval.

---

## System Overview

```
JotForm Form
    │
    │  POST /webhook?token=<WEBHOOK_SECRET>
    │  multipart/form-data (rawRequest + file uploads)
    ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FastAPI Application                          │
│                                                                 │
│  app/main.py           ← lifespan: startup checks, JotForm sync│
│  app/auth.py           ← FIX #1/#2: token + API key auth       │
│  app/routes/webhook.py ← main entry point                      │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼  (after token verified, idempotency checked)
┌─────────────────────────────────────────────────────────────────┐
│                    Pipeline Orchestrator                        │
│            app/pipeline/orchestrator.py                        │
│                                                                 │
│  1. Service Lookup  ─────────────────────────────────────────  │
│     form_id → Python service (priority) OR YAML-driven service │
│                                                                 │
│  2. parse_fields(raw_fields)                                   │
│     Returns section-keyed dict (FIX #4):                      │
│     {"basic": {"עיר": "..."}, "customer": {...}, ...}         │
│                                                                 │
│  3. ConditionalLogicEngine.evaluate(parsed)                    │
│     Returns visibility: {"field_label": True/False}            │
│     Uses section-keyed lookup (FIX #4)                         │
│                                                                 │
│  4. build_summary(parsed)                                      │
│     Returns human-readable Hebrew summary dict                  │
│                                                                 │
│  5. detect_missing(parsed, summary, visibility)                │
│     Skips hidden fields. Returns missing_info + missing_docs.  │
│                                                                 │
│  6. validate(parsed, doc_extractions)                          │
│     Cross-field business rules                                  │
│                                                                 │
│  7. draft_email(summary, missing)                              │
│     Hebrew email text IF missing items exist. Never auto-sent. │
│                                                                 │
│  Returns PipelineResult                                         │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│              Post-Pipeline (webhook.py, after run_pipeline)    │
│                                                                 │
│  FIX #6: download_submission_documents(parsed, submission_id)  │
│    → Downloads all file URLs from JotForm                      │
│    → Stores at data/documents/{id}/{hebrew_label}.{ext}        │
│    → Updates parsed[section][label]["local_path"]              │
│    → Writes data/documents/{id}/_manifest.json                 │
│    (JotForm URLs expire — download immediately before saving)  │
│                                                                 │
│  save_raw()      → data/submissions/{ts}_{id}_raw.json         │
│  save_business() → data/processed/{ts}_{id}_business.json      │
│  save_for_review() → data/review_queue/{id}.json               │
│                                                                 │
│  FIX #5: background_tasks.add_task(_sync_to_sheets_bg)        │
│    → Returns HTTP 200 FIRST, then syncs to Google Sheets       │
│    → Failure here is non-fatal (logged, not raised)            │
│                                                                 │
│  Return 200 {"status": "received", "idempotent_replay": false} │
└─────────────────────────────────────────────────────────────────┘

────────────────── Idempotency (FIX #7) ──────────────────────────

  On every webhook:
  1. Extract submission_id from rawRequest
  2. Check data/review_queue/{submission_id}.json
  3. If exists → return {"idempotent_replay": true} immediately
     (JotForm retries on timeout; this prevents duplicate records)
  4. If not exists → run pipeline as normal

────────────────── Authentication (FIX #1 + #2) ──────────────────

  Webhook endpoint:  ?token=<WEBHOOK_SECRET>  (query param)
    Checked by verify_webhook_token() in app/auth.py
    JotForm adds token to URL when submitting

  All operator routes: X-API-Key: <OPERATOR_API_KEY>  (header)
    OR  Authorization: Bearer <OPERATOR_API_KEY>
    Checked by require_operator() dependency in app/auth.py
    Uses secrets.compare_digest() — constant-time comparison

  Dev mode:
    If OPERATOR_API_KEY or WEBHOOK_SECRET is not set in .env,
    auth is DISABLED with a loud WARNING in the log.
    Never run in production without these set.

  Public (no auth):  GET /   |   GET /health

────────────────── Human Review Workflow ─────────────────────────

  RULE: Email is NEVER sent automatically.
  The operator must explicitly approve each submission.

  Flow:
    1. Webhook arrives → pipeline runs → review record created
    2. Operator: GET /review  (list pending)
    3. Operator: GET /review/{id}  (see full details)
    4. Operator: GET /review/{id}/email  (read draft email)
    5. Operator: PUT /review/{id}/email  (optionally edit email)
    6. Operator: POST /review/{id}/approve  (get final email)
    7. Operator: manually sends email via Gmail
    8. Operator: POST /review/{id}/sent  (mark as sent)

  Status lifecycle:
    pending_review → approved → sent
    pending_review → rejected
    pending_review → needs_info
```

---

## Service Architecture

```
Service Registry (built at startup by orchestrator.py)
┌─────────────────────────────────────────────────────┐
│  form_id: "251955479892982"                         │
│  → ArnonaService  (Python, highest priority)        │
│     app/services/arnona/service.py                  │
│     Field IDs: app/services/arnona/field_map.py     │
│     Field IDs source: config/field_maps/arnona.yaml │
│     Rules:    app/services/arnona/rules.py          │
│     Cond.logic: app/pipeline/conditional_logic.py   │
└─────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────┐
│  form_id: "<electricity form id>"                   │
│  → YAMLDrivenService (YAML, no Python required)     │
│     config/services/electricity.yaml                │
└─────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────┐
│  form_id: "<water form id>"                         │
│  → YAMLDrivenService                                │
│     config/services/water.yaml                      │
└─────────────────────────────────────────────────────┘

Priority rule: Python-coded service always wins if form_id matches.
The arnona YAML (config/services/arnona.yaml) was deleted in v0.6
to prevent divergence — ArnonaService is authoritative.
```

---

## Parsed Data Format (v0.6 Standard)

All services return this section-keyed format (FIX #4):

```python
{
    "basic": {
        "עיר":               "רמת גן",
        "שירותים_נבחרים":   ["ארנונה", "מים"],
        "תאריך_כניסה":      "01/07/2026",
    },
    "customer": {
        "שם_פרטי":   "ישראל",
        "שם_משפחה":  "ישראלי",
        "טלפון":     "050-1234567",
        "אימייל":    "israel@example.com",
        "תעודת_זהות": "123456789",
    },
    "partner":   {...},    # second tenant if present
    "outgoing":  {...},    # outgoing tenant if present
    "landlord":  {...},    # property owner
    "property":  {...},    # address fields
    "arnona":    {...},    # arnona account numbers
    "water":     {...},    # water account numbers
    "documents": {
        "חוזה_שכירות": {
            "present":    True,
            "url":        "https://jotform.com/uploads/... (may expire)",
            "local_path": "data/documents/{id}/חוזה_שכירות.pdf",  # FIX #6
        },
        "תעודת_זהות": {...},
        "חתימה":      {...},
    },
    "payment":   {...},
    "system":    {...},
    "_unmapped": {"unknown_field_id": "raw_value"},  # for discovery
}
```

ConditionalLogicEngine receives this dict and evaluates conditions as:
```python
parsed.get(cond.section, {}).get(cond.field)
# e.g. parsed.get("basic", {}).get("עיר") == "רמת גן"
```

---

## Data Storage

```
data/                          ← NEVER commit to git (contains PII)
  submissions/
    20260610_123456_{id}_raw.json      ← full technical dump (debug)
  processed/
    20260610_123456_{id}_business.json ← Hebrew business summary
  review_queue/
    {submission_id}.json               ← mutable review state
  documents/                           ← FIX #6: downloaded files
    {submission_id}/
      תעודת_זהות.jpg
      חוזה_שכירות.pdf
      חתימה.png
      _manifest.json
  logs/
    webhook.log

config/                        ← committed to git
  field_maps/
    arnona.yaml                ← FIX #3: editable field ID mapping
  services/
    electricity.yaml           ← YAML-driven service (future)
    water.yaml                 ← YAML-driven service (future)
  forms/
    {form_id}_synced.json      ← cached JotForm form definition
```

---

## Background Tasks (FIX #5)

```
Webhook request path (must be fast — JotForm times out at ~30s):
  verify token → idempotency → pipeline → download docs → save files → return 200

After response is sent (background, non-blocking):
  _sync_to_sheets_bg(result)
    → load YAML config for sheet_id and column mapping
    → write to Google Sheets
    → any failure is logged, never raised

This prevents JotForm retry storms caused by slow Sheets API calls.
```

---

## Dead Code Removed in v0.6

These directories were v0.1/v0.2 remnants with no callers. Deleted:

```
app/parsers/             ← replaced by ArnonaService.parse_fields()
app/models/              ← replaced by PipelineResult dataclass
app/outputs/             ← replaced by save_raw()/save_business()
app/services/rules/      ← replaced by app/services/arnona/rules.py
app/services/integrations/ ← placeholder HubSpot/AI/Drive stubs
```

Also removed:
- `submission_service.push_to_hubspot()` — NotImplementedError stub
- `submission_service.enrich_with_ai()` — NotImplementedError stub
- `submission_service.upload_to_google_drive()` — NotImplementedError stub
- `config/services/arnona.yaml` — duplicate of Python ArnonaService

---

## What v0.6 Does NOT Include

By design — not forgotten:

- **No AI/ML** — rule-based only
- **No OCR** — documents stored but not read
- **No HubSpot** — no CRM integration
- **No automatic email sending** — always operator-approved
- **No new service types** — only arnona is fully coded
- **No rate limiting** — assumed to be handled by reverse proxy
- **No HTTPS termination** — assumed reverse proxy (nginx/Caddy)
- **No multi-operator roles** — single shared OPERATOR_API_KEY
