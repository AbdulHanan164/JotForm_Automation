"""
Phase 9D Audit Script
=====================
For each of the 14 matched Missing Docs submissions:
  - List every uploaded file: filename, checkbox selection, simulated local path
  - Assess FilenameClassifier result (would it auto-resolve?)
  - Estimate AI vision classification gain

No API calls made. Works entirely from cached scratch/missing_docs_submissions.json
"""
import json
import re
import sys
from pathlib import Path

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

# QID labels from Phase 9A field inventory
CHECKLIST_QID_LABELS = {
    "317": "תעודת זהות",
    "318": "חוזה שכירות",
    "320": "חשבון ארנונה",
    "321": "חשבון מים",
    "322": "חשבון חשמל",
    "323": "תעודת התאגדות",
    "311": "נסח טאבו",
}
UPLOAD_QIDS = ["38", "37", "329", "330", "331"]

# FilenameClassifier keyword patterns (from reconciliation_merge.py)
FILENAME_PATTERNS = {
    "id_photo": [
        r"תעודת.זהות", r"passport", r"id.card", r"identity",
        r"ת\.ז", r"tz\b", r"id\b", r"תעודה",
    ],
    "lease_contract": [
        r"חוזה", r"contract", r"lease", r"rental", r"שכירות",
        r"agreement", r"חוזה.שכירות",
    ],
    "arnona_bill": [
        r"ארנונה", r"arnona", r"municipal", r"tax", r"חשבון.ארנונה",
        r"property.tax",
    ],
    "arnona_account": [
        r"ארנונה", r"arnona",
    ],
    "water_bill": [
        r"מים", r"water", r"מכון.מים",
    ],
    "electricity_bill": [
        r"חשמל", r"electric", r"חברת.חשמל",
    ],
    "corp_cert": [
        r"תאגיד", r"corporation", r"company", r"עוסק", r"רשם.חברות",
        r"incorporation", r"business.reg",
    ],
    "tabu": [
        r"טאבו", r"tabu", r"land.reg", r"רשם.קרקעות", r"נסח",
    ],
    "signature": [
        r"חתימה", r"signature", r"sign",
    ],
}

GENERIC_PATTERNS = [
    r"^whatsapp.image",
    r"^screenshot",
    r"^img_",
    r"^image_",
    r"^photo_",
    r"^dsc",
    r"^\d{8,}",
    r"^file_",
    r"^document_",
]

def filename_classifier_result(filename: str) -> dict:
    """Simulate FilenameClassifier from reconciliation_merge.py."""
    name_lower = filename.lower().replace("_", " ").replace("-", " ")
    
    # Check if generic
    for gp in GENERIC_PATTERNS:
        if re.search(gp, name_lower, re.IGNORECASE):
            return {
                "classifier": "FilenameClassifier",
                "confidence": 0.0,
                "document_type": None,
                "is_generic": True,
                "reason": f"Generic filename pattern: {filename}"
            }
    
    # Try keyword match
    best_match = None
    best_conf = 0.0
    for doc_type, patterns in FILENAME_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, name_lower, re.IGNORECASE):
                # Score by pattern specificity (multi-word > single)
                words = len(pat.replace(r"\.", " ").split())
                conf = 0.95 if words > 1 else 0.85
                if conf > best_conf:
                    best_conf = conf
                    best_match = doc_type
    
    if best_match:
        return {
            "classifier": "FilenameClassifier",
            "confidence": best_conf,
            "document_type": best_match,
            "is_generic": False,
            "reason": f"Filename keyword match → {best_match}"
        }
    
    return {
        "classifier": "FilenameClassifier",
        "confidence": 0.0,
        "document_type": None,
        "is_generic": False,
        "reason": "No keyword match"
    }


def ai_vision_estimate(filename: str, checkbox_doc_type: str) -> dict:
    """
    Estimate whether AI vision would auto-resolve this file.
    
    Heuristics:
    - Generic images of real documents → AI can classify = likely auto-resolve
    - WhatsApp images: almost always real document photos → AI resolves
    - Screenshots: might be confirmations / receipts → AI resolves most
    - Very small files / thumbnails → less certain
    
    Returns {"would_resolve": bool, "confidence_estimate": float, "rationale": str}
    """
    name_lower = filename.lower()
    ext = Path(filename).suffix.lower()
    
    image_formats = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif"}
    pdf_formats = {".pdf"}
    
    if ext in image_formats:
        if "whatsapp" in name_lower:
            return {
                "would_resolve": True,
                "confidence_estimate": 0.93,
                "rationale": "WhatsApp photos of documents are almost always real document images; AI vision resolves with high confidence"
            }
        if "screenshot" in name_lower:
            return {
                "would_resolve": True,
                "confidence_estimate": 0.88,
                "rationale": "Screenshots are typically digital copies of documents; AI vision can read text content"
            }
        if re.search(r"^(img|image|photo|dsc|pic)", name_lower):
            return {
                "would_resolve": True,
                "confidence_estimate": 0.87,
                "rationale": "Camera-captured image — AI vision reads document type from visual content"
            }
        if re.search(r"^\d{8,}", name_lower):
            return {
                "would_resolve": True,
                "confidence_estimate": 0.85,
                "rationale": "Timestamp-named image — likely device photo; AI vision resolves from content"
            }
        # Unknown image name
        return {
            "would_resolve": True,
            "confidence_estimate": 0.80,
            "rationale": "Image file — AI vision can analyze visual content"
        }
    
    if ext in pdf_formats:
        return {
            "would_resolve": True,
            "confidence_estimate": 0.92,
            "rationale": "PDF — AI can extract text/structure and classify document type reliably"
        }
    
    return {
        "would_resolve": False,
        "confidence_estimate": 0.40,
        "rationale": f"Unknown format {ext} — AI vision uncertain"
    }


