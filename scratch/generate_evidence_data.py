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
        {"id": "6576090039399552136", "name": "Jerusalem Landlord"},
        {"id": "6576153571475451849", "name": "Tel Aviv Partner"},
        {"id": "6575109173857311701", "name": "Ramat Gan Tenant"}
    ]
    
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
        
        result = run_pipeline(raw_fields, "multipart/form-data", {})
        eval_res = result.evaluator_result
        
        print(f"### Submission: {name} ({sub_id})")
        
        # 1. Evaluator visibility output (first 10 hidden and first 10 visible QIDs for brevity/proof)
        visibility_map = eval_res.get("visibility_map", {})
        visible_qids = eval_res.get("visible_fields", [])
        hidden_qids = eval_res.get("hidden_fields", [])
        
        print(f"- **Evaluator Visibility Output Summary**:")
        print(f"  - Total QIDs evaluated: {len(visibility_map)}")
        print(f"  - Total Visible QIDs: {len(visible_qids)} (e.g., {visible_qids[:10]}...) ")
        print(f"  - Total Hidden QIDs: {len(hidden_qids)} (e.g., {hidden_qids[:10]}...) ")
        
        # 2. Canonical section used, active QIDs, and final visibility decision for key fields
        audit_records = eval_res.get("label_visibility_audit", [])
        # sort by label
        audit_records = sorted(audit_records, key=lambda x: x["label"])
        
        print(f"- **Active QIDs, Canonical Sections, and Final Decisions per Label**:")
        print("  | Label (Hebrew) | Canonical Section Used | Active QIDs | Visible QIDs | Final Visibility Decision |")
        print("  |---|---|---|---|---|")
        for record in audit_records:
            lbl = record["label"]
            sec = record["section"]
            canon = record["canonical_section_used"]
            act = record["active_qids"]
            vis = record["visible_qids"]
            dec = record["final_visibility_decision"]
            print(f"  | {lbl} | `{canon}` | `{act}` | `{vis}` | **{dec}** |")
        print("\n" + "="*80 + "\n")

if __name__ == "__main__":
    main()
