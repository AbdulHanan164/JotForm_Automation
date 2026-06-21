"""
Phase 10B Audit Script
======================
For every file that scored 0.00 after Phase 10A FilenameClassifier upgrade,
collect all available metadata from the cached submission JSON and produce
a structured report for AI Vision decision-making.

No API calls. No downloads. No code changes. Read-only.
"""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

CACHE_PATH = Path("scratch/missing_docs_submissions.json")

MATCHED_PAIRS = [
    {"orig_id": "6574256205426857803", "missing_id": "6574271317125403787", "orig_name": "אריק שמש",            "match_conf": 0.95, "match_method": "ID + Phone"},
    {"orig_id": "6573575665763830334", "missing_id": "6573577625768407601", "orig_name": "נטליה חתונצב",        "match_conf": 0.95, "match_method": "ID + Email"},
    {"orig_id": "6573186719412542450", "missing_id": "6573196609414366217", "orig_name": "אלי משה נבו (1)",     "match_conf": 0.95, "match_method": "ID + Email"},
    {"orig_id": "6573186719412542450", "missing_id": "6573193309416613553", "orig_name": "אלי משה נבו (2)",     "match_conf": 0.95, "match_method": "ID + Email"},
    {"orig_id": "6572686375308633246", "missing_id": "6572688775303926395", "orig_name": "ליאת הניג בליצבלאו",  "match_conf": 0.95, "match_method": "ID + Email"},
    {"orig_id": "6569848709515132582", "missing_id": "6569852209518748333", "orig_name": "אזמט אוסמונוב",       "match_conf": 0.95, "match_method": "ID + Email"},
    {"orig_id": "6562322460117672071", "missing_id": "6562335640111332794", "orig_name": "יורי פולבוי",          "match_conf": 0.95, "match_method": "ID + Email"},
    {"orig_id": "6562299860421909187", "missing_id": "6562302400428019091", "orig_name": "ליאור סיבוני",         "match_conf": 0.95, "match_method": "ID + Email"},
    {"orig_id": "6560560773525880539", "missing_id": "6560564243521410541", "orig_name": "אסיה אורלוב",          "match_conf": 0.95, "match_method": "ID + Email"},
    {"orig_id": "6560437688422740842", "missing_id": "6560440298424628961", "orig_name": "שירלי חדד שחר (1)",   "match_conf": 0.95, "match_method": "ID + Email"},
    {"orig_id": "6560437688422740842", "missing_id": "6560438768425161076", "orig_name": "שירלי חדד שחר (2)",   "match_conf": 0.95, "match_method": "ID + Email"},
    {"orig_id": "6560249461012089079", "missing_id": "6560253951019669426", "orig_name": "אסף אבידן",            "match_conf": 0.95, "match_method": "ID + Email"},
    {"orig_id": "6560204639593881379", "missing_id": "6560209135285340330", "orig_name": "נהוראי לוי",           "match_conf": 0.95, "match_method": "ID + Email"},
    {"orig_id": "6557559844026050001", "missing_id": "6557564914027438043", "orig_name": "יוחנן יוהן לאופולד",  "match_conf": 0.95, "match_method": "ID + Email"},
]

CHECKLIST_QIDS = {
    "317": "תעודת זהות",
    "318": "חוזה שכירות",
    "320": "חשבון ארנונה",
    "321": "חשבון מים",
    "322": "חשבון חשמל",
    "323": "תעודת התאגדות",
    "311": "נסח טאבו",
}
UPLOAD_QIDS = ["38", "37", "329", "330", "331"]

# These are the files Phase 10A resolved (confirmed from pre-audit output)
PHASE10A_RESOLVED = {
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
}

def categorize_filename(fn: str) -> str:
    fl = fn.lower()
    if "whatsapp" in fl:
        return "WhatsApp_Image"
    if fl.startswith("screenshot"):
        return "Screenshot"
    if fl.startswith("img_"):
        return "IMG_"
    if re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', fl):
        return "UUID"
    return "Other"