def extract_files_from_submission(sub: dict) -> list[dict]:
    """Extract all uploaded files with their metadata."""
    answers = sub.get("answers", {})
    files_found = []
    
    # Get all upload URLs
    upload_urls = []
    for qid in UPLOAD_QIDS:
        val = answers.get(qid, {}).get("answer")
        if not val:
            continue
        if isinstance(val, str) and val.startswith("http"):
            upload_urls.append((qid, val))
        elif isinstance(val, list):
            for v in val:
                if isinstance(v, str) and v.startswith("http"):
                    upload_urls.append((qid, v))
    
    # Get checklist selections
    checklist_items = []
    for qid, label in CHECKLIST_QID_LABELS.items():
        val = answers.get(qid, {}).get("answer")
        if not val:
            continue
        if isinstance(val, list):
            checklist_items.extend([str(x) for x in val if x])
        elif isinstance(val, str) and val:
            checklist_items.append(val)
    
    for qid, url in upload_urls:
        filename = url.split("/")[-1].split("?")[0]  # strip query params
        local_path = f"data/missing_docs_submissions/{sub['id']}/{filename}"
        
        fn_result = filename_classifier_result(filename)
        ai_result = ai_vision_estimate(filename, ", ".join(checklist_items) if checklist_items else "")
        
        # CheckboxClassifier: use checklist to infer doc type
        checkbox_doc_type = ", ".join(checklist_items) if checklist_items else "(none selected)"
        
        files_found.append({
            "submission_id": sub["id"],
            "upload_qid": qid,
            "filename": filename,
            "url": url,
            "local_path": local_path,
            "checkbox_selection": checkbox_doc_type,
            "filename_classifier": fn_result,
            "ai_vision_estimate": ai_result,
        })
    
    return files_found


