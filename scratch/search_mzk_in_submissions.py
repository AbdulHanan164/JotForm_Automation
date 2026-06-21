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
    
    with open("scratch/missing_docs_submissions.json", encoding="utf-8") as f:
        missing_subs = json.load(f)
        
    arnona_form_id = "250201745267957"
    orig_subs = client.get_submissions(arnona_form_id, limit=50)
    
    print("=== MISSING DOCS SUBMISSIONS (Sample) ===")
    missing_mzk_list = []
    missing_id_list = []
    for sub in missing_subs[:5]:
        answers = sub.get("answers", {})
        mzk = answers.get("184", {}).get("answer") or answers.get("291", {}).get("answer")
        id_val = answers.get("32", {}).get("answer")
        email = answers.get("30", {}).get("answer")
        phone = answers.get("208", {}).get("answer")
        missing_mzk_list.append(mzk)
        missing_id_list.append(id_val)
        print(f"SubID: {sub['id']} | MZK: {mzk} | ID: {id_val} | Email: {email} | Phone: {phone}")
        
    print("\n=== ORIGINAL SUBMISSIONS (Sample) ===")
    orig_mzk_list = []
    orig_id_list = []
    for sub in orig_subs[:10]:
        answers = sub.get("answers", {})
        # Let's search for keys mapping to MZK ref, ID, Email, Phone
        # 184 / 291 or 264 in original? No, let's see how original stores MZK ref.
        # In original form, QID 291 is uniqueId (MZK Reference)
        mzk = answers.get("291", {}).get("answer") or answers.get("184", {}).get("answer")
        id_val = answers.get("32", {}).get("answer")
        email = answers.get("30", {}).get("answer")
        phone = answers.get("208", {}).get("answer")
        orig_mzk_list.append(mzk)
        orig_id_list.append(id_val)
        print(f"SubID: {sub['id']} | MZK: {mzk} | ID: {id_val} | Email: {email} | Phone: {phone}")
        
    print(f"\nMissing MZK list: {missing_mzk_list}")
    print(f"Original MZK list (first 10): {orig_mzk_list}")
    print(f"Intersection of MZK: {set(missing_mzk_list).intersection(set(orig_mzk_list))}")
    print(f"Intersection of ID: {set(missing_id_list).intersection(set(orig_id_list))}")

if __name__ == "__main__":
    main()
