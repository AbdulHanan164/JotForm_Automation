import json
import sys
from pathlib import Path

# Set PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.integrations.jotform.client import JotFormClient
from app.pipeline.reconciliation import MissingDocsReconciler

sys.stdout.reconfigure(encoding='utf-8')

def main():
    client = JotFormClient(settings.jotform_api_key)
    reconciler = MissingDocsReconciler()
    
    # 1. Load Missing-Docs submissions
    missing_form_id = "251323124205946"
    print(f"Loading Missing Documents submissions...")
    try:
        # Load cached submissions first, or fetch fresh if cache missing
        cache_path = Path("scratch/missing_docs_submissions.json")
        if cache_path.exists():
            with open(cache_path, encoding="utf-8") as f:
                missing_subs = json.load(f)
        else:
            missing_subs = client.get_submissions(missing_form_id, limit=50)
        print(f"Loaded {len(missing_subs)} Missing Documents submissions.")
    except Exception as e:
        print(f"Error loading missing docs submissions: {e}")
        return

    # 2. Load original Arnona submissions
    arnona_form_id = "250201745267957"
    print("Fetching recent original submissions from JotForm API...")
    try:
        orig_subs = client.get_submissions(arnona_form_id, limit=50)
        print(f"Fetched {len(orig_subs)} original submissions from API.")
    except Exception as e:
        print(f"Error fetching original submissions: {e}")
        return

    # 3. Match each original submission against the missing docs submissions
    report_rows = []
    
    for orig in orig_subs:
        orig_id = orig["id"]
        answers = orig.get("answers", {})
        
        # Determine customer name for display
        first = answers.get("21", {}).get("answer") or ""
        last = answers.get("20", {}).get("answer") or ""
        fullname = f"{first} {last}".strip() or "Unknown"
        
        # Determine MZK Ref
        mzk = answers.get("291", {}).get("answer") or answers.get("184", {}).get("answer") or "none"
        
        orig_label = f"{fullname} ({orig_id}) [MZK: {mzk}]"
        
        # Run matching
        matches = reconciler.match_submission(orig, missing_subs)
        
        for m in matches:
            matched_sub = m["matched_submission"]
            confidence = m["confidence"]
            reason = m["reason"]
            
            sub_answers = matched_sub.get("answers", {})
            sub_first = sub_answers.get("21", {}).get("answer") or ""
            sub_last = sub_answers.get("20", {}).get("answer") or ""
            sub_fullname = f"{sub_first} {sub_last}".strip() or "Unknown"
            
            sub_label = f"{sub_fullname} ({matched_sub['id']}) [MZK: {matched_sub.get('answers', {}).get('184', {}).get('answer') or 'none'}]"
            
            report_rows.append({
                "orig": orig_label,
                "missing": sub_label,
                "method": reason,
                "confidence": confidence
            })

    # Print out results as markdown table
    print("\n### Matching Results Table")
    print("| Original Submission | Missing Docs Submission | Match Method | Confidence |")
    print("|---|---|---|---|")
    for r in report_rows:
        print(f"| {r['orig']} | {r['missing']} | {r['method']} | {r['confidence']} |")

    # Generate MD report
    report_content = f"""# Phase 9B - Document Reconciliation Matching Report

This report presents the validation results of the document reconciliation matching engine run against real production data ({len(orig_subs)} original submissions mapped against {len(missing_subs)} Missing-Docs submissions).

## Matching Results

| Original Submission | Missing Docs Submission | Match Method | Confidence |
|---|---|---|---|
"""
    for r in report_rows:
        report_content += f"| {r['orig']} | {r['missing']} | {r['method']} | {r['confidence']} |\n"
        
    report_content += "\n\n## Analysis of Results\n"
    if report_rows:
        report_content += f"Successfully matched **{len(report_rows)}** submissions between the two forms.\n"
        # Count match types
        mzk_cnt = sum(1 for r in report_rows if "MZK" in r["method"])
        id_cnt = sum(1 for r in report_rows if "ID" in r["method"])
        email_phone_cnt = sum(1 for r in report_rows if "Email + Phone" in r["method"])
        report_content += f"- **MZK Matches (1.0 Confidence)**: {mzk_cnt}\n"
        report_content += f"- **ID Matches / ID + Email / ID + Phone (0.9 - 0.95 Confidence)**: {id_cnt}\n"
        report_content += f"- **Email + Phone Matches (0.8 Confidence)**: {email_phone_cnt}\n"
    else:
        report_content += "No matches found in the fetched sample.\n"
        
    # Write to artifacts
    report_path = Path("C:/Users/SAIF/.gemini/antigravity/brain/640b28ff-3c4e-44e8-8144-5a82b5a1366d/phase9b_reconciliation_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_content)
    print(f"\nSaved report to {report_path}")

if __name__ == "__main__":
    main()
