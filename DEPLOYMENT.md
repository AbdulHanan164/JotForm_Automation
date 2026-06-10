# Deployment Guide — Render

מה זה קל JotForm Webhook · v0.8.2

---

## What gets deployed

A single FastAPI web service:

```
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

- Health check: `GET /health` (public, no auth)
- Webhook: `POST /webhook?token=<WEBHOOK_SECRET>`
- Operator API: `GET /review` etc. — requires `X-API-Key: <OPERATOR_API_KEY>`
- All state is JSON files under the data directories — **a persistent disk is
  mandatory** (the review queue must survive deploys and restarts).
- No Procfile needed — Render uses the start command from `render.yaml`
  (Procfile is a Heroku concept).

---

## 1. GitHub setup

The repo already lives at `https://github.com/AbdulHanan164/JotForm_Automation`.

Verify before connecting Render:

1. `master` is the deploy branch (render.yaml has `autoDeploy: true` — every
   push to master deploys).
2. **No secrets or PII are committed**: `.env`, `data/`, `logs/` are
   git-ignored. `.env.example` documents every variable.
3. `requirements.txt`, `render.yaml` are at the repo root.

---

## 2. Render setup

1. Sign in at https://render.com (sign in with GitHub).
2. **New → Blueprint** → select the `JotForm_Automation` repo.
3. Render reads `render.yaml` and proposes:
   - Web service **mazekal-webhook** (Python, Starter plan)
   - Persistent disk **mazekal-data**, 1 GB, mounted at `/var/data`
4. When prompted for the `sync: false` environment variables, paste the
   secrets (see §3).
5. Click **Apply**. First build takes 2–3 minutes.
6. Verify: open `https://mazekal-webhook.onrender.com/health` →
   `{"status": "healthy"}`.
7. Check the logs for the startup banner — it prints the resolved data
   directories (must all be under `/var/data/`) and
   `Field map: 44/79 ...` (expected — 35 placeholders are documented).

> **Why the Starter plan:** Render disks are not available on the free tier,
> and the free tier spins down after idle (JotForm webhooks would hit a cold
> start or be dropped). The review queue lives on the disk — without it,
> every deploy wipes pending reviews.

---

## 3. Environment variables

Set in Render → mazekal-webhook → Environment:

| Variable | Required | Value |
|---|---|---|
| `OPERATOR_API_KEY` | **Yes** | `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `WEBHOOK_SECRET` | **Yes** | same generator — goes into the JotForm webhook URL |
| `JOTFORM_API_KEY` | Optional | JotForm → Account → API. Enables form-definition sync at startup |
| `PYTHON_VERSION` | Set by render.yaml | `3.13.4` (dev parity: `3.14.0` if available on Render) |
| `SUBMISSIONS_DIR` … `LOGS_DIR` | Set by render.yaml | `/var/data/...` — do not change |
| `GOOGLE_SHEETS_CREDENTIALS_PATH` | Optional | Upload credentials JSON as a Render **Secret File**, then set this to `/etc/secrets/<filename>` |

⚠️ If `OPERATOR_API_KEY` or `WEBHOOK_SECRET` is empty, that protection is
**disabled** (the startup log warns loudly). Never run production without both.

---

## 4. Custom domain (optional)

1. Render → mazekal-webhook → Settings → Custom Domains → Add
   (e.g. `webhook.mazekal.co.il`).
2. At the DNS provider add the record Render shows:
   `CNAME webhook → mazekal-webhook.onrender.com`
3. Render provisions TLS automatically (Let's Encrypt) — usually live within
   minutes of DNS propagating.
4. After the domain is active, use it in the JotForm webhook URL (§5).

---

## 5. JotForm webhook URL update

For the production form **250201745267957** ("NEW MAIN FORM - 3.1"):

1. JotForm → the form → **Settings → Integrations → Webhooks**.
2. Set the URL (one line, token included):

   ```
   https://mazekal-webhook.onrender.com/webhook?token=<WEBHOOK_SECRET>
   ```

   (or the custom domain once configured)
3. Remove/disable any old webhook URL pointing at a previous server.
4. **Smoke test:** submit a test entry on the form, then:
   - Render logs show `→ Service: arnona_transfer (form 250201745267957)`
   - `GET https://.../review` with header `X-API-Key: <OPERATOR_API_KEY>`
     lists the new submission.

---

## 6. Exact Render Start Command

```
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Build command: `pip install -r requirements.txt`
Health check path: `/health`

---

## Verified before shipping (v0.8.2)

- ✅ App boots through FastAPI lifespan with env-var-driven directories
- ✅ All five data directories auto-create at startup (`app/config.py`)
- ✅ Review queue writes/reads on a non-default storage path (disk simulation)
- ✅ `GET /health` → 200 without auth; `/review` → 401 without `X-API-Key`
- ✅ `POST /webhook` without `?token=` → 401
- ✅ No Windows-specific code, no absolute local paths — all `pathlib`,
  all relative or env-driven (test suite: 185 passed)

## Known limitations on Render

- **Single instance only.** The file-based review queue has no locking — do
  not scale to multiple instances ("num instances" must stay 1).
- **Disk is per-service.** Back up `/var/data` periodically (Render →
  Disks → Snapshots, or a scheduled export) — it holds client PII and the
  entire review history.
- CORS is currently `allow_origins=["*"]` (in `app/main.py`). Acceptable
  while the API is key-protected; tighten when an operator UI gets a fixed
  origin.
- Logs also stream to stdout, so Render's log viewer works even though
  `webhook.log` rotates on the disk.
