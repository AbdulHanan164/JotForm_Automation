import json
import sys
from pathlib import Path

# Set PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.integrations.jotform.client import JotFormClient
from app.pipeline.orchestrator import run_pipeline
from scratch.phase8_comparison import translate_answers_to_webhook_format

def main():
    client = JotFormClient(settings.jotform_api_key)
    submissions = [
        {"id": "6576090039399552136", "flow": "Jerusalem Landlord"},
        {"id": "6576153571475451849", "flow": "Tel Aviv Partner"},
        {"id": "6575109173857311701", "flow": "Ramat Gan Tenant"}
    ]
    
    for sub in submissions:
        sub_id = sub["id"]
        flow = sub["flow"]
        print(f"=== {flow} ({sub_id}) ===")
        
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
        
        result = run_pipeline(raw_fields, "multipart/form-data", {})
        eval_res = result.evaluator_result
        
        # We need to print label visibility audit records
        audit_records = eval_res.get("label_visibility_audit", [])
        
        # Sort by label for consistent output
        audit_records = sorted(audit_records, key=lambda x: x["label"])
        
        # Focus on multi-section labels or key labels
        target_labels = ["אימייל", "טלפון", "מספר_לקוח", "מספר_נכס", "שם_משפחה", "שם_פרטי", "תעודת_זהות"]
        
        print(f"{'Label':<15} | {'Section':<10} | {'Canonical':<10} | {'Active QIDs':<12} | {'Visible QIDs':<12} | {'Decision':<8}")
        print("-" * 75)
        for record in audit_records:
            lbl = record["label"]
            if lbl not in target_labels:
                continue
            sec = record["section"]
            canon = record["canonical_section_used"]
            act = str(record["active_qids"])
            vis = str(record["visible_qids"])
            dec = str(record["final_visibility_decision"])
            print(f"{lbl:<15} | {sec:<10} | {canon:<10} | {act:<12} | {vis:<12} | {dec:<8}")
        print("\n")

if __name__ == "__main__":
    main()