def checklist_to_doc_candidates(checklist: list[str]) -> list[str]:
    """Map checklist text to candidate document types."""
    candidates = []
    for item in checklist:
        il = item
        if any(x in il for x in ["תעודת זהות", "תז", "זהות", "ספח"]):
            candidates.append("id_photo")
        if any(x in il for x in ["חוזה", "שכירות", "מכר", "הסכם"]):
            candidates.append("lease_contract")
        if "ארנונה" in il:
            candidates.append("arnona_bill")
        if "חשבון מים" in il:
            candidates.append("water_bill")
        if "מונה מים" in il:
            candidates.append("water_meter")
        if "חשבון חשמל" in il:
            candidates.append("electricity_bill")
        if "מונה חשמל" in il:
            candidates.append("electricity_meter")
        if "חשבון גז" in il:
            candidates.append("gas_bill")
        if "מונה גז" in il:
            candidates.append("gas_meter")
        if "טאבו" in il:
            candidates.append("tabu_document")
        if "התאגדות" in il:
            candidates.append("corp_cert")
        # Generic meter reads (could be water/elec/gas)
        if "מונה" in il and not any(x in il for x in ["מונה מים","מונה חשמל","מונה גז"]):
            candidates.append("utility_meter_generic")
    return list(dict.fromkeys(candidates))  # deduplicate, preserve order

def ai_recoverability(category: str, candidates: list[str], ext: str) -> dict:
    """
    Estimate AI Vision recoverability for this file.
    Returns {recoverable: bool, confidence: float, rationale: str}
    """
    ext = ext.lower()
    is_image = ext in {".jpg", ".jpeg", ".png", ".heic", ".webp"}
    is_pdf   = ext == ".pdf"

    if not is_image and not is_pdf:
        return {"recoverable": False, "confidence": 0.30,
                "rationale": f"Unsupported format '{ext}' — AI vision uncertain"}

    if category == "WhatsApp_Image":
        # WhatsApp photos of documents are almost always real document scans
        return {"recoverable": True, "confidence": 0.92,
                "rationale": "WhatsApp images are device photos of physical documents; "
                             "AI vision reads document type from visual content with high accuracy"}

    if category == "Screenshot":
        # Screenshots are typically digital document copies
        return {"recoverable": True, "confidence": 0.87,
                "rationale": "Screenshots contain rendered document text; "
                             "AI reads headers/labels to classify"}

    if category == "IMG_":
        return {"recoverable": True, "confidence": 0.88,
                "rationale": "Camera-captured images (IMG_) are direct document photos; "
                             "AI vision reads visual content reliably"}

    if category == "UUID":
        return {"recoverable": True, "confidence": 0.82,
                "rationale": "UUID-named files (JotForm CDN output) contain unknown visual content; "
                             "AI can classify but no name-based signal"}

    return {"recoverable": True, "confidence": 0.80,
            "rationale": "File likely contains document content; AI can analyze"}


