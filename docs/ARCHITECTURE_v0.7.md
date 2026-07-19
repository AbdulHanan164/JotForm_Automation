# Architecture v0.7 — Consolidated Deterministic Core

Date: 2026-07-19 · Supersedes ARCHITECTURE_v0.6.md for the subsystems below.
Companion documents: `docs/AUDIT_PHASE1.md` (what was wrong and where),
`docs/UNRESOLVED_MAPPINGS.md` (field-ID debt), `docs/INTEGRATION_TODO.md`
(work blocked on `.env` / external services).

## 1. What v0.7 is

v0.7 is a consolidation release: **no external behavior was added or removed**;
every requirement/classification decision now flows through exactly ONE
implementation, keyed on deterministic business data. The AI surface is
unchanged and confined to document *classification* (reading uploaded images);
AI never decides what is required.

```
JotForm webhook
   └─ app/routes/webhook.py
        └─ app/pipeline/orchestrator.py            (10-stage pipeline, unchanged)
             ├─ conditional visibility              evaluator.py → legacy engine fallback
             ├─ parse_fields                        config/field_maps/arnona.yaml (single mapping layer)
             ├─ business model                      app/mappers/business_mapper.py
             │    ├─ transaction type               app/rules/transaction.py          ← canonical
             │    ├─ role routing                   app/rules/transaction.py (same table)
             │    └─ supplemental services          app/mappers/supplemental_services.py
             ├─ missing info + docs                 app/rules/requirements.py          ← canonical
             │    └─ doc resolution                 app/documents/storage.manifest_status (alias-aware)
             ├─ reconciliation merge                app/pipeline/reconciliation_merge.py
             │    └─ classifier output              normalized via app/core/doc_types.canonicalize
             └─ review queue → dashboard            app/routes/dashboard.py
                                                     labels from app/core/transactions.py
```

## 2. Layer map

| Layer | Location | Depends on |
|---|---|---|
| **core** (vocabulary) | `app/core/` — `doc_types.py`, `transactions.py` | nothing |
| **rules** (engines) | `app/rules/` — `requirements.py`, `transaction.py` | core, mappers.models |
| **models** | `app/mappers/models.py` | core (indirect) |
| **mappers/parsers** | `app/mappers/` — `business_mapper.py`, `supplemental_services.py` | rules, models |
| **services** | `app/services/` — per-form adapters (arnona active; water/electricity stubs) | rules, mappers |
| **pipeline** | `app/pipeline/` — orchestrator, evaluators, reconciliation | services, rules, core |
| **routes/templates** | `app/routes/`, `app/templates/` | core (labels), review queue |
| **validators** | `app/mappers/business_validators.py`, `app/pipeline/validator.py` | models |
| **tests** | `tests/` | everything (hermetic — no network) |

Dependency rule: arrows point downward only — `app/core` imports nothing from
the app; `app/rules` imports only core + models.

**Why layers live inside `app/` instead of a top-level `core/ business/ …`
reorganization:** the deploy start command (`uvicorn app.main:app`), every
absolute import, the EC2 git-pull deployment, and the pytest configuration all
assume the `app` package root. A physical move would churn ~60 files for zero
functional gain and real production risk ("no breaking changes" constraint).
The suggested structure is realized as sub-packages: `app/core`, `app/rules`,
`app/mappers` (models+parsers), `app/services`, `app/pipeline`, `tests/`.

## 3. The rule engine (Missing Information / Missing Documents)

`app/rules/requirements.py`. Requirements are declarative tables
(`INFO_RULES`, `DOC_RULES`) evaluated against a `RequirementContext`:

    (TransactionTraits, is_company, selected services, visibility)

- **TransactionTraits** (`app/core/transactions.py`) state which roles a
  transaction has (`has_incoming`, `has_outgoing`, `has_landlord`), which
  contract proves entitlement (`lease` / `sale` / none), whether ownership
  proof is needed (`needs_tabu`), and whether a second person is implied
  (`partner_expected`). This is what stops the engine demanding an incoming
  tenant on a termination or a landlord phone on a sale.
- **Service relevance** uses substring matching, and an EMPTY services list is
  treated as arnona-relevant (conservative default for the arnona form).
- **Visibility** keys are the real form-field labels emitted by both
  conditional engines. (Pre-v0.7 the info rules consulted labels no engine
  produced, so conditional hiding never applied.)
- Output shape is unchanged: consumers (review queue JSON, email drafts,
  dashboard) require no migration.

Extension point: to require something new, add ONE `InfoRule`/`DocRule` entry
and, if it should be worded specially in customer emails, one
`_ITEM_PRESENTATION` entry in `app/services/arnona/email_templates.py`
(unknown ids fall back to a generic line).

