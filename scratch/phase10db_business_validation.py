import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

CACHE_PATH = Path("scratch/missing_docs_submissions.json")
RESULTS_PATH = Path("scratch/phase10c_validation_results.json")

# Mapping the 14 matched pairs from Phase 10B audit
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

def translate_checklist_item(item: str) -> str:
    item_lower = item.lower().strip()
    import re
    item_lower = re.sub(r'<[^>]+>', '', item_lower)
    
    # ID photo translations
    if any(x in item_lower for x in ["תז", "זהות", "ספח", "דרכון", "תעודת זהות"]):
        return "ID Photo"
    
    # Lease contract translations
    if any(x in item_lower for x in ["חוזה", "שכירות", "הסכם", "מכר", "רכישה"]):
        return "Lease Contract"
        
    # Municipal tax
    if "ארנונה" in item_lower:
        return "Arnona Bill"
        
    # Utilities
    if "מים" in item_lower:
        if "מונה" in item_lower:
            return "Water Meter"
        return "Water Bill"
        
    if "חשמל" in item_lower:
        if "מונה" in item_lower:
            return "Electricity Meter"
        return "Electricity Bill"
        
    if "גז" in item_lower:
        if "מונה" in item_lower:
            return "Gas Meter"
        return "Gas Bill"
        
    if "טאבו" in item_lower:
        return "Tabu Document"
        
    if "התאגדות" in item_lower or "חתימה" in item_lower or "פרוטוקול" in item_lower or "תאגיד" in item_lower:
        return "Corp Cert"
        
    return "Other"

def map_canonical_to_english_name(doc_type: str) -> str:
    mapping = {
        "id_photo": "ID Photo",
        "lease_contract": "Lease Contract",
        "sale_contract": "Lease Contract",
        "arnona_bill": "Arnona Bill",
        "water_bill": "Water Bill",
        "water_meter": "Water Meter",
        "electricity_bill": "Electricity Bill",
        "electricity_meter": "Electricity Meter",
        "gas_bill": "Gas Bill",
        "gas_meter": "Gas Meter",
        "tabu_document": "Tabu Document",
        "corp_cert": "Corp Cert",
        "signature": "Signature"
    }
    return mapping.get(doc_type, "Other")

