# Integration TODOs — blocked on `.env` recovery / external services

Everything in this file requires API keys, the production server, or live
JotForm data. The v0.7 architecture is complete without them; once the `.env`
is recovered, ONLY the items below plus integration testing remain.

## 1. Recover secrets (from the EC2 server's `.env` — do not regenerate)

| Variable | Why recovery matters |
|---|---|
| `WEBHOOK_SECRET` | Baked into the JotForm webhook URL — regenerating without updating the form silently kills all submissions |
| `OPERATOR_API_KEY` | Operator dashboard/API login |
| `GEMINI_API_KEY` | Primary vision classifier; without it classification degrades to filename matching |
| `JOTFORM_API_KEY` (have) | Startup form-schema sync → enables the REAL conditional evaluator; document downloads |
| `OPENAI_API_KEY` (have) | Vision classifier fallback |

## 2. Field-map verification (needs JOTFORM_API_KEY + a real submission)

See `docs/UNRESOLVED_MAPPINGS.md`. Priority order:
1. Partner email QID (`q105_email105` guess) and the missing partner-phone QID
   for the "מתחיל שכירות" flow — production bug #2.
2. Couple answer value for `q209_input209` ("זוג נשוי" was never observed live;
   the v0.7 classifier tolerates variants and corroborates, but confirm).
3. Supplemental-services QID(s) — map with label `שירותים_נוספים` (the
   `_unmapped` scan in `supplemental_services.py` is a stopgap).
4. The 5 remaining numeric guesses (transfer date, floor, entrance,
   Ramat-Gan account numbers, water property number).
5. FHS computed-column QIDs (17 quarantined entries) — optional; raw sections
   cover them.

## 3. Conditional-engine schema cache (needs JOTFORM_API_KEY)

`config/forms/{250201745267957}.json` is gitignored and populated by startup
sync. Verify on the server that the log shows `JotForm sync: N/N forms up to
date` and that submissions log `JotFormConditionEvaluator` rather than
`falling back to legacy engine`. Until then the 8-rule legacy engine decides
visibility.

## 4. Server-side migration (needs EC2 access)

After deploying v0.7, re-run detection over the existing review queue so
historical records get the corrected requirements:

    python scripts/backfill_detection.py dryrun   # inspect
    python scripts/backfill_detection.py apply    # backs up first

(The script rewrites detection-only fields; approvals/status preserved.
It hardcodes `/home/ubuntu/app` + `/var/data` — server only.)

## 5. Known non-blocking stubs (unchanged in v0.7)

- `lease_analyzer._ai_extract` — NotImplementedError, reachable only when
  `ENABLE_DOCUMENT_JOBS=true` AND `OPENAI_API_KEY` set. Implement or guard
  before enabling document jobs.
- `extractor.py` ID-photo / arnona-bill OCR — returns MOCK, flagged for
  manual review by design.
- Water/electricity services — clean stubs, unregistered
  (`orchestrator.py` `_PYTHON_SERVICES`), YAML configs are placeholders.

## 6. Deployment doc mismatch

`DEPLOYMENT.md` / `render.yaml` describe Render; the production server is EC2
(`/home/ubuntu/app`, `/var/data`). Rewrite the deployment guide after
confirming the server layout during `.env` recovery.
