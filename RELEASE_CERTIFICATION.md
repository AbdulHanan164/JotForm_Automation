# RELEASE CERTIFICATION — v0.7 (`architecture-refactor` @ e0cd30a)

Date: 2026-07-20 · Target: EC2 Ubuntu, `/home/ubuntu/app`, data in `/var/data`
Certifying scope: everything from architecture through deployment readiness.
Every claim below was verified in this audit — nothing is carried on trust.

---

## 1. Architecture Status — ✅ VERIFIED

- Single source of truth confirmed by code inspection and grep: one requirement
  engine (`app/rules/requirements.py`), one transaction classifier + role
  router (`app/rules/transaction.py`), one document vocabulary
  (`app/core/doc_types.py`), one manifest lookup (`storage.manifest_status`).
  The duplicate engines (`arnona/rules.py`, mapper-local detection,
  `REQUIRED_DOCS`) are deleted; `missing_detector.py` is a re-export shim kept
  for the server backfill scripts.
- Layering verified: `app/core` imports nothing from the app; `app/rules`
  imports only core + models; no upward imports.
- **v0.7 does NOT touch**: `main.py`, webhook route, orchestrator, evaluator,
  schema loader/sync, config.py, auth — verified via
  `git diff master..architecture-refactor` (empty for all of them).
  Startup and routing behavior after deploy is therefore identical to today's.

## 2. Business Logic Status — ✅ VERIFIED against production data

Replayed all **58 production submissions** (2026-06-14 → 2026-07-19) from the
server backup through the new pipeline; diffed against the outputs the server
actually stored. Full detail: `validation_report.md`.

- 30 transaction-type changes — every one traced to form evidence
  (couples/roommates recovered from the real `q193_moveType` answer; legacy
  records pre-dating detection now classified). **0 unexplained.**
- Corpus-wide invariant sweep: **0 violations** — terminations never demand
  incoming-tenant data; sale/owner flows never demand landlord phone or the
  wrong contract; company overrides hold; hidden fields never demanded.
- End-to-end smoke test (this audit): booted the app against a copy of
  production data and re-posted **yesterday's live webhook** — HTTP 200 in
  3.7 s, classified `rental_start_couple` (production had said "single"),
  address-update purchase detected from the mapped q568 field, full summary,
  draft email, dashboard detail renders. Idempotency guard verified
  (replaying an already-processed ID returns the cached result).

## 3. Document Engine Status — ✅ VERIFIED

- No-downgrade invariant proven at 3 layers (manifest write guard, strongest-
  status read, review-update ✅-preservation) + corpus sweep: 0 downgrades.
- All 58 production manifests are the OLD downloader format (`files:{}`).
  v0.7 reads them without error and fabricates no presence.
- Replay proved production was re-requesting id_photo/signature files the
  customer had already sent (files exist on disk, old parse said absent) —
  21 phantom demands eliminated.
- Alias + needs_review behavior covered by the deterministic test suite.

## 4. Replay Validation — ✅ 58/58, one bug found & fixed

The replay caught a real bug the refactor would have shipped: supplemental
services detected on 58/58 submissions from static JotForm widget text.
Fixed (map q568/q569/q630, drop `_unmapped` scan, negation guard), regression-
tested, re-validated: detections now 12/58 = exact ground truth
(**0 FP / 0 FN**). This is commit e0cd30a.

## 5. Regression Tests — ✅

- **339 passed, 10 skipped** on Python 3.11 (dev venv) **and Python 3.13**
  (fresh venv with the exact pinned production requirements).
- Server runs Python **3.14.4** — not locally testable; risk assessed LOW
  (no 3.14-removed APIs used; deps are the same pinned versions already
  running on the server). Post-deploy smoke test covers the residue.
- Baseline before refactor: 232 passed, **2 failed** — both pre-existing
  failures are fixed.

## 6. Security Review — ⚠️ one action required (not code)

- No hardcoded credentials in tracked files (scanned for token/key patterns).
- `.gitignore` covers `.env`, `.env.*`, `data/`, `config/forms/`, venvs.
- Auth model unchanged (operator key + webhook token); reject endpoint removed
  intentionally (Phase 12C).