def main():
    with open(CACHE_PATH, encoding="utf-8") as f:
        all_subs = json.load(f)
    by_id = {s["id"]: s for s in all_subs}

    with open(RESULTS_PATH, encoding="utf-8") as f:
        results_list = json.load(f)
    
    results_map = {}
    for r in results_list:
        mid = r["missing_id"]
        filename = r["file"]
        results_map[(mid, filename)] = r

    from app.pipeline.reconciliation_merge import FilenameClassifier
    fn_clf = FilenameClassifier()

    table_data = []
    total_before_count = 0
    total_after_count = 0
    recovered_types = {}
    unresolved_types = {}

    for pair in MATCHED_PAIRS:
        mid = pair["missing_id"]
        sub = by_id.get(mid)
        if not sub:
            continue
            
        answers = sub.get("answers", {})

        # Collect Checklist Selections
        checklist_items = []
        for qid, label in CHECKLIST_QIDS.items():
            val = answers.get(qid, {}).get("answer")
            if not val:
                continue
            if isinstance(val, list):
                checklist_items.extend([str(x) for x in val if x])
            elif isinstance(val, str) and val:
                checklist_items.append(val)
        
        missing_before = sorted(list(set(translate_checklist_item(x) for x in checklist_items)))
        if "Other" in missing_before:
            missing_before.remove("Other")

        resolved_types = set()
        
        for qid in UPLOAD_QIDS:
            val = answers.get(qid, {}).get("answer")
            if not val:
                continue
            urls = [val] if isinstance(val, str) else (val if isinstance(val, list) else [])
            for url in urls:
                if not isinstance(url, str) or not url.startswith("http"):
                    continue
                filename = url.split("/")[-1].split("?")[0]
                
                fake_path = f"data/missing_docs_submissions/{mid}/{filename}"
                fn_res = fn_clf.classify(fake_path)
                
                resolved_type = ""
                if fn_res["confidence"] >= 0.90:
                    resolved_type = map_canonical_to_english_name(fn_res["document_type"])
                else:
                    r_res = results_map.get((mid, filename))
                    if r_res and r_res.get("auto_classified"):
                        resolved_type = map_canonical_to_english_name(r_res["gemini_type"])
                
                if resolved_type and resolved_type != "Other":
                    resolved_types.add(resolved_type)

        missing_after = sorted(list(set(missing_before) - resolved_types))
        recovered = sorted(list(set(missing_before) & resolved_types))

        total_before_count += len(missing_before)
        total_after_count += len(missing_after)

        for r in recovered:
            recovered_types[r] = recovered_types.get(r, 0) + 1
        for u in missing_after:
            unresolved_types[u] = unresolved_types.get(u, 0) + 1

        table_data.append({
            "name": pair["orig_name"],
            "before": missing_before,
            "after": missing_after,
            "recovered": recovered
        })

    # Output Markdown Report format
    print("# Phase 10D-B Business Validation Report\n")
    print("## 1. Per-Submission Reduction Table\n")
    print("| Submission | Missing Docs Before AI | Missing Docs After AI | Documents Recovered |")
    print("|---|---|---|---|")
    for row in table_data:
        before_str = ", ".join(f"* {x}" for x in row["before"]) if row["before"] else "*(none)*"
        after_str = ", ".join(f"* {x}" for x in row["after"]) if row["after"] else "*(none)*"
        rec_str = ", ".join(f"* {x}" for x in row["recovered"]) if row["recovered"] else "*(none)*"
        
        # Format lists inside table cells nicely
        before_cell = "<br>".join(f"• {x}" for x in row["before"]) if row["before"] else "*(none)*"
        after_cell = "<br>".join(f"• {x}" for x in row["after"]) if row["after"] else "*(none)*"
        rec_cell = "<br>".join(f"• {x}" for x in row["recovered"]) if row["recovered"] else "*(none)*"
        print(f"| {row['name']} | {before_cell} | {after_cell} | {rec_cell} |")
    
    print("\n## 2. Total Reduction\n")
    reduction = total_before_count - total_after_count
    reduction_pct = (reduction / total_before_count * 100) if total_before_count > 0 else 0
    print(f"- **Total Missing Docs Required Before AI**: {total_before_count}")
    print(f"- **Total Missing Docs Required After AI**: {total_after_count}")
    print(f"- **Absolute Document Reduction**: {reduction} fewer missing document warnings")
    print(f"- **Percentage Reduction in Warnings**: {reduction_pct:.1f}%")

    print("\n## 3. Top Recovered Document Types\n")
    print("| Document Type | Count Recovered |")
    print("|---|---|")
    for dtype, count in sorted(recovered_types.items(), key=lambda x: x[1], reverse=True):
        print(f"| {dtype} | {count} |")

    print("\n## 4. Remaining Unresolved Document Types\n")
    print("| Document Type | Count Remaining |")
    print("|---|---|")
    for dtype, count in sorted(unresolved_types.items(), key=lambda x: x[1], reverse=True):
        print(f"| {dtype} | {count} |")

    print("\n## 5. Complaint Resolution Estimate\n")
    fully_resolved = sum(1 for row in table_data if len(row["before"]) > 0 and len(row["after"]) == 0)
    partially_or_fully = sum(1 for row in table_data if len(row["before"]) > 0 and len(row["recovered"]) > 0)
    total_complaints = sum(1 for row in table_data if len(row["before"]) > 0)
    
    fully_pct = (fully_resolved / total_complaints * 100) if total_complaints > 0 else 0
    part_pct = (partially_or_fully / total_complaints * 100) if total_complaints > 0 else 0

    print(f"- **Total Submissions with Missing Document Warnings**: {total_complaints}")
    print(f"- **Submissions Fully Cleared (0 missing docs remaining)**: {fully_resolved} ({fully_pct:.1f}%)")
    print(f"- **Submissions Partially or Fully Resolved (at least 1 document recovered)**: {partially_or_fully} ({part_pct:.1f}%)")
    print(f"\n**Final Estimate**: **{fully_pct:.1f}%** of Alexander's original document warnings would now be **fully automatically resolved** (cleared completely), and **{part_pct:.1f}%** of complaints would receive significant manual workload relief with at least one document resolved.")

if __name__ == "__main__":
    main()
