# Production Validation Report — v0.7 (`architecture-refactor`)

Date: 2026-07-19 · Validator: historical replay over the 2026-07 EC2 server backup
Method: every stored production submission replayed through the refactored
pipeline (parse → business model → transaction classification → summary →
missing detection → supplemental services), diffed against the outputs the
production server actually stored (`_business`, `_missing`, `_summary` inside
each `*_raw.json`). Production data was copied to a sandbox and never modified;
all replay writes went to `validation_sandbox/replay_out/`.

## 1. Replay totals

| Metric | Value |
|---|---|
| Production submissions on disk | **58** (2026-06-14 → 2026-07-19, form 250201745267957) |
| Successfully replayed | **58 / 58** (0 failures, 0 engine errors) |
| Replay wall-clock | 1.3–2.7 s total (~25–45 ms per submission, includes manifest I/O) |
| Review-queue items examined | 57 · Document manifests examined | 58 · Downloaded files | 20 |
| Test suite | **339 passed, 10 skipped** (baseline before refactor: 232 passed, 2 failed) |

## 2. Transaction breakdown (replayed, v0.7 engine)

| Type | n | | Type | n |
|---|---|---|---|---|
| rental_start_single | 16 | | rental_termination_couple | 4 |
| rental_start_couple | 12 | | rental_termination_roommates | 2 |
| rental_start_roommates | 4 | | landlord_rental_single/couple/roommates | 1+1+1 |
| rental_start_company | 1 | | sale_purchase | 5 |
| rental_termination_single | 6 | | sale_transfer | 2 |
| owner_return | 3 | | | |

30 of 58 classifications changed vs. stored production values. **Every change
was traced to form evidence** (see §4); none is unexplained.

## 3. Differences vs. production outputs

| Category | Count | Classification |
|---|---|---|
| Transaction type changed | 30 | 13 EXPECTED IMPROVEMENT (legacy `rental_transfer` records predating detection, now classified from raw answers) + 17 EXPECTED BUG FIX (see §4) |
| Missing-info diffs | 25 submissions | all EXPECTED BUG FIX / EXPECTED IMPROVEMENT (§5) |
| Missing-docs diffs | 23 submissions | all EXPECTED BUG FIX (§6) |
| Supplemental services | 12 detections | EXPECTED IMPROVEMENT — new capability, validated to ground truth (§7) |
| POSSIBLE REGRESSION | **1 found and FIXED during validation** (§7) |
| UNKNOWN | **0** — every diff was root-caused |

## 4. Transaction detection (Phase 6) — all invariants hold

- **Married couples**: 14 submissions carried the marital answer ONLY in the
  unmapped composite field `q193_moveType` ("…, זוג נשוי, ") — production had
  classified **all of them single**. v0.7 recovers the real answer. Verified:
  every unmapped-scan hit across the corpus was `q193_moveType` (a structured
  answer field) — **zero free-text false positives**.
- **Roommates**: 8 recovered the same way (`שותפים` in q193 or explicit field).
- **Company**: the 1 company submission correctly overrides individual rules
  (no personal-ID / id-photo demands; corp_cert + tabu demanded).
- **Termination** (12): **zero** incoming-tenant demands (production demanded
  name/phone/email/ID on all of them). Move-out satisfied via
  תאריך_סיום_חוזה where present — verified field-level on 3 samples.
- **Purchase (5) / Sale (2) / Owner-return (3)**: sale_contract replaces the
  lease demand; owner_return demands tabu and no contract; no landlord-phone
  demands on owner/sale flows. 0 violations across the corpus.

## 5. Missing information (Phase 5) — corpus sweep results

Removed vs. production (all traced): incoming-tenant items on terminations
(×10 each), move_in_date on non-move-in flows (×12), owner_phone on owner/sale
flows (×7), arnona numbers where ארנונה was not among the selected services
(×2–3), partner_id where pre-v0.7 mapping mis-detected a partner (×4).
Added vs. production (all justified): partner_name/partner_id (×6) on
couple/roommate flows whose partner details are genuinely absent;
customer_email/name/phone/id (×1–3) on seller/landlord flows where the
buyer/tenant section is genuinely empty. Hidden-field check: no flagged item
had `was_field_visible == False` under the stored production visibility.

## 6. Document engine (Phase 4)

- **No supplied document regresses to missing** — sweep of all 58 old→new doc
  status maps: 0 downgrades (✅ stayed ✅).
- **11× id_photo and 10× signature demands DROPPED**: the customer had
  uploaded (the downloaded `תעודת_זהות.jpeg` files exist in the server backup)
  but old parses stored `present: false` (pending-submissions handling).
  Production was re-asking customers for files it already had. Fixed.