- **ACTION REQUIRED:** a GitHub classic PAT was pasted into chat and stored in
  the local worktree git config (`branch.architecture-refactor.remote`) during
  the push. **Revoke/rotate it at github.com/settings/tokens** and run
  `git config --unset branch.architecture-refactor.remote`. Unrelated to the
  server deployment; do it regardless.

## 7. Deployment Readiness — ✅ VERIFIED from the server backup

| Item | Finding |
|---|---|
| Production `.env` | **Recovered** in backup (`/home/ubuntu/app/.env`, identical to `.env.backup`). 10 keys: OPERATOR_API_KEY, WEBHOOK_SECRET, JOTFORM_API_KEY, 6 data-dir overrides → `/var/data/*`, ENABLE_DOCUMENT_JOBS=false. |
| `.env` compatibility | All 10 keys map 1:1 to `app/config.py` fields — **no changes needed, no new variables required**. v0.7 adds no config keys. AI keys (GEMINI/OPENAI) absent → AI classifiers inert, exactly as today. |
| Deployed code vs git | Server code == `master` **exactly** (byte-diffed every .py/.yaml) — zero uncommitted hotfixes to preserve. |
| Requirements | Server `requirements.txt` byte-identical to branch (EOL only). No new dependencies in v0.7 → **no pip install needed**. |
| Python / venv | Server: CPython 3.14.4 venv at `/home/ubuntu/app/venv`. Suite passes on 3.13 locally. |
| Data | All data lives OUTSIDE the repo (`/var/data`) — `git` operations cannot touch it. Deploy performs **zero data migrations**; review items are only rewritten by the optional post-deploy backfill (which backs up first). |
| Visibility engine | Live logs (2026-07-19) show the active form runs the legacy engine (schema cache never populated for it). v0.7 doesn't touch sync/evaluator → **same engine after deploy**. |
| Webhook / domain / URLs | v0.7 changes no route paths (diffed), no port, no server process, no nginx/domain config, and `.env` (with WEBHOOK_SECRET baked into the JotForm webhook URL) is untouched → **Alexander's URLs, webhook, and login continue unchanged**. |
| DEPLOYMENT.md | STALE (describes Render, not EC2). Superseded by the checklist below; rewrite post-release. |

## 8. Production Risks (all LOW, none blocking)

1. Python 3.14 not locally testable — mitigated by import/compile smoke test in
   the checklist before restart.
2. Historical review items keep pre-v0.7 requirements until
   `backfill_detection.py apply` runs (deliberate; dry-run first).
3. First live seller-flow submission should be eyeballed (buyer-email
   requirement — 1 corpus occurrence, section genuinely empty).
4. Manifest read-modify-write has no lock (pre-existing; webhook flow makes
   collisions rare).
5. The systemd/nginx layer was NOT in the backup (backup covered `/home` and
   `/var/data` only) — the checklist discovers and records it before touching
   anything.

## 9. Known Limitations

- Visibility for the active form uses the legacy 8-rule engine until the form
  schema is synced (unchanged from today; run `POST /admin/sync/250201745267957`
  when desired — treat as its own change, not part of this release).
- OCR extraction is MOCK by design; document jobs disabled by `.env`.
- 5 plausible-but-unverified field IDs + 17 quarantined fabricated IDs
  documented in `docs/UNRESOLVED_MAPPINGS.md`.

## 10. Future Improvements (non-blocking)

Map `q193_moveType` first-class; tighten `internet_tv` tokens; file-lock the
manifest merge; rewrite DEPLOYMENT.md for EC2; move `Q.save` before the email
redraft in `update_review_item_after_merge`.

---

## 11. Deployment Checklist (execute in order; verify each step)

> Total downtime target: < 10 seconds (one service restart). No data is
> migrated; rollback is a git checkout + restart.

**0. Preconditions (local)** — branch pushed (e0cd30a), 339 tests green. ✅ done.

**1. Snapshot the server** (SSH as ubuntu):
```bash
sudo tar -czf ~/pre_v07_backup_$(date +%Y%m%d_%H%M).tar.gz /home/ubuntu/app /var/data --exclude=/home/ubuntu/app/venv
ls -lh ~/pre_v07_backup_*.tar.gz            # verify size > 1 MB
cp /home/ubuntu/app/.env ~/.env.pre_v07     # belt-and-braces copy of .env
```

