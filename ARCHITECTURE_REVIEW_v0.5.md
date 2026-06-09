# Senior Architect Review — v0.5.0
## מה זה קל — JotForm Automation Pipeline
**Date:** 2026-06-09  
**Reviewer:** Senior Architect (AI-assisted)  
**Codebase:** https://github.com/AbdulHanan164/JotForm_Automation.git

---

> **Executive summary.**  
> The core pipeline logic is well-structured and the human-review-first constraint is correctly enforced throughout. However, three issues require immediate attention before any real customer data touches this system: (1) zero authentication on all endpoints, (2) a critical structural inconsistency between the Python service and YAML service parsed-data formats that makes YAML conditional logic silently non-functional, and (3) all field IDs in `field_map.py` are still placeholders — the system cannot correctly parse any real JotForm submission today.  
>
> The remaining gaps are real but less urgent. They are ranked and explained below.

---

## 1. Scalability

### 1.1 Can it support dozens of services?
**Verdict: Yes, with one fix needed.**

The YAML-driven architecture is sound in principle — adding a new service is just adding a YAML file. However, a critical inconsistency exists between the Python service parsed-data format and the YAML service parsed-data format (detailed in §6). Until that is fixed, new YAML services will have silently broken conditional logic and missing-field detection.

The service registry (`_SERVICES` dict) runs `_register()` at **module import time** as a module-level side effect. This causes two problems:
- Any YAML parse error during startup silently swallows the failure (`except Exception: logger.warning(...)`)  
- Testing individual pipeline stages is harder because the registry is already populated

**Fix:** Move `_register()` into the `lifespan` context manager, where startup failures are visible.

### 1.2 Can it support thousands of submissions per month?
**Verdict: Yes for ~1,000/month. No for 10,000+/month.**

The current bottleneck chain:

| Stage | Current implementation | Break point |
|---|---|---|
| File I/O per submission | 3 writes (raw, business, review) | ~500/day before disk latency accumulates |
| `load_all()` in review queue | Scans ALL `*.json` files, O(n) | ~500 files before operators notice lag |
| `_sync_to_sheets()` in webhook | Called synchronously, blocks response | Any Sheets API timeout (2–10s) blocks JotForm retry |
| Document extraction | Currently mock; when AI is real, each file = 1–3 API calls | Each call takes 3–10s, pipeline would need async |
| Google Sheets API | `append_row()` is synchronous HTTP | Rate limit: 60 requests/min |

**The most dangerous one is Google Sheets sync in the webhook handler.** JotForm has a 5-second webhook timeout. If the Sheets API takes longer, JotForm will retry the webhook, creating duplicate submissions. This must be moved to a background task.

### 1.3 Bottlenecks ranked

1. **Google Sheets sync is synchronous in the webhook handler** — causes JotForm retries under any API latency
2. **`load_all()` scans all files** — no index, O(n) on review queue size  
3. **Full pipeline runs synchronously per webhook** — when AI document extraction is real, this becomes 10–30s
4. **No idempotency check** — JotForm retries create duplicate review items
5. **`_SERVICES` registry rebuilt on every server restart** — minor, but YAML load time grows with service count

---

## 2. Maintainability

### 2.1 Dead code from early versions
The following directories appear to be remnants of v0.1/v0.2 and are no longer called by anything in the current pipeline. They will confuse future developers:

```
app/parsers/                       ← replaced by app/services/{service}/field_map.py
app/parsers/field_maps/main_form.py
app/parsers/jotform_parser.py
app/services/rules/                ← replaced by app/services/{service}/validators.py
app/services/integrations/        ← replaced by app/integrations/
app/outputs/                       ← appears unused
app/models/onboarding.py          ← appears unused
```

These should be deleted before more developers join. Dead code that looks like it might still be active is worse than no code.

### 2.2 Duplicate conditional logic encoding — HIGH RISK

The arnona conditional logic is encoded in **three separate places**:

