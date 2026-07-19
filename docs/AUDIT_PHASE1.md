# Phase 1 — Full Architecture Audit

Date: 2026-07-19 · Baseline commit: `ff61124` · Baseline tests: 232 passed, 2 failed, 10 skipped

This audit is the factual basis for the v0.7 consolidation refactor. Every item
below was verified by reading the code (file:line references included).

---

## 1. Duplicate implementations

### 1.1 Missing Information — TWO engines (divergent)

| Engine | Location | Status |
|---|---|---|
| Business-model detector | `app/mappers/missing_detector.py:_detect_info` (99-180) | Primary — runs whenever `parsed["_business"]` exists (effectively always) |
| Raw rules table | `app/services/arnona/rules.py:INFO_RULES` (82-210) | Fallback — only on mapper exception (`service.py:146-163`) |

Known divergences:
- Name check: `full_name` present (detector) vs first AND last (rules.py:115).
- Services matching: exact list membership `"ארנונה" in services_selected`
  (detector:167) vs substring `any(kw in s ...)` (rules.py:52). The exact-match
  version causes the two failing baseline tests and drops arnona-number
  requirements whenever the multi-select value isn't the literal string.
- rules.py has a `services_selected` required rule (102-108) the detector lacks.

### 1.2 Missing Documents — THREE sources of truth

| Source | Location | `arnona_bill` required? | Referenced by |
|---|---|---|---|
| `_detect_docs` | `missing_detector.py:202-241` | **Always** | pipeline (primary) |
| `DOC_RULES` | `rules.py:213-262` | Only if service contains "ארנונה" | fallback only |
| `REQUIRED_DOCS` | `field_map.py:152-157` | n/a (per-service table) | **NOTHING — dead config** |

### 1.3 Conditional evaluators — TWO engines with silent fallback

- `JotFormConditionEvaluator` (`app/pipeline/evaluator.py:248`) — evaluates the
  real JotForm conditions from `config/forms/{form_id}.json`. Dead on any fresh
  clone (cache is gitignored; populated only by startup sync with JOTFORM_API_KEY).
- `arnona_logic_engine` (`app/services/arnona/conditional_logic.py`) — 8
  hand-transcribed rules. This is what actually runs when the schema cache is
  absent; the orchestrator falls back silently (`orchestrator.py:188-207`).
- **The fallback result is then partially discarded**: `_detect_info` checks
  visibility under composite labels ("טלפון (בעל הבית)", "תעודת_זהות (שוכר שני)")
  that never appear in either engine's visibility dict (`missing_detector.py:125,140,159`)
  — so the visibility guard is inert for those rules.

### 1.4 Transaction routing — SAME branching encoded twice

`business_mapper.py` encodes the move-type/landlord-role branch twice:
`_detect_transaction_type` (71-123) and the role re-assignment block (190-229).
They can drift independently.

### 1.5 Summary builders — TWO

`BusinessSubmission.to_summary_dict()` (primary, `models.py:349`) vs
`app/services/arnona/summary.py:build` (fallback at `service.py:123`).

### 1.6 Transaction-type label tables — TWO

`app/routes/dashboard.py` `_T["he"]["txn_type"]` (100-118) and
`_T["en"]["txn_type"]` (160-178) duplicate the full 17-entry code list; the
codes themselves live implicitly in `business_mapper.py`. No single registry.

### 1.7 Manifest doc-status lookup — THREE copies

1. `missing_detector.is_doc_resolved_in_manifest` (183-197)
2. `models.py Documents._doc_present` manifest branch (216-226)
3. `reconciliation_merge.update_review_item_after_merge` manifest loop (839-864)

Copy #2 is **broken**: it calls `json.loads` but `models.py` never imports
`json`; the `except Exception: pass` swallows the `NameError`, so the operator
summary NEVER reflects reconciled documents.

## 2. Inconsistent document vocabulary

- Canonical consumer set: 6 types — `storage.DOC_TYPES` (`storage.py:37-44`):
  `id_photo, lease_contract, signature, arnona_bill, corp_cert, tabu`.
- Classifier producer set: 13 types (`reconciliation_merge.py` `_RULES` /
  `_VALID_TYPES`): adds `sale_contract, water_bill, water_meter,
  electricity_bill, electricity_meter, gas_bill, gas_meter, tabu_document`.
- Manifest is keyed by whatever the classifier returned. Consumers
  (`is_doc_resolved_in_manifest`, `update_review_item_after_merge:848`)
  look up only the 6 canonical keys → `tabu_document`/`sale_contract` uploads
  are **never recognized as satisfying a requirement** → re-requested forever.

## 3. Placeholder mappings (`config/field_maps/arnona.yaml`)

24 entries with `verified: false`:
- 7 plausible numeric guesses: `q9_transferDate9, q105_email105 (partner email!),
  q53_floor53, q54_entrance54, q63_arnonaTenant63, q64_arnonaCustomer64,
  q70_waterProperty70`.
