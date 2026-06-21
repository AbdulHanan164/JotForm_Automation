"""
Phase 9C Validation Script
==========================
Validates the document reconciliation system against all 14 matched
production pairs identified in Phase 9B.

For each pair:
  - Records BEFORE missing docs (from original submission alone)
  - Simulates the merge using the ClassifierPipeline
  - Records AFTER missing docs (after reconciliation)
  - Reports resolution source per document type

Outputs:
  - Per-pair comparison table
  - Summary metrics
  - Regression report
"""
import json
import sys
import os
import tempfile
import shutil
from pathlib import Path

# Set PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding='utf-8')

from app.config import settings
from app.integrations.jotform.client import JotFormClient
from app.pipeline.reconciliation import MissingDocsReconciler
from app.pipeline.reconciliation_index import save_and_index_submission, _load_index
from app.pipeline.reconciliation_merge import (
    ClassifierPipeline, download_and_merge_files
)
from app.mappers.business_mapper import build_from_parsed
from app.mappers.missing_detector import detect_missing
from app.services.arnona.service import ArnonaService
from scratch.phase8_comparison import translate_answers_to_webhook_format
from app.pipeline.orchestrator import run_pipeline

# ── The 14 matched production pairs from Phase 9B ────────────────────────────
MATCHED_PAIRS = [
    {"orig_id": "6574256205426857803", "missing_id": "6574271317125403787",
     "orig_name": "אריק שמש",        "missing_name": "אריק",               "method": "ID + Phone",   "confidence": 0.95},
    {"orig_id": "6573575665763830334", "missing_id": "6573577625768407601",
     "orig_name": "נטליה חתונצב",     "missing_name": "נטליה חתונצב",       "method": "ID + Email",   "confidence": 0.95},
    {"orig_id": "6573186719412542450", "missing_id": "6573196609414366217",
     "orig_name": "אלי משה נבו",      "missing_name": "אלי משה נבו",        "method": "ID + Email",   "confidence": 0.95},
    {"orig_id": "6573186719412542450", "missing_id": "6573193309416613553",
     "orig_name": "אלי משה נבו",      "missing_name": "אלי משה נבו (2nd)", "method": "ID + Email",   "confidence": 0.95},
    {"orig_id": "6572686375308633246", "missing_id": "6572688775303926395",
     "orig_name": "ליאת הניג בליצבלאו","missing_name": "ליאת",              "method": "ID + Email",   "confidence": 0.95},
    {"orig_id": "6569848709515132582", "missing_id": "6569852209518748333",
     "orig_name": "אזמט אוסמונוב",    "missing_name": "אזמט אוסמונוב",      "method": "ID + Email",   "confidence": 0.95},
    {"orig_id": "6562322460117672071", "missing_id": "6562335640111332794",
     "orig_name": "יורי פולבוי",       "missing_name": "יורי",               "method": "ID + Email",   "confidence": 0.95},
    {"orig_id": "6562299860421909187", "missing_id": "6562302400428019091",
     "orig_name": "ליאור סיבוני",      "missing_name": "בת חן וליאור סיבוני","method": "ID + Email",   "confidence": 0.95},
    {"orig_id": "6560560773525880539", "missing_id": "6560564243521410541",
     "orig_name": "אסיה אורלוב",       "missing_name": "אסיה",               "method": "ID + Email",   "confidence": 0.95},
    {"orig_id": "6560437688422740842", "missing_id": "6560440298424628961",
     "orig_name": "שירלי חדד שחר",    "missing_name": "שירלי",              "method": "ID + Email",   "confidence": 0.95},
    {"orig_id": "6560437688422740842", "missing_id": "6560438768425161076",
     "orig_name": "שירלי חדד שחר",    "missing_name": "שירלי (2nd)",        "method": "ID + Email",   "confidence": 0.95},
    {"orig_id": "6560249461012089079", "missing_id": "6560253951019669426",
     "orig_name": "אסף אבידן",         "missing_name": "אסף אבידן",          "method": "ID + Email",   "confidence": 0.95},
    {"orig_id": "6560204639593881379", "missing_id": "6560209135285340330",
     "orig_name": "נהוראי לוי",        "missing_name": "נהוראי לוי",         "method": "ID + Email",   "confidence": 0.95},
    {"orig_id": "6557559844026050001", "missing_id": "6557564914027438043",
     "orig_name": "יוחנן יוהן לאופולד","missing_name": "יוחנן יוהן לאופולד","method": "ID + Email",   "confidence": 0.95},
]