1. `app/services/arnona/conditional_logic.py` — the executable `ConditionalRule` objects
2. `app/services/arnona/field_map.py` — `CITY_HIDDEN_FIELDS` dict (a second encoding of the same rules)
3. `config/services/arnona.yaml` — `conditional_rules:` section (a third encoding)

When a JotForm conditional rule changes, a developer must update all three. There is no test to confirm they agree. This will diverge silently.

**Fix:** Remove `CITY_HIDDEN_FIELDS` from `field_map.py` — it's redundant. The engine is the single source of truth.

### 2.3 Two incompatible parsed-data schemas

This is the most serious maintainability problem in the codebase. (Also flagged in §6.)

- **ArnonaService** returns a section-keyed dict: `{"basic": {"עיר": "ת"א"}, "customer": {...}}`
- **YAMLDrivenService** returns a flat dict: `{"עיר": "ת"א", "שם פרטי (דייר נכנס)": "..."}`

Every downstream component (conditional logic engine, validator, summary builder, missing detector) was written for the section-keyed format. When YAML services run, those components receive the flat format — results are silently wrong, not errored.

### 2.4 Hebrew label naming inconsistency

Labels in `field_map.py` use underscores: `"שם_פרטי"`, `"תעודת_זהות"`  
Labels in `arnona.yaml` use spaces and parentheses: `"שם פרטי (דייר נכנס)"`, `"תעודת זהות (דייר נכנס)"`

These are different strings. Any code that references a label by name will silently miss fields if it was written for one format and receives the other.

**Fix:** Pick one convention and enforce it as a schema rule in the YAML loader.

### 2.5 `reviewed_by` is an unauthenticated string

`POST /review/{id}/approve` accepts `reviewed_by: str = Body("operator")`. An operator can write anything. There is no audit integrity. The approval trail means nothing legally or operationally.

---

## 3. Reliability

### 3.1 JotForm API down
**Current behavior:** On startup, `sync_all()` catches exceptions with `logger.warning()` and continues. The pipeline falls back to whatever is already in `config/forms/{id}.json`.  
**Assessment:** Acceptable, because the cache TTL is 6 hours. The server starts and processes submissions using cached definitions.  
**Gap:** If the cache file doesn't exist yet (first run, no prior sync), no fallback exists. The service will register with Python-only rules and YAML services with no form definitions.

### 3.2 Google Sheets API down
**Current behavior:** `_sync_to_sheets()` in `webhook.py` catches all exceptions with `logger.warning()`.  
**Assessment:** Correctly non-blocking. The submission is still processed.  
**Gap:** There is no retry mechanism. If Sheets is down during a spike of submissions, those rows are never written. The operator's review dashboard (if using Sheets) will have gaps with no indication of what's missing.

### 3.3 Document extraction fails
**Current behavior:** `extract_all()` catches per-document exceptions and returns a `BaseExtraction` with `state=FAILED`.  
**Assessment:** Correct isolation — one bad document doesn't fail the pipeline.  
**Gap:** The pipeline continues with `doc_extractions = {}` if the entire `extract_all` call throws. In that case, all cross-doc validators silently skip (they check `state in ("not_attempted", "mock")`). The review item shows no validation issues — not because there are none, but because extraction failed. This is a silent false-negative.

### 3.4 Invalid YAML config
**Current behavior:** `_load_yaml()` catches parse exceptions and returns `{}`. `load_yaml_services()` skips files with missing `form_id`. The pipeline continues with only Python services.  
**Gap:** An operator edits `arnona.yaml`, introduces a YAML syntax error, restarts the server. The YAML service silently disappears. The Python ArnonaService still runs (because Python services override YAML), so submissions are still processed, but with the old Python rules. The operator has no idea their config change did nothing.  
**Fix:** On startup, validate all YAML files and fail loudly if any are syntactically invalid.

### 3.5 Concurrent review queue writes
`update_status()` does `load() → modify → save()`. If two operators open the same review item simultaneously and both approve:

1. Operator A: `load()` → gets `pending_review`
2. Operator B: `load()` → gets `pending_review`  
3. Operator A: `save()` → writes `approved`
4. Operator B: `save()` → overwrites with `approved` again (no check)

This is a last-write-wins race. In practice, with one operator it's unlikely but not impossible (browser double-click, tab refresh).

### 3.6 Missing submission deduplication
JotForm retries webhooks on timeout. If the pipeline takes >5 seconds, JotForm sends the same submission again. The system creates:
- Two `*_raw.json` files (different timestamps)
- Two `*_business.json` files  
- Two review queue entries (the second overwrites the first, losing any in-progress review)

---

## 4. Security

This section is written with the assumption that these files contain **Israeli ID numbers, lease agreements with addresses, phone numbers, and email addresses** — all of which are personally identifiable information (PII) under Israeli privacy law (חוק הגנת הפרטיות).

### 4.1 CRITICAL — No authentication on any endpoint

Every endpoint in the system is publicly accessible with no authentication:

| Endpoint | Exposure |
|---|---|
| `POST /webhook` | Anyone can inject fake submissions |
| `GET /review` | Anyone can see all pending customer submissions |
| `GET /review/{id}` | Full customer PII, documents, emails |
| `GET /discover/{id}` | Raw form field dump including PII |
| `POST /review/{id}/approve` | Anyone can approve submissions |
| `GET /admin/forms` | Internal form structure |
| `GET /submissions` | Full list of processed submissions |

**There is no API key, no session token, no OAuth, nothing.** If this server's URL is known — and JotForm webhook URLs are sometimes guessable — any person on the internet can read every customer's personal data and approve or reject their submissions.

This is the single highest-priority fix before any real customer data is processed.

**Minimum acceptable before production:**
- HTTP Basic Auth or Bearer token on all non-webhook routes
- JotForm webhook signature verification on `POST /webhook`

### 4.2 CRITICAL — No JotForm webhook signature verification

JotForm can sign webhooks with a secret key. Without verifying this signature, anyone who discovers the webhook URL can POST fake submissions. These fake submissions:
- Enter the review queue
- Are shown to operators alongside real submissions
- Can contain crafted PII to confuse the operator

### 4.3 HIGH — JotForm document URLs expire

JotForm-uploaded documents (ID photos, lease PDFs) are served via temporary signed URLs that typically expire in hours to days. The system stores these URLs in:
- `data/submissions/*_raw.json`
- `data/review_queue/{id}.json`

After expiry, every URL in the stored data returns 403. The operator can no longer view documents for any past submission. The extracted data (MOCK state) is the only thing that survives. When AI extraction is real, the extracted fields survive but the source document is gone.

**Fix:** On first receipt of a submission, download and store copies of all uploaded documents in a controlled location (encrypted at rest). Don't rely on JotForm URLs persisting.

### 4.4 HIGH — PII stored in plain-text JSON files with no access control

`data/submissions/`, `data/processed/`, and `data/review_queue/` contain:
- Full name, ID number, phone, email (customer, partner, outgoing tenant, landlord)
- Property address
- Lease agreement contents (when AI extraction runs)
- Draft emails mentioning all of the above

These files have no:
- Encryption at rest
- File-system access control (beyond OS defaults)
- Retention policy (files accumulate indefinitely)
- Anonymization or pseudonymization

Under the Israeli Privacy Protection Regulations (תקנות הגנת הפרטיות), the data controller must implement security measures appropriate to the sensitivity of data held.

### 4.5 MEDIUM — No audit log

The system has no tamper-proof audit trail. `reviewed_by` is a freeform string field. There is no log of:
- Which IP address approved submission X
- What the email content was at the time of approval
- Whether the email was edited before approval
- When the email was actually sent

If a customer disputes an action, there is no evidence.

### 4.6 MEDIUM — `/discover/{id}` exposes raw PII to anyone

`GET /discover/{id}` was designed as a developer tool to identify JotForm field IDs. It returns the full raw form data including customer PII. This endpoint must be:
- Removed from production, or
- Secured behind admin authentication, and
- Rate-limited