def main():
    with open(CACHE_PATH, encoding="utf-8") as f:
        all_subs = json.load(f)
    by_id = {s["id"]: s for s in all_subs}

    unresolved_files = []
    pair_map = {p["missing_id"]: p for p in MATCHED_PAIRS}

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

        # Also collect free-form checklist from any answer containing these Hebrew patterns
        for qid, ans_data in answers.items():
            if qid in CHECKLIST_QIDS or qid in UPLOAD_QIDS:
                continue
            ans = ans_data.get("answer", "")
            if isinstance(ans, list):
                for a in ans:
                    if isinstance(a, str) and any(kw in a for kw in ["תז","חוזה","ארנונה","מים","חשמל","גז","טאבו","ספח","מונה","צילום"]):
                        checklist.append(a)
            elif isinstance(ans, str) and any(kw in ans for kw in ["תז","חוזה","ארנונה","מים","חשמל","גז","טאבו","ספח","מונה","צילום"]):
                checklist.append(ans)

        checklist = list(dict.fromkeys(checklist))  # deduplicate

        # Collect uploads
        for qid in UPLOAD_QIDS:
            val = answers.get(qid, {}).get("answer")
            if not val:
                continue
            urls = [val] if isinstance(val, str) else val
            for url in (urls if isinstance(urls, list) else []):
                if not isinstance(url, str) or not url.startswith("http"):
                    continue
                filename = url.split("/")[-1].split("?")[0]

                # Skip Phase 10A resolved files
                if filename in PHASE10A_RESOLVED:
                    continue

                ext = Path(filename).suffix
                category = categorize_filename(filename)
                candidates = checklist_to_doc_candidates(checklist)
                ai_est = ai_recoverability(category, candidates, ext)

                unresolved_files.append({
                    "filename": filename,
                    "ext": ext,
                    "category": category,
                    "missing_id": mid,
                    "orig_id": pair["orig_id"],
                    "orig_name": pair["orig_name"],
                    "match_conf": pair["match_conf"],
                    "match_method": pair["match_method"],
                    "checklist": checklist,
                    "candidates": candidates,
                    "ai_recoverable": ai_est["recoverable"],
                    "ai_confidence": ai_est["confidence"],
                    "ai_rationale": ai_est["rationale"],
                    "local_path": f"data/missing_docs_submissions/{mid}/{filename}",
                })

    # ── PRINT REPORT ─────────────────────────────────────────────────────────
    print("=" * 80)
    print("PHASE 10B AUDIT — AI Vision Classification Feasibility")
    print("=" * 80)
    print(f"\nTotal unresolved files after Phase 10A: {len(unresolved_files)}")

    # Category breakdown
    cats = {}
    for f in unresolved_files:
        cats[f["category"]] = cats.get(f["category"], 0) + 1
    print("\nCategory breakdown:")
    for cat, cnt in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"  {cat:<20}: {cnt:>3} files")

    # Extension breakdown
    exts = {}
    for f in unresolved_files:
        exts[f["ext"]] = exts.get(f["ext"], 0) + 1
    print("\nExtension breakdown:")
    for ext, cnt in sorted(exts.items(), key=lambda x: -x[1]):
        print(f"  {ext or '(none)':<10}: {cnt:>3} files")

    # Per-file table
    print("\n" + "=" * 80)
    print("FULL FILE TABLE")
    print("=" * 80)
    print(f"  {'#':>3}  {'Filename':<50}  {'Cat':<16}  {'Candidates':<35}  {'AI Conf':>7}")
    print("  " + "-" * 120)

    for i, f in enumerate(unresolved_files, 1):
        fn = f["filename"][:48]
        cands = ", ".join(f["candidates"])[:33] if f["candidates"] else "(none)"
        print(f"  {i:>3}  {fn:<50}  {f['category']:<16}  {cands:<35}  {f['ai_confidence']:>6.2f}")

    # Candidate doc type frequency
    print("\n" + "=" * 80)
    print("CANDIDATE DOCUMENT TYPE FREQUENCY (from checklist)")
    print("=" * 80)
    type_counts = {}
    for f in unresolved_files:
        for c in f["candidates"]:
            type_counts[c] = type_counts.get(c, 0) + 1
    for dtype, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
        bar = "█" * min(cnt, 40)
        print(f"  {dtype:<28}: {cnt:>3}  {bar}")

    # Recovery estimate
    print("\n" + "=" * 80)
    print("AI RECOVERY ESTIMATE")
    print("=" * 80)
    recoverable = sum(1 for f in unresolved_files if f["ai_recoverable"])
    avg_conf = sum(f["ai_confidence"] for f in unresolved_files) / len(unresolved_files) if unresolved_files else 0
    conservative = int(len(unresolved_files) * 0.70)
    optimistic = recoverable

    print(f"  Unresolved files:            {len(unresolved_files)}")
    print(f"  AI-recoverable (estimated):  {recoverable} / {len(unresolved_files)}")
    print(f"  Average AI confidence:       {avg_conf:.2f}")
    print(f"  Optimistic recovery:         {optimistic} files ({optimistic/len(unresolved_files)*100:.1f}%)")
    print(f"  Conservative recovery (70%): {conservative} files ({conservative/len(unresolved_files)*100:.1f}%)")

    # Output raw data for report generation
    import json as js
    Path("scratch/phase10b_unresolved.json").write_text(
        js.dumps(unresolved_files, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"\n  Data written to scratch/phase10b_unresolved.json ({len(unresolved_files)} records)")

    return unresolved_files

if __name__ == "__main__":
    main()
