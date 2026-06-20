import json
import logging
import sys
from pathlib import Path
from unittest.mock import patch

# Set PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.integrations.jotform.client import JotFormClient
from app.pipeline.orchestrator import run_pipeline
from app.services.arnona.field_map import FIELD_MAP
from app.pipeline.evaluator import _extract_qid

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("comparison")

sys.stdout.reconfigure(encoding='utf-8')

def translate_answers_to_webhook_format(answers: dict) -> dict:
    # Map QID -> jotform_id from FIELD_MAP
    qid_to_jfid = {}
    for jfid in FIELD_MAP.keys():
        qid = _extract_qid(jfid)
        if qid:
            qid_to_jfid[qid] = jfid
            
    # Flatten answers if they are in the API structure
    flat_answers = {}
    for qid, ans in answers.items():
        if isinstance(ans, dict):
            val = ans.get("answer")
            if val is not None:
                flat_answers[str(qid)] = val
        else:
            flat_answers[str(qid)] = ans
            
    # Build webhook format fields
    webhook_fields = {}
    for qid, val in flat_answers.items():
        jfid = qid_to_jfid.get(qid)
        if jfid:
            webhook_fields[jfid] = val
        else:
            # Fallback
            webhook_fields[f"q{qid}"] = val
            
    return webhook_fields

def main():
    client = JotFormClient(settings.jotform_api_key)
    
    submissions_to_test = [
        {"id": "6576090039399552136", "flow": "Jerusalem Landlord"},
        {"id": "6576153571475451849", "flow": "Tel Aviv Partner"},
        {"id": "6575109173857311701", "flow": "Ramat Gan Tenant"},
        {"id": "6568173356277189497", "flow": "Holon Tenant"},
        {"id": "6574256205426857803", "flow": "Landlord Arik Shemesh"},
        {"id": "6572533925111487879", "flow": "Married Couple Fishof"}
    ]
    
    info_rows = []
    docs_rows = []
    regressions_found = False
    
    print("Fetching and processing submissions...")
    for sub in submissions_to_test:
        sub_id = sub["id"]
        flow = sub["flow"]
        print(f"  Processing {flow} ({sub_id})...")
        
        try:
            sub_detail = client.get_submission(sub_id)
        except Exception as e:
            print(f"Failed to fetch submission {sub_id}: {e}")
            continue
            
        form_id = sub_detail.get("form_id", "")
        answers = sub_detail.get("answers", {})
        
        # We need form title to construct envelope
        try:
            form_def = client._get(f"/form/{form_id}")
            form_title = form_def.get("title", "")
        except Exception:
            form_title = "העברת חשבון ארנונה"
            
        webhook_fields = translate_answers_to_webhook_format(answers)
        
        raw_fields = {
            "submissionID": sub_id,
            "formID": form_id,
            "formTitle": form_title,
            "rawRequest": json.dumps(webhook_fields, ensure_ascii=False),
            **webhook_fields
        }
        
        # 1. Run pipeline before (legacy engine fallback)
        with patch("app.pipeline.schema_loader.get_schema", return_value=None):
            result_before = run_pipeline(raw_fields, "multipart/form-data", {})
            
        # 2. Run pipeline after (evaluator integration)
        result_after = run_pipeline(raw_fields, "multipart/form-data", {})
        
        # Compute differences for info
        before_info = set(result_before.missing_info_labels)
        after_info = set(result_after.missing_info_labels)
        removed_info = before_info - after_info
        added_info = after_info - before_info
        
        # Compute differences for docs
        before_docs = set(result_before.missing_doc_labels)
        after_docs = set(result_after.missing_doc_labels)
        removed_docs = before_docs - after_docs
        added_docs = after_docs - before_docs
        
        info_rows.append({
            "id": sub_id,
            "flow": flow,
            "before": list(before_info),
            "after": list(after_info),
            "removed": list(removed_info),
            "added": list(added_info)
        })
        
        docs_rows.append({
            "id": sub_id,
            "flow": flow,
            "before": list(before_docs),
            "after": list(after_docs),
            "removed": list(removed_docs),
            "added": list(added_docs)
        })
        
        if added_info or added_docs or removed_docs:
            regressions_found = True

    # Print Info Table
    print("\n### Info Comparison Table")
    print("| Submission ID | Flow | Missing Before | Missing After | Removed (✅ fixed) | Added (⚠️ regression) |")
    print("|---|---|---|---|---|---|")
    for row in info_rows:
        before_str = ", ".join(row["before"]) or "(none)"
        after_str = ", ".join(row["after"]) or "(none)"
        removed_str = ", ".join(row["removed"]) or "(none)"
        added_str = ", ".join(row["added"]) or "(none)"
        if row["added"]:
            added_str = f"⚠️ **{added_str}**"
        print(f"| `{row['id']}` | {row['flow']} | {before_str} | {after_str} | {removed_str} | {added_str} |")

    # Print Docs Table
    print("\n### Docs Comparison Table")
    print("| Submission ID | Flow | Missing Before | Missing After | Removed (⚠️ regression) | Added (⚠️ regression) |")
    print("|---|---|---|---|---|---|")
    for row in docs_rows:
        before_str = ", ".join(row["before"]) or "(none)"
        after_str = ", ".join(row["after"]) or "(none)"
        removed_str = ", ".join(row["removed"]) or "(none)"
        added_str = ", ".join(row["added"]) or "(none)"
        if row["added"] or row["removed"]:
            added_str = f"⚠️ **{added_str}**"
            removed_str = f"⚠️ **{removed_str}**"
        print(f"| `{row['id']}` | {row['flow']} | {before_str} | {after_str} | {removed_str} | {added_str} |")

    if regressions_found:
        print("\n❌ REGRESSIONS DETECTED! Run validation failed.")
        sys.exit(1)
    else:
        print("\n✅ VALIDATION PASSED. No regressions detected.")
        sys.exit(0)

if __name__ == "__main__":
    main()