def main():
    print("=" * 70)
    print("PHASE 9D AUDIT — Missing Docs Files Inventory")
    print("=" * 70)
    
    # Load cache
    with open(CACHE_PATH, encoding="utf-8") as f:
        all_subs = json.load(f)
    by_id = {s["id"]: s for s in all_subs}
    
    missing_ids = [p["missing_id"] for p in MATCHED_PAIRS]
    
    all_files = []
    pair_summaries = []
    
    for pair in MATCHED_PAIRS:
        mid = pair["missing_id"]
        sub = by_id.get(mid)
        if not sub:
            print(f"\n  ⚠️  {pair['orig_name']}: missing_id {mid} not in cache")
            continue
        
        files = extract_files_from_submission(sub)
        all_files.extend(files)
        
        # Checklist selections for this sub
        answers = sub.get("answers", {})
        checklist_items = []
        for qid, label in CHECKLIST_QID_LABELS.items():
            val = answers.get(qid, {}).get("answer")
            if not val:
                continue
            if isinstance(val, list):
                checklist_items.extend([str(x) for x in val if x])
            elif isinstance(val, str) and val:
                checklist_items.append(val)
        
        pair_summaries.append({
            "orig_name": pair["orig_name"],
            "orig_id": pair["orig_id"],
            "missing_id": mid,
            "file_count": len(files),
            "checklist": checklist_items,
            "files": files,
        })
    
    # ── DETAILED FILE TABLE ────────────────────────────────────────────────────
    print(f"\nTotal files found: {len(all_files)}")
    print()
    
    for ps in pair_summaries:
        print(f"\n{'─' * 70}")
        print(f"  Original:  {ps['orig_name']} ({ps['orig_id']})")
        print(f"  Missing:   {ps['missing_id']}")
        print(f"  Checklist: {', '.join(ps['checklist']) if ps['checklist'] else '(none)'}")
        print(f"  Files:     {ps['file_count']}")
        
        if not ps["files"]:
            print("  (no uploads found)")
            continue
        
        for f in ps["files"]:
            fn = f["filename_classifier"]
            ai = f["ai_vision_estimate"]
            auto_now   = "✅ AUTO" if fn["confidence"] >= 0.90 else "⏳ NEEDS_REVIEW"
            auto_ai    = "✅ AI RESOLVES" if ai["would_resolve"] else "❌ AI UNCERTAIN"
            
            print(f"\n    File:       {f['filename']}")
            print(f"    Local path: {f['local_path']}")
            print(f"    Checkbox:   {f['checkbox_selection']}")
            print(f"    FilenameClassifier: {auto_now} (conf={fn['confidence']:.2f}) — {fn['reason']}")
            print(f"    AI Vision:  {auto_ai} (est. conf={ai['confidence_estimate']:.2f}) — {ai['rationale']}")
    
    # ── AGGREGATE STATISTICS ──────────────────────────────────────────────────
    print(f"\n\n{'=' * 70}")
    print("AGGREGATE STATISTICS")
    print("=" * 70)
    
    total           = len(all_files)
    auto_resolved   = sum(1 for f in all_files if f["filename_classifier"]["confidence"] >= 0.90)
    generic         = sum(1 for f in all_files if f["filename_classifier"]["is_generic"])
    keyword_match   = sum(1 for f in all_files if not f["filename_classifier"]["is_generic"] and f["filename_classifier"]["confidence"] >= 0.85)
    ai_would_resolve = sum(1 for f in all_files if f["ai_vision_estimate"]["would_resolve"])
    
    print(f"\n  Total files:                {total}")
    print(f"  Auto-resolved now (≥0.90):  {auto_resolved}")
    print(f"  Generic filename:           {generic}")
    print(f"  Keyword match found:        {keyword_match}")
    print(f"  AI would resolve:           {ai_would_resolve} / {total}")
    
    if total > 0:
        print(f"\n  Current auto-resolve rate:   {auto_resolved/total*100:.1f}%")
        print(f"  AI auto-resolve rate (est):  {ai_would_resolve/total*100:.1f}%")
        print(f"  Net gain from AI:            +{ai_would_resolve - auto_resolved} files ({(ai_would_resolve - auto_resolved)/total*100:.1f}%)")
    
    # Breakdown by file type
    ext_counts = {}
    for f in all_files:
        ext = Path(f["filename"]).suffix.lower() or "no-ext"
        ext_counts[ext] = ext_counts.get(ext, 0) + 1
    
    print(f"\n  File extensions breakdown:")
    for ext, count in sorted(ext_counts.items(), key=lambda x: -x[1]):
        print(f"    {ext:12s}: {count}")
    
    # Filename category breakdown
    print(f"\n  Filename categories:")
    categories = {
        "WhatsApp images":  sum(1 for f in all_files if "whatsapp" in f["filename"].lower()),
        "Screenshots":      sum(1 for f in all_files if "screenshot" in f["filename"].lower()),
        "Camera (IMG/DSC)": sum(1 for f in all_files if re.search(r"^(img_|dsc)", f["filename"].lower())),
        "Timestamp named":  sum(1 for f in all_files if re.match(r"^\d{8,}", f["filename"])),
        "Keyword named":    sum(1 for f in all_files if f["filename_classifier"]["confidence"] >= 0.90),
        "Other":            0,
    }
    accounted = sum(v for k, v in categories.items() if k != "Other")
    categories["Other"] = total - accounted
    
    for cat, count in categories.items():
        bar = "█" * count
        print(f"    {cat:22s}: {count:2d} {bar}")
    
    # ── CHECKLIST SELECTIONS SUMMARY ──────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("CHECKLIST SELECTIONS ACROSS ALL 14 PAIRS")
    print("=" * 70)
    
    all_checklist = []
    for ps in pair_summaries:
        all_checklist.extend(ps["checklist"])
    
    checklist_freq = {}
    for item in all_checklist:
        checklist_freq[item] = checklist_freq.get(item, 0) + 1
    
    for item, freq in sorted(checklist_freq.items(), key=lambda x: -x[1]):
        print(f"  {item:30s}: {freq} submission(s)")
    
    # ── AI VISION GAIN ESTIMATE ───────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("EXPECTED AI VISION GAIN ESTIMATE")
    print("=" * 70)
    print(f"""
  Current state (FilenameClassifier only):
    Files auto-resolved:      {auto_resolved} / {total} ({auto_resolved/total*100:.1f}%)
    Files in needs_review:    {total - auto_resolved} / {total} ({(total-auto_resolved)/total*100:.1f}%)
    Missing-doc reductions:   0 (needs_review does not satisfy requirement)

  With AI Vision Classifier (OpenAI / Gemini / Nvidia):
    Files auto-resolved:      ~{ai_would_resolve} / {total} ({ai_would_resolve/total*100:.1f}%)
    Files remaining review:   ~{total - ai_would_resolve} / {total} ({(total - ai_would_resolve)/total*100:.1f}%)
    Estimated missing-doc reductions: depends on which doc type is missing per pair

  Expected business impact per pair (2 missing docs: חוזה_שכירות + חשבון_ארנונה):
    If AI classifies lease contract upload → -1 missing doc per pair
    If AI classifies arnona bill upload    → -1 missing doc per pair
    Maximum reduction possible:            28 (14 pairs × 2 docs)
    Realistic AI reduction estimate:       ~{min(ai_would_resolve, 28)} missing docs resolved

  Conservative estimate (70% accuracy after AI confidence threshold):
    Auto-resolved:            ~{int(ai_would_resolve * 0.7)} files
    Missing-doc reductions:   ~{min(int(ai_would_resolve * 0.7), 22)} across 14 pairs
""")
    
    return all_files, pair_summaries


if __name__ == "__main__":
    main()
