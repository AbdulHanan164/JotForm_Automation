"""
Phase 10C Validation Script
============================
Runs GeminiVisionClassifier against the 61 truly unresolved files from the
Phase 10B audit. Downloads files live from JotForm CDN URLs.

Requirements:
  - GEMINI_API_KEY must be set in .env
  - google-generativeai installed
  - internet connection for JotForm CDN downloads

Mode: --dry-run (default) or --live
  dry-run: Simulate without calling Gemini (reports which files would be sent)
  live:    Actually call Gemini (costs API credits)
"""
import json
import sys
import argparse
import tempfile
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding='utf-8')

CACHE_PATH = Path("scratch/missing_docs_submissions.json")

MATCHED_PAIRS = [
    {"orig_id": "6574256205426857803", "missing_id": "6574271317125403787", "orig_name": "אריק שמש"},
    {"orig_id": "6573575665763830334", "missing_id": "6573577625768407601", "orig_name": "נטליה חתונצב"},
    {"orig_id": "6573186719412542450", "missing_id": "6573196609414366217", "orig_name": "אלי משה נבו (1)"},
    {"orig_id": "6573186719412542450", "missing_id": "6573193309416613553", "orig_name": "אלי משה נבו (2)"},
    {"orig_id": "6572686375308633246", "missing_id": "6572688775303926395", "orig_name": "ליאת הניג בליצבלאו"},
    {"orig_id": "6569848709515132582", "missing_id": "6569852209518748333", "orig_name": "אזמט אוסמונוב"},
    {"orig_id": "6562322460117672071", "missing_id": "6562335640111332794", "orig_name": "יורי פולבוי"},
    {"orig_id": "6562299860421909187", "missing_id": "6562302400428019091", "orig_name": "ליאור סיבוני"},
    {"orig_id": "6560560773525880539", "missing_id": "6560564243521410541", "orig_name": "אסיה אורלוב"},
    {"orig_id": "6560437688422740842", "missing_id": "6560440298424628961", "orig_name": "שירלי חדד שחר (1)"},
    {"orig_id": "6560437688422740842", "missing_id": "6560438768425161076", "orig_name": "שירלי חדד שחר (2)"},
    {"orig_id": "6560249461012089079", "missing_id": "6560253951019669426", "orig_name": "אסף אבידן"},
    {"orig_id": "6560204639593881379", "missing_id": "6560209135285340330", "orig_name": "נהוראי לוי"},
    {"orig_id": "6557559844026050001", "missing_id": "6557564914027438043", "orig_name": "יוחנן יוהן לאופולד"},
]

UPLOAD_QIDS = ["38", "37", "329", "330", "331"]
CHECKLIST_QIDS = {
    "317": "תעודת זהות", "318": "חוזה שכירות", "320": "חשבון ארנונה",
    "321": "חשבון מים", "322": "חשבון חשמל", "323": "תעודת התאגדות", "311": "נסח טאבו",
}

# Files already auto-resolved by FilenameClassifier after Phase 10A+10B corrections
ALREADY_RESOLVED = {
    "נטליה_חתון_חוזה_שכירות_2026_שלוה_166.pdf",
    "צילום_חשבון_ארנונה.pdf",
    "נסח_טאבו_לגיא_28229.pdf",
    "חוזה_שכירות_חתום.pdf",
    "סיום שכירות יואב 18.pdf",
    "תז וספח JGL.jpg",
    "רותי ויץ לאופולד תז 2024.pdf",
    "נדב כהן תז וספח.jpg",
    "קריאת מונה מים יואב 18.jpeg",
    "קריאת מונה חשמל יואב 18.jpeg",
    # Additional resolved from full-cache run
    "נטליה_חתום_הסכם_שכירות_2026_אלנבי_166.pdf",
    "צילום_חשבון_גז.pdf",
    "אישור_עירייה_לטאבו_28229.pdf",
    "חוזה_מכירה_חתום.pdf",
    "הסכם רכישה חתום.pdf",
    "חשמל מידטאון.jpeg",
    "תעודת זהות שירלי מידטאון.jpeg",
    "חוזה שכירותמידטאון.jpeg",
}