- **8× arnona_bill demands dropped** where ארנונה was not a selected service.
- **Old manifests resolve safely**: all 58 production manifests are the old
  downloader format (`files: {}`, no `documents` key). v0.7 reads them without
  error and fabricates no presence. Alias/needs_review behavior is covered by
  the 339-test suite (no production manifest has reconciliation entries yet —
  that feature shipped after this data window).

## 7. Supplemental services (Phase 7) — bug found by replay, fixed, re-validated

**The replay caught a real bug in the refactor.** The parser's `_unmapped`
scan detected `address_update` on **58/58** submissions: JotForm posts static
text-widget content (price labels q620/q626/q491, byte-identical in every
submission) with every webhook. Worse, the REAL answer field
(`q568_input568`, a multi-select list) never reached `_unmapped` (str-only
filter), and decline answers ("לא תודה - עדכון כתובת…") would have counted as
purchases.

**Fix applied** (commit on this branch):
1. Mapped the three verified ancillary-services QIDs (q568/q569/q630 →
   `שירותים_נוספים`, validated against all 58 submissions) in `arnona.yaml`.
2. Removed the `_unmapped` scan from supplemental detection (kept for
   transaction detection, where it was validated clean — q193 only).
3. Added a word-boundary-aware negation guard ("לא תודה"/"ללא"/"אין" as whole
   words, so "אינטרנט" still detects).
4. Added 6 regression tests reproducing the exact production shapes.

**Re-validation**: detections = 12/58, matching the independently-derived
ground truth (raw q568 answers) with **0 false positives, 0 false negatives**.
20 explicit declines correctly ignored. No duplicates; serialization
round-trips verified in tests.

## 8. Production safety scan (Phase 8)

- `TODO/FIXME`: 6 occurrences — 2 are quarantine *markers* by design
  (placeholder-ID detection), 1 generated-code comment, 3 documented
  integration TODOs. None hides broken logic.
- Bare `except:`: 5 (pre-existing; utils/downloader paths).
- `except Exception`: 68 total; ~8 are silent (`pass`) — notably
  [models.py:232](app/mappers/models.py:232) (manifest lookup fallback — intentional,
  returns ❌), downloader HEAD-check fallbacks, evaluator rawRequest decode.
  All pre-existing patterns; v0.7 *removed* the worst one (silent divergent
  rules fallback → loud `engine_error`).
- Race condition (pre-existing, documented): `download_and_merge_files` does a
  read-modify-write of `_manifest.json` without a lock; concurrent merges for
  the same submission could lose an update. Writes themselves are atomic
  (tempfile + `os.replace`).
- File writes: all manifest/queue writes go through atomic write helpers. ✓
- Unsafe assumption noted: `field_map._YAML_CONFIG` is CWD-relative
  (pre-existing v0.6 behavior; server systemd unit sets the correct CWD).

## 9. Failures

**None.** 58/58 replays completed; no submission raised; no engine_error was
returned; the summary builder never fell back to the legacy path.

## 10. Verdict

# ✅ SAFE TO MERGE

**Why:**
1. **Zero unexplained differences** — all 30 transaction changes, 25 info
   diffs and 23 doc diffs were root-caused to form evidence, and every one
   moves output toward the documented-correct answer (couples recovered from
   q193, terminations freed of incoming demands, already-uploaded documents no
   longer re-requested).
2. **Zero invariant violations** across the corpus: no supplied document
   regresses, no incoming demands on terminations, no landlord demands on
   owner flows, company overrides hold, hidden fields are never demanded.
3. **The one regression the refactor would have shipped** (supplemental
   false positives on every submission) **was caught by this replay, fixed,
   regression-tested, and re-validated to exact ground truth** — which is
   precisely what this validation exists to do.
4. 339 deterministic tests pass; replay is fast (~30 ms/submission) and
   requires no external APIs.

**Follow-ups (non-blocking):**
- Map `q193_moveType` as a first-class field (today it is recovered via the
  validated unmapped scan; a direct mapping is cleaner).
- After deploying, run `scripts/backfill_detection.py dryrun` on the server so
  the 57 existing review items get the corrected requirements; eyeball the
  delta before `apply`.
- Verify the buyer-email requirement on the seller flow with the next live
  seller submission (1 occurrence in corpus; genuinely-empty section today).
- Add a file lock around the manifest read-modify-write (pre-existing).
- Rotate the GitHub token that was exposed during the push and remove it from
  `branch.architecture-refactor.remote` git config.