## 4. The document engine (vocabulary + resolution)

`app/core/doc_types.py` defines:
- `CANONICAL_TYPES` — 13 types (7 requirement-bearing + 6 supplemental/utility)
- `ALIASES` — every legacy/classifier spelling → canonical
- `SATISFIED_BY` — which supplied types satisfy which requirement
  (a sale contract satisfies the contract requirement and vice versa)

Rules:
1. Manifests only ever store canonical spellings — `download_and_merge_files`
   normalizes classifier output at a single choke point.
2. Every consumer resolves presence through
   `storage.manifest_status(submission_id, requirement)` — the ONE lookup,
   alias-aware for pre-v0.7 manifests.
3. `needs_review` means "the customer supplied a file; the operator must
   verify it". It is **not re-requested** from the customer and is displayed
   as 🕓 in the operator summary (✅ = verified present, ❌ = truly absent).

## 5. The transaction engine

`app/rules/transaction.py`:
- `detect_transaction_type()` — normalized, token-based matching
  (bidi-mark/punctuation tolerant; Hebrew final forms handled), with two
  recovery layers: a scan of `_unmapped` values for marital/roommate answers,
  and corroboration from actual partner data (rental flows only — in the
  landlord flow the partner section holds the tenant).
- `role_routing()` — the single section→role table, keyed on the raw form
  answers; `business_mapper` consumes it, so classification and role
  assignment cannot drift.
- Display labels and traits live in `app/core/transactions.py`; the dashboard
  i18n tables reference them (previously duplicated in two dicts).

## 6. The mapping layer

Single source: `config/field_maps/arnona.yaml`, loaded by
`app/services/arnona/field_map.py`.
- Entries with fabricated IDs (`*placeholder*`/`HERE`/`TODO`) are
  **quarantined at load time**: never matched, never fed to the visibility
  algorithm, but fully reported via `UNRESOLVED_MAPPINGS`,
  `GET /admin/fieldmap/arnona/status`, and `docs/UNRESOLVED_MAPPINGS.md`.
- Plausible unverified numeric IDs stay active (right guess ⇒ parses; wrong
  guess ⇒ matches nothing).
- `REQUIRED_DOCS` (dead) and `_PYTHON_DEFAULTS` (empty) were removed.

## 7. Supplemental services

`app/mappers/supplemental_services.py` — registry-driven detection (address
update, mail forwarding, gas, internet/TV) over mapped fields, package
description, and `_unmapped`. Carried on
`BusinessSubmission.supplemental_services`, shown in the operator summary
(`שירותים_נוספים`) and on the dashboard detail page. Adding a service = one
`REGISTRY` entry.

## 8. Fallbacks that remain (by design) and their contracts

| Fallback | Status |
|---|---|
| Evaluator → legacy 8-rule conditional engine | KEPT — the legacy engine is the only visibility source when `config/forms/*.json` is absent (fresh clone / no JOTFORM_API_KEY). Logged per submission. |
| BusinessSubmission → raw-rules missing detection | **REMOVED** — one engine; on failure the submission is marked incomplete with `engine_error` (loud), never evaluated by a divergent rule set. |
| `to_summary_dict` → legacy `summary.build` | KEPT — exercised only if model reconstruction throws. |
| Classifier chain filename → Gemini → OpenAI → checkbox | KEPT — that's the designed cost ladder, not debt. |

## 9. Defects fixed in v0.7 (regression-locked by tests)

1. `models.py` manifest lookup crashed on a missing `json` import (silently) —
   summaries never reflected reconciled documents.
2. `needs_review` follow-up uploads downgraded present documents to ❌.
3. `reconcile_and_merge_for_original` crashed twice per match
   (`source_url` KeyError, `hebrew_label_for` NameError) — both swallowed.
4. Doc-vocabulary mismatch — supplied `tabu_document`/`sale_contract` files
   were re-requested forever.
5. Exact-match service check dropped arnona requirements
   (the 2 pre-v0.7 failing tests now pass).
6. Married couples classified single on any string variance / unmapped QID.
7. Termination flows demanded incoming-tenant data that cannot exist;
   sale/owner flows demanded landlord phone and lease contracts they don't have.
8. Visibility guard inert for person-fields (label mismatch).
9. Fabricated field-map IDs polluted the evaluator's label-visibility algorithm.

## 10. Test suite

`336 passed, 10 skipped` (baseline before v0.7: 232 passed, **2 failed**).
New files: `test_requirements_engine.py`, `test_transaction_rules.py`,
`test_doc_vocabulary.py`, `test_supplemental_services.py`. All hermetic —
no network, no API keys; safe to run anywhere (`python -m pytest`).