def download_to_temp(url: str, suffix: str) -> Path | None:
    """Download a URL to a temp file, return path or None on failure."""
    try:
        from app.documents.downloader import _with_api_key
        request_url = _with_api_key(url)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        req = urllib.request.Request(request_url, headers={"User-Agent": "MAZEKAL/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            tmp.write(resp.read())
        tmp.close()
        return Path(tmp.name)
    except Exception as exc:
        print(f"      ⚠️  Download failed: {exc}")
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Actually call Gemini API")
    parser.add_argument("--limit", type=int, default=0, help="Max files to process (0=all)")
    args = parser.parse_args()

    mode = "LIVE" if args.live else "DRY-RUN"

    print("=" * 70)
    print(f"PHASE 10C VALIDATION — GeminiVisionClassifier ({mode})")
    print("=" * 70)

    from app.pipeline.reconciliation_merge import ClassifierPipeline, FilenameClassifier

    fn_clf = FilenameClassifier()
    pipeline = ClassifierPipeline()

    if args.live:
        from app.config import settings
        if not settings.gemini_api_key and not settings.openai_api_key:
            print("\n❌ ERROR: Neither GEMINI_API_KEY nor OPENAI_API_KEY set in .env — cannot run live mode")
            sys.exit(1)
        print(f"  Gemini API key: {'configured' if settings.gemini_api_key else 'not configured'}")
        print(f"  OpenAI API key: {'configured' if settings.openai_api_key else 'not configured'}")
    else:
        print("  Mode: DRY-RUN — Gemini/OpenAI will NOT be called")

    # Load cache
    with open(CACHE_PATH, encoding="utf-8") as f:
        all_subs = json.load(f)
    by_id = {s["id"]: s for s in all_subs}

    results = []
    processed = 0

    for pair in MATCHED_PAIRS:
        mid = pair["missing_id"]
        sub = by_id.get(mid)
        if not sub:
            continue

        answers = sub.get("answers", {})

        # Collect checklist
        checklist = []
        for qid, label in CHECKLIST_QIDS.items():
            val = answers.get(qid, {}).get("answer")
            if not val:
                continue
            if isinstance(val, list):
                checklist.extend([str(x) for x in val if x])
            elif isinstance(val, str) and val:
                checklist.append(val)

        # Collect uploads
        for qid in UPLOAD_QIDS:
            val = answers.get(qid, {}).get("answer")
            if not val:
                continue
            urls = [val] if isinstance(val, str) else (val if isinstance(val, list) else [])
            for url in urls:
                if not isinstance(url, str) or not url.startswith("http"):
                    continue

                filename = url.split("/")[-1].split("?")[0]
                ext = Path(filename).suffix.lower()

                # Check FilenameClassifier first
                fake_path = f"data/missing_docs_submissions/{mid}/{filename}"
                fn_res = fn_clf.classify(fake_path)

                if fn_res["confidence"] >= 0.90:
                    # Already resolved — skip
                    continue

                if filename in ALREADY_RESOLVED:
                    continue

                # This file is unresolved — candidate for Pipeline
                processed += 1
                if args.limit and processed > args.limit:
                    break

                print(f"\n  [{processed}] {pair['orig_name']} / {filename}")
                print(f"      Checklist: {', '.join(checklist[:3])}{'...' if len(checklist) > 3 else ''}")

                if args.live:
                    # Download to temp
                    tmp_path = download_to_temp(url, suffix=ext)
                    if not tmp_path:
                        pipeline_res = {
                            "document_type": "",
                            "confidence": 0.0,
                            "reason": "Download failed",
                            "classifier": "ClassifierPipeline",
                        }
                    else:
                        pipeline_res = pipeline.classify(str(tmp_path))
                        try:
                            tmp_path.unlink()
                        except Exception:
                            pass
                else:
                    # Dry run — simulate what would happen
                    pipeline_res = {
                        "document_type": "(would call AI)",
                        "confidence": 0.0,
                        "reason": f"DRY-RUN: file would be processed by ClassifierPipeline",
                        "classifier": "ClassifierPipeline",
                    }

                auto = pipeline_res["confidence"] >= 0.90
                status = "✅ AUTO" if auto else "⏳ REVIEW"

                print(f"      Pipeline: {status}  type={pipeline_res['document_type']}  conf={pipeline_res['confidence']:.2f}  via={pipeline_res.get('classifier', 'None')}")
                print(f"      Reason: {pipeline_res['reason'][:80]}")

                results.append({
                    "file": filename,
                    "submission": pair["orig_name"],
                    "missing_id": mid,
                    "checklist": checklist,
                    "gemini_type": pipeline_res["document_type"],
                    "gemini_conf": pipeline_res["confidence"],
                    "auto_classified": auto,
                    "reason": pipeline_res["reason"],
                    "model": pipeline_res.get("model", ""),
                    "classified_at": pipeline_res.get("classified_at", ""),
                })

            if args.limit and processed >= args.limit:
                break

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    auto_count = sum(1 for r in results if r["auto_classified"])
    review_count = len(results) - auto_count

    print(f"  Mode:               {mode}")
    print(f"  Files processed:    {len(results)}")
    print(f"  Auto-classified:    {auto_count}")
    print(f"  Needs review:       {review_count}")
    if results:
        print(f"  Classification rate: {auto_count / len(results) * 100:.1f}%")

    baseline_filename = 18
    total_files = 79
    new_total = baseline_filename + auto_count
    print(f"\n  Before/After:")
    print(f"    FilenameClassifier only:        {baseline_filename} / {total_files} ({baseline_filename/total_files*100:.1f}%)")
    print(f"    FilenameClassifier + Gemini:    {new_total} / {total_files} ({new_total/total_files*100:.1f}%)")

    # Save results
    out_path = Path("scratch/phase10c_validation_results.json")
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  Results saved to {out_path}")


if __name__ == "__main__":
    main()