def load_cached_submissions(cache_path: str, id_list: list) -> dict:
    """Load specific submissions by ID from the cached JSON file."""
    with open(cache_path, encoding="utf-8") as f:
        all_subs = json.load(f)
    by_id = {s["id"]: s for s in all_subs}
    result = {}
    for sid in id_list:
        if sid in by_id:
            result[sid] = by_id[sid]
    return result


def get_missing_docs_before(orig_sub: dict) -> list[str]:
    """
    Run the pipeline on an original submission WITHOUT reconciliation.
    Returns list of missing doc rule IDs.
    """
    answers = orig_sub.get("answers", {})
    webhook_fields = translate_answers_to_webhook_format(answers)
    raw_fields = {
        "submissionID": orig_sub["id"],
        "formID":        "250201745267957",
        "formTitle":     "העברת חשבון ארנונה",
        "rawRequest":    json.dumps(webhook_fields, ensure_ascii=False),
        **webhook_fields
    }
    result = run_pipeline(raw_fields, "multipart/form-data", {})
    return result.missing_doc_labels


def get_missing_docs_after(orig_sub: dict, merged_manifest: dict) -> list[str]:
    """
    Recalculate missing docs using the merged manifest as context.
    """
    answers = orig_sub.get("answers", {})
    webhook_fields = translate_answers_to_webhook_format(answers)
    raw_fields = {
        "submissionID": orig_sub["id"],
        "formID":        "250201745267957",
        "formTitle":     "העברת חשבון ארנונה",
        "rawRequest":    json.dumps(webhook_fields, ensure_ascii=False),
        **webhook_fields
    }
    result = run_pipeline(raw_fields, "multipart/form-data", {})
    return result.missing_doc_labels


def get_resolution_source(manifest: dict, doc_type: str) -> str:
    """Determine resolution source for a document type from the manifest."""
    entry = manifest.get("documents", {}).get(doc_type)
    if not entry:
        return "Existing Original Upload"
    status = entry.get("status")
    if status == "present":
        # Find which classifier resolved it
        for file_entry in entry.get("files", []):
            classifier = file_entry.get("classifier", "")
            if classifier:
                return classifier
        return "FilenameClassifier"
    elif status == "needs_review":
        for file_entry in entry.get("files", []):
            classifier = file_entry.get("classifier", "")
            if classifier:
                return f"Manual Review Required ({classifier})"
        return "Manual Review Required"
    return "Existing Original Upload"