### 4.7 LOW — HTTP headers stored in raw JSON

`result.headers` stores all incoming HTTP headers in the raw JSON. These headers may include:
- JotForm internal tokens
- Proxied Authorization headers
- Internal routing headers from Cloudflare/nginx

These should be stripped before storage.

---

## 5. Data Storage Strategy

### 5.1 Is file-based storage still appropriate?

At the current scale (tens of submissions per month for a single service), **yes, file-based storage is acceptable**. The design deliberately deferred this decision, and that was correct.

However, the three-file-per-submission design already shows strain:

**Problem 1: Out-of-sync files.**  
`{ts}_{id}_raw.json`, `{ts}_{id}_business.json`, and `{id}.json` (review queue) can disagree. If the review queue item is updated (operator edits email) but the business file is not, they diverge. The current system has no reconciliation mechanism.

**Problem 2: No submissions index.**  
`load_all()` reads every file in the directory. There is no index by date, status, customer name, or service. Searching or reporting requires scanning all files.

**Problem 3: Multiple business files per submission.**  
`save_business()` uses a timestamp prefix: `{ts}_{id}_business.json`. If called twice for the same submission (e.g., after a resubmission), there will be two business files. `get_submission()` does `glob(f"*_{submission_id}_business.json")` and returns the first match — which may be the older one.

### 5.2 Recommended storage strategy

**For v0.6 (current file system, improved):**
- Replace three files with **one canonical file per submission**: `data/submissions/{id}.json` containing all data
- The review queue JSON is the single mutable record; raw and business data are views of the same object
- Add a simple `data/index.json` that maps `submission_id → {received_at, status, service, customer_name}` for fast listing

