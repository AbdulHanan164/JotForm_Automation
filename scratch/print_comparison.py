import json
import sys
from pathlib import Path
from unittest.mock import patch

# Set PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.integrations.jotform.client import JotFormClient
from app.pipeline.orchestrator import run_pipeline
from scratch.phase8_comparison import translate_answers_to_webhook_format

def main():
    client = JotFormClient(settings.jotform_api_key)
    submissions = [
        {"id": "6576090039399552136", "name": "Jerusalem Landlord"},
        {"id": "6576153571475451849", "name": "Tel Aviv Partner"},
        {"id": "6575109173857311701", "name": "Ramat Gan Tenant"},
        {"id": "6568173356277189497", "name": "Holon Tenant"},
        {"id": "6574256205426857803", "name": "Landlord Arik Shemesh"},
        {"id": "6572533925111487879", "name": "Married Couple Fishof"}
    ]
    
    print("| Submission | Missing Before | Missing After | Removed | Added |")
    print("|---|---|---|---|---|")
    
    for sub in submissions:
        sub_id = sub["id"]
        name = sub["name"]
        
        sub_detail = client.get_submission(sub_id)
        form_id = sub_detail.get("form_id", "")
        answers = sub_detail.get("answers", {})
        
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
        
        # Run legacy (before)
        with patch("app.pipeline.schema_loader.get_schema", return_value=None):
            res_before = run_pipeline(raw_fields, "multipart/form-data", {})
            
        # Run evaluator (after)
        res_after = run_pipeline(raw_fields, "multipart/form-data", {})
        
        before_missing = res_before.missing_info_labels + res_before.missing_doc_labels
        after_missing = res_after.missing_info_labels + res_after.missing_doc_labels
        
        removed = [x for x in before_missing if x not in after_missing]
        added = [x for x in after_missing if x not in before_missing]
        
        bm_str = ", ".join(before_missing) if before_missing else "(none)"
        am_str = ", ".join(after_missing) if after_missing else "(none)"
        rem_str = ", ".join(removed) if removed else "(none)"
        add_str = ", ".join(added) if added else "(none)"
        
        print(f"| {name} ({sub_id}) | {bm_str} | {am_str} | {rem_str} | {add_str} |")

if __name__ == "__main__":
    main()