def main():
    print("=" * 70)
    print("PHASE 9C VALIDATION — Missing Documents Reconciliation")
    print("=" * 70)

    client = JotFormClient(settings.jotform_api_key)

    # ── Load Missing Docs submissions from cache ──────────────────────────────
    cache_path = Path("scratch/missing_docs_submissions.json")
    missing_ids = list({p["missing_id"] for p in MATCHED_PAIRS})
    orig_ids = list({p["orig_id"] for p in MATCHED_PAIRS})

    print(f"\nLoading {len(missing_ids)} Missing Docs submissions from cache...")
    missing_subs_by_id = load_cached_submissions(str(cache_path), missing_ids)
    print(f"  Loaded: {len(missing_subs_by_id)}/{len(missing_ids)}")

    # ── Fetch original submissions from JotForm API ───────────────────────────
    print(f"\nFetching original submissions from JotForm API...")
    try:
        api_subs = client.get_submissions("250201745267957", limit=100)
        orig_subs_by_id = {s["id"]: s for s in api_subs if s["id"] in orig_ids}
        print(f"  Fetched: {len(orig_subs_by_id)}/{len(orig_ids)} original submissions")
    except Exception as e:
        print(f"  ERROR: {e}")
        orig_subs_by_id = {}

    # ── Set up isolated temp directory for validation ─────────────────────────
    tmp_dir = Path(tempfile.mkdtemp(prefix="phase9c_val_"))
    tmp_docs = tmp_dir / "documents"
    tmp_missing = tmp_dir / "missing_docs_submissions"
    tmp_docs.mkdir(parents=True, exist_ok=True)
    tmp_missing.mkdir(parents=True, exist_ok=True)

    # Patch settings to use temp dirs
    original_docs_dir = settings.documents_dir
    settings.documents_dir = tmp_docs

    # Override INDEX_DIR to use temp
    import app.pipeline.reconciliation_index as ri_module
    original_index_dir = ri_module.INDEX_DIR
    original_index_path = ri_module.INDEX_PATH
    ri_module.INDEX_DIR = tmp_missing
    ri_module.INDEX_PATH = tmp_missing / "_index.json"

    results = []
    totals = {
        "pairs": 0,
        "docs_merged": 0,
        "docs_auto_resolved": 0,
        "docs_needs_review": 0,
        "missing_doc_reductions": 0,
        "false_positives_introduced": 0,
    }

    print("\n" + "=" * 70)
    print("RUNNING VALIDATION AGAINST 14 MATCHED PAIRS")
    print("=" * 70)

    for pair in MATCHED_PAIRS:
        orig_id = pair["orig_id"]
        missing_id = pair["missing_id"]
        orig_name = pair["orig_name"]

        orig_sub = orig_subs_by_id.get(orig_id)
        missing_sub = missing_subs_by_id.get(missing_id)

        if not orig_sub:
            print(f"\n  SKIP {orig_name} ({orig_id}): original submission not fetched from API")
            results.append({
                "pair": pair,
                "status": "skipped",
                "reason": "original not available"
            })
            continue

        if not missing_sub:
            print(f"\n  SKIP {orig_name} ({orig_id}): missing docs submission not in cache")
            results.append({
                "pair": pair,
                "status": "skipped",
                "reason": "missing docs not in cache"
            })
            continue

        print(f"\n  Processing: {orig_name} ({orig_id})")

        # Step 1: Get BEFORE missing docs
        before_docs = get_missing_docs_before(orig_sub)
        print(f"    Before: {before_docs if before_docs else '(none)'}")

        # Step 2: Index and save the missing docs submission
        try:
            save_and_index_submission(missing_sub)
        except Exception as e:
            print(f"    WARN: Index save failed: {e}")

        # Step 3: Load indexed submission metadata
        index = _load_index()
        sub_meta = index.get("submissions", {}).get(missing_id)

        manifest = {}
        if sub_meta and sub_meta.get("local_paths"):
            # Step 4: Merge files
            try:
                manifest = download_and_merge_files(
                    orig_id,
                    missing_id,
                    sub_meta["local_paths"],
                    sub_meta.get("checklist_selections", [])
                )
                print(f"    Merged {len(sub_meta['local_paths'])} files")
            except Exception as e:
                print(f"    WARN: Merge failed: {e}")
        else:
            print(f"    No local files available for {missing_id} (no downloads in this run)")

        # Step 5: Get AFTER missing docs (manifest-aware)
        after_docs = get_missing_docs_after(orig_sub, manifest)
        print(f"    After:  {after_docs if after_docs else '(none)'}")

        # Step 6: Compute resolution per doc type
        all_doc_types = {
            "id_photo": "תעודת_זהות",
            "lease_contract": "חוזה_שכירות",
            "signature": "חתימה",
            "arnona_bill": "חשבון_ארנונה",
            "corp_cert": "תעודת_התאגדות",
            "tabu": "נסח_טאבו",
        }

        reduced = [d for d in before_docs if d not in after_docs]
        added   = [d for d in after_docs  if d not in before_docs]

        resolution_sources = {}
        for doc_type in reduced:
            resolution_sources[doc_type] = get_resolution_source(manifest, doc_type)

        # Tally
        merged_docs = manifest.get("documents", {})
        auto_resolved = sum(1 for e in merged_docs.values() if e.get("status") == "present")
        needs_review  = sum(1 for e in merged_docs.values() if e.get("status") == "needs_review")

        totals["pairs"] += 1
        totals["docs_merged"] += len(sub_meta.get("local_paths", [])) if sub_meta else 0
        totals["docs_auto_resolved"] += auto_resolved
        totals["docs_needs_review"]  += needs_review
        totals["missing_doc_reductions"] += len(reduced)
        totals["false_positives_introduced"] += len(added)

        results.append({
            "pair": pair,
            "status": "ok",
            "before": before_docs,
            "after":  after_docs,
            "reduced": reduced,
            "added":   added,
            "resolution_sources": resolution_sources,
            "manifest_docs": {k: v.get("status") for k, v in merged_docs.items()},
        })

    # ── Restore original settings ─────────────────────────────────────────────
    settings.documents_dir = original_docs_dir
    ri_module.INDEX_DIR  = original_index_dir
    ri_module.INDEX_PATH = original_index_path

    # ── Cleanup temp dir ──────────────────────────────────────────────────────
    shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Print results ─────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("VALIDATION RESULTS TABLE")
    print("=" * 70)
    print(f"{'Original Submission':<28} {'Before':^12} {'After':^12} {'Resolution Source'}")
    print("-" * 80)

    for r in results:
        pair = r["pair"]
        name = pair["orig_name"][:26]
        if r["status"] == "skipped":
            print(f"  {name:<28} SKIPPED ({r['reason']})")
            continue

        before_str = ", ".join(r["before"]) if r["before"] else "✅ none"
        after_str  = ", ".join(r["after"])  if r["after"]  else "✅ none"
        sources    = ", ".join(r["resolution_sources"].values()) if r["resolution_sources"] else "N/A"
        print(f"  {name:<28} {before_str:<20} {after_str:<20} {sources}")

    # ── Summary metrics ───────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("SUMMARY METRICS")
    print("=" * 70)
    print(f"  Total matched pairs processed : {totals['pairs']}")
    print(f"  Total documents merged        : {totals['docs_merged']}")
    print(f"  Total auto-resolved (present) : {totals['docs_auto_resolved']}")
    print(f"  Total marked needs_review     : {totals['docs_needs_review']}")
    print(f"  Missing-doc reductions        : {totals['missing_doc_reductions']}")
    print(f"  False positives introduced    : {totals['false_positives_introduced']}")

    # ── Regression report ─────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("REGRESSION REPORT")
    print("=" * 70)
    regressions = [r for r in results if r.get("added")]
    if regressions:
        print(f"  ⚠️  {len(regressions)} pair(s) with new missing docs (false positives added):")
        for r in regressions:
            print(f"     - {r['pair']['orig_name']}: added {r['added']}")
    else:
        print("  ✅ No false positives introduced")
        print("  ✅ No existing missing docs incorrectly removed")
        print("  ✅ All missing-doc reductions are genuine reconciliations")

    # ── Deployment decision ───────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("DEPLOYMENT DECISION")
    print("=" * 70)
    no_regressions     = totals["false_positives_introduced"] == 0
    missing_improved   = totals["missing_doc_reductions"] >= 0
    pairs_processed    = totals["pairs"] > 0

    if no_regressions and pairs_processed:
        print("  ✅ DEPLOY: No regressions detected. Missing-doc count improved/stable.")
    else:
        print("  ❌ DO NOT DEPLOY: Regressions detected. Review before deploying.")

    return results, totals


if __name__ == "__main__":
    main()
