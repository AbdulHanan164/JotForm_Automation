# Migration Plan: v0.5.0 → v0.6.0

**System:** מה זה קל — JotForm Webhook Pipeline  
**Contact:** 058-773-2700 | docs@mazekal.co.il  
**Date:** June 2026  
**Risk Level:** Low — no database, no schema changes, no client-facing UI

---

## Summary of Changes

v0.6.0 fixes 8 architectural blockers identified in the senior architect review.
No new features are added. No AI, OCR, or new services.

| Fix | What Changed | Impact |
|-----|-------------|--------|
| #1 Auth | All routes now require `X-API-Key` | **Breaking** — add key to all API calls |
| #2 Webhook token | `?token=` required in JotForm URL | **Breaking** — update JotForm webhook URL |
| #3 Field map YAML | Field IDs now in `config/field_maps/arnona.yaml` | Additive |
| #4 Conditional logic | `parse_fields()` now returns section-keyed dict | Internal — no external interface change |
| #5 Sheets background | Sheets sync moved to background task | Non-breaking |
| #6 Document download | Files downloaded on receipt to `data/documents/` | Additive |
| #7 Idempotency | Duplicate webhooks return cached result | Non-breaking |
| #8 Dead code | 5 dead directories deleted, 3 stubs removed | Internal |

---

## Pre-Migration Checklist

Before deploying v0.6.0 to production:

- [ ] Back up `data/` directory (contains client PII)
- [ ] Back up current `.env`
- [ ] Note your current JotForm webhook URL
- [ ] Confirm the server is not receiving active webhooks during migration

---

## Step 1 — Update `.env`

Add two new required variables to `.env`:

```bash
# Protect all operator routes (review, admin, submissions, discover)
# Generate: python -c "import secrets; print(secrets.token_hex(32))"
OPERATOR_API_KEY=<generate-a-strong-random-key>

# Verify JotForm webhooks — shared secret added to webhook URL
# Generate: python -c "import secrets; print(secrets.token_urlsafe(32))"
WEBHOOK_SECRET=<generate-a-strong-random-key>

# Document storage directory (new in v0.6)
DOCUMENTS_DIR=data/documents
```

**Do not commit `.env` to git.** It is in `.gitignore`.

---

## Step 2 — Update JotForm Webhook URL

In JotForm:
1. Open form **251955479892982** (העברת חשבון ארנונה)
2. Settings → Integrations → Webhook
3. Change the URL from:
   ```
   https://yourserver.com/webhook
   ```
   To:
   ```
   https://yourserver.com/webhook?token=<YOUR_WEBHOOK_SECRET>
   ```
   (Use the exact value of `WEBHOOK_SECRET` from your `.env`)

4. Save. JotForm will now send `?token=...` with every webhook call.

**If you skip this step:** all JotForm webhooks will return `401 Unauthorized` and no submissions will be processed.

---

## Step 3 — Deploy New Code

```bash
git pull origin main      # or however you deploy
pip install -r requirements.txt   # no new packages in v0.6
```

Verify the app starts cleanly:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Expected startup log:

```
Starting JotForm Webhook Receiver v0.6.0
Submissions  : .../data/submissions
Processed    : .../data/processed
Review queue : .../data/review_queue
Documents    : .../data/documents           ← new in v0.6
SECURITY WARNING: OPERATOR_API_KEY not set  ← until you set the key
```

---

## Step 4 — Update All API Callers

Any script, cURL command, or tool that calls the API must now include the API key:

**Option A — Header:**
```bash
curl -H "X-API-Key: <YOUR_OPERATOR_API_KEY>" https://yourserver.com/review
```

**Option B — Bearer token:**
```bash
curl -H "Authorization: Bearer <YOUR_OPERATOR_API_KEY>" https://yourserver.com/review
```

**Routes that now require auth (were public in v0.5):**

| Route | v0.5 | v0.6 |
|-------|------|------|
| `GET /review` | Public | Auth required |
| `GET /review/{id}` | Public | Auth required |
| `POST /review/{id}/approve` | Public | Auth required |
| `GET /submissions` | Public | Auth required |
| `GET /discover/{id}` | Public | Auth required |
| `GET /admin/*` | Public | Auth required |
| `GET /` | Public | **Still public** |
| `GET /health` | Public | **Still public** |

---

## Step 5 — Verify Field Map (Optional But Recommended)

After deployment, check the field map status:

```bash
curl -H "X-API-Key: <key>" https://yourserver.com/admin/fieldmap/arnona/status
```

Expected response (before real IDs are confirmed):
```json
{
  "status": "placeholder_ids_present",
  "total_fields": 51,
  "verified": 0,
  "unverified": 51,
  "action_needed": "51 field ID(s) are still placeholders..."
}
```

To verify real field IDs:
1. Submit one test form
2. `GET /discover/{submission_id}` — see all raw field IDs
3. Match IDs to labels in `config/field_maps/arnona.yaml`
4. Set `verified: true` for each confirmed field
5. Restart server
6. Repeat `GET /admin/fieldmap/arnona/status` until `"status": "ok"`

---

## Step 6 — Verify Documents Directory

The new `data/documents/` directory is created automatically on startup.
After the first webhook, verify:

```
data/documents/
  {submission_id}/
    תעודת_זהות.jpg
    חוזה_שכירות.pdf
    _manifest.json
```

---

## Step 7 — Smoke Test

Run this sequence to confirm everything works end-to-end:

```bash
# 1. Health check (no auth)
curl https://yourserver.com/health
# → {"status": "healthy"}

# 2. Submit a test webhook
curl -X POST "https://yourserver.com/webhook?token=<WEBHOOK_SECRET>" \
  -F "formID=251955479892982" \
  -F "submissionID=test-001" \
  -F "rawRequest={\"formID\":\"251955479892982\",\"submissionID\":\"test-001\"}"
# → {"status": "received", "idempotent_replay": false}

# 3. Submit the same webhook again (idempotency)
# (same curl command)
# → {"status": "received", "idempotent_replay": true, "X-Idempotent-Replay: true"}

# 4. Check review queue
curl -H "X-API-Key: <OPERATOR_API_KEY>" https://yourserver.com/review
# → {"count": 1, "items": [...]}

# 5. Verify no auth → 401
curl https://yourserver.com/review
# → {"detail": "Authentication required..."}

# 6. Verify wrong webhook token → 401
curl -X POST "https://yourserver.com/webhook?token=wrongtoken" ...
# → {"detail": "Invalid webhook token."}
```

---

## Rollback Plan

v0.6 is backward-compatible at the data layer — all `data/` files use the same JSON format. If you need to roll back to v0.5.0:

1. `git checkout v0.5.0`
2. Remove `OPERATOR_API_KEY` and `WEBHOOK_SECRET` from `.env` (or leave them — v0.5 ignores them)
3. Change JotForm webhook URL back to `https://yourserver.com/webhook` (no token)
4. Restart

Data files written by v0.6 are fully readable by v0.5.

---

## Post-Migration Monitoring

Watch logs for:

```
SECURITY WARNING: OPERATOR_API_KEY not set   ← .env not loaded
SECURITY WARNING: WEBHOOK_SECRET not set     ← .env not loaded
IDEMPOTENT replay: submission xxx            ← normal JotForm retry
Document download error (non-fatal): ...     ← JotForm file download failed
Sheets background sync error: ...            ← Google Sheets creds issue
```
