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
    
    # 1. Collect submissions
    # Local files
    local_files = list(Path("data/submissions").glob("*.json"))
    local_queue = list(Path("data/review_queue").glob("*.json"))
    
    submission_payloads = []
    
    # Fetch from JotForm API to get a rich production dataset (latest 50 submissions)
    print("Fetching recent submissions from JotForm API...")
    try:
        api_subs = client.get_submissions("250201745267957", limit=50)
        for s in api_subs:
            submission_payloads.append({
                "source": "api",
                "id": s["id"],
                "form_id": s["form_id"],
                "answers": s.get("answers", {})
            })
        print(f"Fetched {len(api_subs)} submissions from API.")
    except Exception as e:
        print(f"Warning: failed to fetch from API: {e}")

    # Process local submissions files
    for p in local_files + local_queue:
        if p.name == ".gitkeep":
            continue
        try:
            with p.open("r", encoding="utf-8") as f:
                data = json.load(f)
            
            # Check if it is a PipelineResult dump or a raw webhook payload
            if "_raw_request" in data: # PipelineResult dump
                sub_id = data.get("submission_id", "unknown")
                form_id = data.get("form_id", "")
                raw_req = data.get("_raw_request", {})
                submission_payloads.append({
                    "source": f"local_{p.parent.name}",
                    "id": sub_id,
                    "form_id": form_id,
                    "answers": raw_req
                })
            elif "answers" in data: # API-like structure
                submission_payloads.append({
                    "source": f"local_{p.parent.name}",
                    "id": data.get("id") or data.get("submission_id") or "unknown",
                    "form_id": data.get("form_id", ""),
                    "answers": data.get("answers", {})
                })
            elif "submissionID" in data: # raw webhook payload
                submission_payloads.append({
                    "source": f"local_{p.parent.name}",
                    "id": data.get("submissionID"),
                    "form_id": data.get("formID", ""),
                    "answers": data
                })
        except Exception as e:
            print(f"Failed to read local file {p}: {e}")

    # Remove duplicates by ID
    unique_subs = {}
    for s in submission_payloads:
        sub_id = s["id"]
        if sub_id and sub_id != "unknown":
            unique_subs[sub_id] = s
            
    submissions_to_test = list(unique_subs.values())
    
    total_tested = 0
    total_changed = 0
    total_unchanged = 0
    false_pos_removed = set()
    false_pos_added = set()
    
    print(f"\nRunning regression verification on {len(submissions_to_test)} submissions...")
    
    for sub in submissions_to_test:
        sub_id = sub["id"]
        form_id = sub["form_id"]
        answers = sub["answers"]
        
        # Ensure it belongs to the arnona form
        if form_id != "250201745267957" and form_id != "":
            continue
            
        webhook_fields = translate_answers_to_webhook_format(answers)
        
        raw_fields = {
            "submissionID": sub_id,
            "formID": "250201745267957",
            "formTitle": "העברת חשבון ארנונה",
            "rawRequest": json.dumps(webhook_fields, ensure_ascii=False),
            **webhook_fields
        }
        
        # Run before
        with patch("app.pipeline.schema_loader.get_schema", return_value=None):
            result_before = run_pipeline(raw_fields, "multipart/form-data", {})
            
        # Run after
        result_after = run_pipeline(raw_fields, "multipart/form-data", {})
        
        before_info = set(result_before.missing_info_labels)
        after_info = set(result_after.missing_info_labels)
        
        removed = before_info - after_info
        added = after_info - before_info
        
        total_tested += 1
        if removed or added:
            total_changed += 1
            false_pos_removed.update(removed)
            false_pos_added.update(added)
        else:
            total_unchanged += 1

    print("\n=== REGRESSION VERIFICATION RESULTS ===")
    print(f"Records Tested  : {total_tested}")
    print(f"Records Changed : {total_changed}")
    print(f"Records Unchanged: {total_unchanged}")
    print(f"False Positives Removed: {list(false_pos_removed)}")
    print(f"False Positives Added  : {list(false_pos_added)}")

if __name__ == "__main__":
    main()