**For v1.0 (database):**
- Migrate to **SQLite** (not PostgreSQL — you don't need a server for this scale)
- SQLite gives: ACID transactions (fixes the concurrent-write race), full-text search, proper indexes, a single file to back up
- PostgreSQL is appropriate only when you have multiple server instances (horizontal scaling), which is not needed below ~50k submissions/month

**What to store permanently vs temporarily:**

| Data | Keep permanently | Notes |
|---|---|---|
| Parsed business data (no raw JotForm IDs) | Yes | Core business record |
| Review workflow history (status changes) | Yes | Audit trail |
| Draft and final email text | Yes | Legal record of communications |
| Validation issues at time of submission | Yes | Shows what was flagged |
| Extracted document data | Yes | Even MOCK — shows what was checked |
| Raw JotForm field dump | 90 days then delete | Debug only; contains PII |
| Uploaded document copies | Until processed + 1 year | Then delete per retention policy |
| HTTP headers | Never | No business value, may contain tokens |

---

## 6. Service Configuration Design (YAML Architecture)

### 6.1 Critical defect: YAML services have incompatible parsed-data format

This is a **silent bug that makes YAML-driven services functionally broken** for conditional logic, missing detection, and validation.

**ArnonaService (Python) `parse_fields()` returns:**
```python
{
    "basic":    {"עיר": "רמת גן", "שירותים_נבחרים": ["ארנונה"]},
    "customer": {"שם_פרטי": "ישראל", "שם_משפחה": "ישראלי"},
    ...
}
```

**YAMLDrivenService `parse_fields()` returns:**
```python
{
    "עיר": "רמת גן",
    "שם פרטי (דייר נכנס)": "ישראל",
    ...
}
```

`ConditionalLogicEngine._eval_condition()` does:
```python
section_data = parsed.get(cond.section, {})  # "basic" → {}  (not found in flat dict)
raw_value = section_data.get(cond.field, "")  # always ""
```

Result: **Every condition evaluates to False. No fields are ever hidden. All conditionally-required fields get flagged as missing incorrectly.**

The YAML `get_conditional_logic_engine()` creates `Condition(section="")` for every rule. `parsed.get("", {})` always returns `{}`. The engine is structurally broken for YAML services.

**Fix required:** Pick one parsed format. The section-keyed format is better (structured, explicit). Update `YAMLDrivenService.parse_fields()` to return section-keyed output, using the `section` field already present in the YAML field definitions.

### 6.2 Label naming convention is undefined

The YAML uses: `label: "שם פרטי (דייר נכנס)"` — natural language with spaces and parentheses  
`field_map.py` uses: `"שם_פרטי"` — underscored key within a section dict

These are entirely different identifiers. Any lookup that compares them will silently fail. Before adding more services, you need a documented, enforced convention:

**Recommended:** Use short underscore keys within sections (like `field_map.py` does). The YAML `display_label` can be natural language for UI display, but `label` (the key used for lookups) must follow the underscore convention.

### 6.3 YAML conditional rules don't specify sections

In `arnona.yaml`:
```yaml
conditions:
  - field: "עיר"
    operator: equals
    value: "רמת גן"
```

No `section` key. In `arnona/conditional_logic.py`:
```python
Condition(field="עיר", section="basic", operator=Op.EQUALS, value="רמת גן")
```

The Python version explicitly specifies `section="basic"`. The YAML version will create `Condition(section="")`. The engine will never find the field. YAML rules must include `section`.

### 6.4 The dual-service-definition problem

For the arnona service, there are now **two service definitions** that can never be completely in sync:

1. `app/services/arnona/` — Python service with field_map, validators, conditional logic, rules, summary builder
2. `config/services/arnona.yaml` — YAML service with different field labels, different conditional rule format

The Python service "wins" (by design). The YAML is effectively dead for arnona. But they will diverge over time as one is updated and the other isn't, causing confusion about which is authoritative.

**Recommendation:** For arnona specifically, either:
- Delete the YAML entirely (Python service is the source of truth), OR
- Delete the Python service and migrate it fully to YAML + a Python validators-only module (since declarative YAML can't express cross-doc validation)

Don't keep both running in parallel.

### 6.5 Missing YAML schema validation

There is no schema validation for service YAMLs. A typo in the YAML (`reqiured` instead of `required`) silently produces wrong behavior. No error is raised at load time.

**Fix:** Add a JSON Schema or Pydantic model to validate YAML structure at load time. Fail loudly on startup if a service YAML has structural errors.

---

## 7. Human Review Workflow

### 7.1 The workflow is conceptually correct
The core enforcement — email never sent without approval — is implemented correctly throughout. The status state machine (pending → approved/rejected/needs_info → sent) is sound.

### 7.2 Missing: re-submission linkage

When the operator marks a submission `needs_info` and the client re-submits the form, there is no mechanism to:
- Link the new submission to the original
- Automatically close the original as superseded
- Show the operator a diff between the original and the re-submission

In practice, the operator will see two separate review items with no connection between them. This will cause confusion and potential duplicate processing.

### 7.3 Missing: operator notification

There is no mechanism to notify operators when a new submission arrives. The operator must poll `GET /review` manually. For a business processing dozens of requests per day, this is unusable — submissions will sit unreviewed for hours.

**Minimum viable:** Send an email/Slack message to the team when a new submission enters the queue. A simple outbound email (using Python's `smtplib`) is sufficient.

### 7.4 Missing: SLA tracking

There is no `due_by` timestamp, no aging indicator, no escalation trigger. A submission could sit in `pending_review` for a week with no indication that it is overdue. For a service business, processing time is a key metric.

### 7.5 Missing: transition from APPROVED to SENT

`ReviewStatus.SENT` exists as an enum value but there is no endpoint to mark a submission as sent. After the operator sends the email manually via Gmail, the system permanently shows the submission as `approved`, not `sent`. The operator has no way to record that the action was completed.

### 7.6 Missing: bulk operations

If 20 submissions arrive simultaneously (e.g., after a campaign), the operator must approve them one at a time via `POST /review/{id}/approve`. There is no bulk-approve or bulk-reject endpoint.

### 7.7 Edge case: approve a submission with errors
`POST /review/{id}/approve` does not block approval when `has_errors=True`. An operator can approve a submission that the validation engine flagged with errors. Sometimes this is correct (human overrides the system). But it should require an explicit acknowledgment: `{"override_errors": true, "reason": "..."}`.

### 7.8 `needs_info` doesn't reset when client resubmits

When a submission is in `needs_info` state and the client calls the operator with the missing information, the operator updates the review item to `approved` directly. But if the operator updates the form and resubmits, the new submission creates a new review item while the old one stays in `needs_info`. There is no status `awaiting_resubmission` and no webhook linkage.

---

## 8. Production Readiness

The following issues must be resolved before any real customer data is processed.

### Severity 1 — BLOCKER (prevents production deployment)

| # | Issue | File | Impact |
|---|---|---|---|
| 1 | **No authentication on any endpoint** | All routes | Complete data exposure to the internet |
| 2 | **No JotForm webhook signature verification** | `routes/webhook.py` | Fake submissions can be injected |
| 3 | **All field IDs in `field_map.py` are placeholders** | `services/arnona/field_map.py` | System cannot correctly parse any real submission |
| 4 | **YAML conditional logic silently broken** (§6.1) | `config_service/loader.py` | YAML services have wrong hidden-field logic |

### Severity 2 — HIGH (fix before real customers)

| # | Issue | File | Impact |
|---|---|---|---|
| 5 | **Google Sheets sync blocks webhook response** | `routes/webhook.py` | JotForm retries → duplicate submissions |
| 6 | **JotForm document URLs expire** (§4.3) | `review/queue.py` | Documents unviewable within hours |
| 7 | **No idempotency** on webhook | `routes/webhook.py` | JotForm retries create duplicates |
| 8 | **PII stored plaintext with no access control** | `data/` directories | Privacy law compliance |
| 9 | **No operator notification** on new submission | (missing) | Submissions sit unreviewed indefinitely |

### Severity 3 — MEDIUM (fix in v0.6)

| # | Issue | Impact |
|---|---|---|
| 10 | Dead code from v0.1/v0.2 still in tree | Confusion, maintenance burden |
| 11 | `load_all()` scans all files (no index) | Slow review queue at 500+ submissions |
| 12 | Concurrent write race on review queue | Data loss if two operators act simultaneously |
| 13 | No YAML schema validation | Silent misconfiguration |
| 14 | No audit log with real identity | No legal trail for approvals |
| 15 | Duplicate service definitions (arnona Python + YAML) | Will diverge silently |

### Severity 4 — LOW (fix before v1.0)

| # | Issue | Impact |
|---|---|---|
| 16 | No re-submission linkage | Operator confusion |
| 17 | No SLA tracking | No visibility into processing time |
| 18 | APPROVED → SENT transition missing | Incomplete workflow |
| 19 | No bulk review operations | Operator inefficiency |
| 20 | No health check that tests real functionality | Monitoring is ineffective |

---

## 9. Technical Debt

All current shortcuts and mocks, ranked by risk to the business.

### Risk: HIGH — will cause wrong business outcomes when activated

| Item | Location | Risk if not fixed before AI activation |
|---|---|---|
| All field IDs are placeholders | `services/arnona/field_map.py` | Zero fields parsed correctly from real submissions |
| `_ai_extract()` raises NotImplementedError | `documents/lease_analyzer.py` | AI extraction crashes, swallowed by try/except, silent MOCK result |
| Document download not implemented | `documents/extractor.py` | AI extraction will receive expired URLs → all extractions fail |
| YAML conditional logic broken | `config_service/loader.py` | All fields show as visible, wrong missing-field detection |

### Risk: MEDIUM — functional gaps, not silent failures

| Item | Location | Notes |
|---|---|---|
| ID card OCR returns MOCK | `documents/extractor.py` | No ID number cross-validation possible |
| Arnona bill OCR returns MOCK | `documents/extractor.py` | Account number cross-validation not possible |
| Water bill extraction not implemented | `documents/extractor.py` | No label in dispatch map |
| HubSpot integration stub | `services/submission_service.py` | Raises NotImplementedError |
| Google Drive integration stub | `services/submission_service.py` | Raises NotImplementedError |
| Electricity service stub | `services/electricity/service.py` | Raises NotImplementedError for all methods |
| Water service stub | `services/water/service.py` | Raises NotImplementedError for all methods |
| `app/db/` is empty | `app/db/` | No data model exists |
| `app/documents/ocr/` is empty | `app/documents/ocr/` | No OCR strategy defined |
| Empty `tests/` directory | `tests/` | Zero automated test coverage |

### Risk: LOW — code quality, not functional correctness

| Item | Location | Notes |
|---|---|---|
| Dead v0.1/v0.2 code | `app/parsers/`, `app/services/rules/`, `app/services/integrations/`, `app/outputs/`, `app/models/` | Confusing but inert |
| `form_id` and `service_name` as `@property` on ArnonaService returning constants | `services/arnona/service.py` | Works, but odd pattern |
| `ValidationIssue.to_dict()` uses `__dict__` with enum conversion | `pipeline/validator.py` | Fragile, breaks with `__slots__` or property-based fields |
| `PipelineResult.validation_issues` typed as `list["ValidationIssue"]` but stored as dicts after review round-trip | `review/models.py` | Type inconsistency between pipeline and review item |
| PyYAML not verified present at startup | `config_service/loader.py` | Silently falls back to empty services |

---

## 10. Roadmap

### What the roadmap must NOT be driven by
Do not add new features until the four Severity-1 blockers are fixed. Adding electricity/water services, AI extraction, or HubSpot integration on top of a system with broken authentication and broken conditional logic creates technical debt that multiplies.

---

### v0.6 — Security and Reliability Foundation
**Goal:** This system can be safely exposed to the internet with real customer data.  
**Timeframe estimate:** 2–3 weeks of focused development.

**Must include:**
1. **Webhook authentication:** Bearer token (`WEBHOOK_SECRET` in `.env`); JotForm sends it as a header or query param. Reject any request without it.
2. **Review API authentication:** HTTP Basic Auth or a static API key. Single user is fine for now; do not build OAuth yet.
3. **Webhook idempotency:** Check if `submission_id` already exists in the review queue before running the pipeline. Return 200 (idempotent acknowledge) if duplicate.
4. **Move Sheets sync to background:** Use FastAPI's `BackgroundTasks` to run `_sync_to_sheets` after returning the 200 response. One-line change.
5. **Document URL preservation:** On webhook receipt, immediately download and save copies of all uploaded files to `data/documents/{submission_id}/`. Store local paths, not JotForm URLs.
6. **Fix YAML conditional logic engine:** Update `YAMLDrivenService.parse_fields()` to return section-keyed output. Add `section` to YAML conditional rule conditions.
7. **Fix field IDs in `field_map.py`:** Receive one real JotForm submission, run `/discover/{id}`, update all field IDs. This is manual work that cannot be automated away.
8. **Delete dead code:** Remove `app/parsers/`, `app/services/rules/`, `app/services/integrations/`, `app/outputs/`, `app/models/`. They are not used.
9. **YAML schema validation:** Add a Pydantic model for the service YAML schema. Fail with a clear error at startup if any YAML is invalid.
10. **Operator notification:** Send one email to the ops team email when a new submission enters the queue. Use Python `smtplib`. No new dependencies.

**Must NOT include in v0.6:**
- AI document extraction (mock is fine)
- New services (electricity, water)
- Database migration
- HubSpot integration

---

### v0.7 — Operational Completeness
**Goal:** The ops team can manage this system without developer intervention for routine tasks.  
**Timeframe estimate:** 3–4 weeks after v0.6 is stable.

**Must include:**
1. **SQLite migration:** Replace file scanning with SQLite. Schema: one `submissions` table, one `review_events` table (audit log), one `documents` table. Keep the current file-based backup as an export feature.
2. **Real field IDs verified:** Receive 10+ real submissions across all cities (רמת גן, תל אביב, אשדוד), verify conditional logic fires correctly, confirm missing-field detection is accurate.
3. **Audit log:** Every review action (approve/reject/edit/needs_info) writes to a separate, append-only `review_events` table with timestamp + actor identity.
4. **SLA tracking:** Add `due_by` (48h after receipt) and a `GET /review?overdue=true` filter.
5. **Re-submission linkage:** When a submission arrives for a customer whose previous submission is in `needs_info`, automatically link them and surface the diff to the operator.
6. **`SENT` status endpoint:** `POST /review/{id}/sent` — operator marks that the email was actually sent.
7. **Resolve dual arnona service definition:** Either delete the YAML for arnona (Python service is authoritative) or migrate fully to YAML + a separate validators module. Document the decision.
8. **Basic test suite:** At minimum, test the conditional logic engine, missing-field detection, and validation rules with known input fixtures. This is how you prevent regressions when field IDs are finally updated.

**Must NOT include in v0.7:**
- AI document extraction (requires its own testing cycle)
- HubSpot integration
- Multi-user authentication (single API key is fine until v1.0)

---

### v1.0 — Production Quality
**Goal:** The system can handle 3–5 services and hundreds of submissions per month with minimal operator intervention for clean submissions.  
**Timeframe estimate:** 6–8 weeks after v0.7 is stable.

**Must include:**
1. **AI document extraction for the lease contract:** Start with lease only — highest value, validates the most critical cross-doc rules. Use OpenAI GPT-4o Vision. The interface already exists in `documents/lease_analyzer.py`; implement `_ai_extract()`.
2. **Electricity and water services fully operational:** Real form IDs, real field maps, conditional logic verified.
3. **Retention policy enforcement:** Automated deletion of expired data per policy (raw data after 90 days, documents after 1 year + processed). Logged deletions.
4. **Multi-operator identity:** Replace the freeform `reviewed_by` string with a real identity (even if just a list of named users from `.env`). Operators select their name from a dropdown in the review UI.
5. **Google Sheets two-way sync:** When operator updates review status, write the status back to the Sheet. Currently only submission arrival is written.
6. **Scalability for 1,000/month:** Verify `load_all()` performance with 1,000 records. If SQLite is in place (from v0.7), this is a query, not a file scan.
7. **Real end-to-end test per service:** Scripted test that submits a real (anonymized) form, runs the full pipeline, and verifies: correct hidden fields, correct missing detection, correct email draft.

**What should NOT be in v1.0:**
- HubSpot CRM integration (build only if the client confirms it's needed)
- Full OCR for ID cards (high effort, marginal value if the lease extraction works)
- Automatic email sending (the human-review constraint was a deliberate client requirement; do not remove it without explicit client sign-off)

---

## Summary Priority Table

| Priority | Fix | Effort | Risk if deferred |
|---|---|---|---|
| **P0** | Add authentication to all endpoints | 1 day | Data breach |
| **P0** | Verify JotForm webhook signature | 2 hours | Fake submissions |
| **P0** | Verify real field IDs | 1 day (manual) | System parses nothing correctly |
| **P0** | Fix YAML conditional logic engine | 1 day | Wrong hidden-field detection |
| **P1** | Move Sheets sync to background | 2 hours | JotForm retries, duplicates |
| **P1** | Download and store uploaded documents | 1 day | Documents become unreachable |
| **P1** | Add webhook idempotency | 4 hours | Duplicate submissions |
| **P2** | Delete dead v0.1/v0.2 code | 2 hours | Confusion, maintenance debt |
| **P2** | YAML schema validation | 4 hours | Silent misconfiguration |
| **P2** | Fix dual arnona service definition | 4 hours | Diverging definitions |
| **P3** | SQLite migration | 1 week | Scalability ceiling |
| **P3** | Audit log | 2 days | No legal trail |
| **P3** | Re-submission linkage | 3 days | Operator confusion |
| **P3** | Test suite | 1 week | Regression risk on field ID update |