- 17 fabricated IDs (`fhs_*_placeholder`) that can never match a webhook field.
  They also leak into `build_label_visibility` as always-visible passive QIDs.

Notable verified-but-single-sample: `q209_input209` ("שותפים") — only the value
`"שותפים"` was ever observed; the couple value `"זוג נשוי"` in
`_detect_transaction_type` is a guess. Partner email has NO verified mapping;
partner phone (`q213`) verified only for the "בעל בית" flow — root causes of
the couple-misclassification and missing-partner-contact bugs.

## 4. Dead code / unused files

- `field_map.REQUIRED_DOCS` (152-157) — referenced by nothing.
- `field_map._PYTHON_DEFAULTS` (111) — permanently empty dict merged into FIELD_MAP.
- `app/db/__init__.py` — 0-byte reserved namespace.
- `scratch/` — ~30 one-off phase-evidence scripts (some call live AI APIs); not
  part of app or tests.
- `test_comprehensive.py` (repo root) — excluded by `pytest.ini testpaths=tests`.
- `nvidia_api_key`, `hubspot_api_key`, `google_drive_credentials_path` in
  `config.py` — no consumers.
- `README.md:212-220` + `ARCHITECTURE_REVIEW_v0.5.md` describe HubSpot/Drive/AI
  stubs deleted in v0.6 — stale docs.

## 5. Placeholder implementations

- `lease_analyzer._ai_extract` (`app/documents/lease_analyzer.py:123`) —
  `NotImplementedError`, **armed by setting OPENAI_API_KEY** (line 43); every
  lease extraction then silently degrades to FAILED. (Only reachable when
  `ENABLE_DOCUMENT_JOBS=true`.)
- `extractor.py:96-118` — ID-photo / arnona-bill extraction returns MOCK.
- `app/services/water/service.py`, `electricity/service.py` +
  `config/services/{water,electricity}.yaml` — clean stubs, unregistered
  (commented out in `orchestrator.py:60-61`); loader skips placeholder form ids.

## 6. Fallback implementations (silent-degradation inventory)

| Fallback | Trigger | Risk |
|---|---|---|
| Evaluator → legacy 8-rule engine | missing `config/forms/*.json` | **Always active on fresh clone**; logged once per submission at WARNING |
| `_business` detector → rules.py | mapper exception | Divergent rule set, no operator-visible flag |
| `to_summary_dict` → `summary.build` | model reconstruction exception | Divergent summary |
| Manifest lookups → `except: pass` | any error | Broken `json` import invisible for months |
| Every pipeline stage | any exception | `logger.warning` + continue |

## 7. Confirmed defects found during this audit (beyond the earlier production audit)

1. `models.py:221` — `json` used without import → manifest status never
   reflected in summaries (silent `NameError`).
2. `reconciliation_merge.py:859-863` — a `needs_review` follow-up upload
   **downgrades an already-present document to ❌** in both `business_data`
   and the Hebrew summary.
3. `reconciliation_merge.py:966` — `entry["files"][0]["source_url"]` — key is
   never written (entries carry `local_path`) → KeyError aborts the in-memory
   merge mid-way (swallowed by orchestrator stage try/except).
4. `reconciliation_merge.py:877` — post-merge recalculation calls
   `detect_missing(bs)` with **no visibility dict**, so conditional hiding is
   ignored for recalculated items; also only `missing_docs` is updated while a
   stale `missing_info` is used for the re-drafted email.
5. `missing_detector.py:167` — exact list-membership service matching (see 1.1)
   — the direct cause of the 2 failing baseline tests.
6. Requirements not conditioned on transaction type: incoming-tenant fields are
   demanded on rental-termination submissions whose incoming section is empty
   by design (`business_mapper.py:204-208`), landlord phone demanded for
   landlord-less sale/owner flows, `lease_contract`+`arnona_bill` demanded
   unconditionally (`missing_detector.py:225-233`).

## 8. Sources of truth (current → target)

| Concern | Today | Target (v0.7) |
|---|---|---|
| Required info/docs | 3 divergent tables | `app/rules/requirements.py` (one declarative table) |
| Document types | 2 vocabularies | `app/core/doc_types.py` (canonical + aliases) |
| Transaction types + labels | mapper strings + 2 dashboard dicts | `app/core/transactions.py` |
| Field IDs | `arnona.yaml` (partially placeholder) | `arnona.yaml` + loader that quarantines fake IDs + `docs/UNRESOLVED_MAPPINGS.md` |
| Visibility | 2 engines, keys ignored downstream | evaluator (when schema cached) → legacy engine; requirements engine consumes REAL field labels |
| Manifest status | 3 lookup copies (1 broken) | `storage.manifest_status()` (alias-aware, single copy) |