**2. Record current state (for rollback + service discovery):**
```bash
cd /home/ubuntu/app && git rev-parse HEAD > ~/pre_v07_commit.txt && cat ~/pre_v07_commit.txt
systemctl list-units --type=service | grep -Ei "uvicorn|gunicorn|jotform|webhook|app" || true
ps aux | grep -E "uvicorn|gunicorn" | grep -v grep        # note EXACT run command, port, user
sudo nginx -T 2>/dev/null | grep -E "server_name|proxy_pass" | head   # note domain + upstream port
curl -s http://127.0.0.1:<PORT>/health                    # baseline health
```
**STOP if** the run command/port can't be identified — report back before proceeding.

**3. Fetch the release (no service impact yet):**
```bash
cd /home/ubuntu/app
git status                     # MUST be clean except .env/data (untracked-ignored)
git fetch origin
git log --oneline origin/architecture-refactor -3   # expect e0cd30a on top
```

**4. Pre-flight compile + import check on the SERVER's Python 3.14 (still no impact):**
```bash
git checkout architecture-refactor
venv/bin/python -m compileall -q app && echo COMPILE-OK
venv/bin/python -c "import app.main; print('IMPORT-OK')"
venv/bin/python -m pytest -q 2>&1 | tail -1          # expect 339 passed
```
**STOP if** any of the three fails → run rollback (§12) — service is still running old code, zero impact so far.

**5. Restart the service (the only downtime moment):**
```bash
sudo systemctl restart <SERVICE_NAME>       # from step 2 (or the recorded run method)
sleep 3 && systemctl status <SERVICE_NAME> --no-pager | head -5
```

**6. Health checks:**
```bash
curl -s http://127.0.0.1:<PORT>/health                        # {"status":"healthy"}
curl -s http://127.0.0.1:<PORT>/ | head -c 200                # version + review_queue=/var/data/review_queue
tail -20 /var/data/logs/webhook.log                           # startup lines, no tracebacks
curl -s -o /dev/null -w "%{http_code}\n" https://<DOMAIN>/dashboard/login   # 200 via nginx+SSL
```

**7. Smoke tests (production URL, as Alexander):**
- Log into the dashboard with the existing operator key — list renders, open any historical item — displays exactly as before (historical items intentionally unchanged).
- `curl -s -o /dev/null -w "%{http_code}" -X POST https://<DOMAIN>/webhook` → 401/403 (token required) — webhook URL alive and protected.
- Wait for (or submit) one real form submission; verify log shows the pipeline complete and the review item appears with a v0.7 transaction type.

**8. (Recommended, separate step) Backfill historical review items:**
```bash
cd /home/ubuntu/app && venv/bin/python scripts/backfill_detection.py dryrun   # inspect the delta
venv/bin/python scripts/backfill_detection.py apply                            # backs up queue first
```

**9. Post-deploy:** merge `architecture-refactor` → `master` on GitHub (the deployed commit becomes master), delete stale worktree branches, rotate the exposed PAT (§6).

## 12. Rollback Checklist (< 1 minute, no data restore needed)

```bash
cd /home/ubuntu/app
git checkout $(cat ~/pre_v07_commit.txt)
sudo systemctl restart <SERVICE_NAME>
curl -s http://127.0.0.1:<PORT>/health
```
Data needs NO restore (deploy writes nothing to /var/data). If step 8's apply
ran and must be undone, restore the queue backup it created
(`/var/data/review_queue_backup_<timestamp>/`) over `/var/data/review_queue/`.
Full-disaster restore: the step-1 tarball.

---

# ✅ APPROVED FOR PRODUCTION

**Why it is safe:**
1. The deployed server code is byte-identical to `master` — the release is a
   clean fast-forward with no hotfixes to lose.
2. The recovered production `.env` works with v0.7 unchanged — verified
   key-by-key against config; no new variables, no renames.
3. All 58 real production submissions replay through the new code with zero
   failures and zero unexplained differences; yesterday's live webhook was
   re-run end-to-end on the branch and produced a strictly-better result.
4. No route, port, domain, webhook URL, auth, or startup behavior changes —
   verified by diff, not assumption. Alexander's experience is unchanged
   except for corrected classifications on NEW submissions.
5. Deployment touches no data; rollback is a 1-minute git checkout.
