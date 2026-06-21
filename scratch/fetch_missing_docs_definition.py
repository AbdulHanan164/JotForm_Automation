import json
import sys
from pathlib import Path

# Set PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.integrations.jotform.client import JotFormClient

sys.stdout.reconfigure(encoding='utf-8')

def main():
    client = JotFormClient(settings.jotform_api_key)
    form_id = "251323124205946"
    
    print(f"Fetching definition for form {form_id}...")
    try:
        defn = client.get_form_definition(form_id, force=True)
        # Save to scratch folder for analysis
        scratch_dir = Path("scratch")
        scratch_dir.mkdir(exist_ok=True)
        with open(scratch_dir / "missing_docs_form_definition.json", "w", encoding="utf-8") as f:
            json.dump(defn, f, ensure_ascii=False, indent=2)
        print("Successfully saved form definition to scratch/missing_docs_form_definition.json")
    except Exception as e:
        print(f"Error fetching form definition: {e}")
        return

    # Print out all fields (questions)
    questions = defn.get("questions", {})
    print("\n=== FIELD INVENTORY ===")
    for qid, q in sorted(questions.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 999):
        qtype = q.get("type", "")
        text = q.get("text") or q.get("label") or q.get("name") or ""
        required = q.get("required") == "Yes" or q.get("required") is True
        upload_field = qtype in ("control_fileupload", "control_widget") # check if it supports upload
        name = q.get("name", "")
        print(f"QID: {qid} | Label/Text: '{text}' | Name: '{name}' | Type: {qtype} | Required: {required} | Upload Field: {upload_field}")
        
    print("\nFetching recent submissions for form...")
    try:
        subs = client.get_submissions(form_id, limit=20)
        with open(scratch_dir / "missing_docs_submissions.json", "w", encoding="utf-8") as f:
            json.dump(subs, f, ensure_ascii=False, indent=2)
        print(f"Successfully saved {len(subs)} submissions to scratch/missing_docs_submissions.json")
        
        if subs:
            print("\n=== SAMPLE SUBMISSION STRUCTURE ===")
            sample = subs[0]
            print(f"Submission ID: {sample.get('id')}")
            print(f"Created At: {sample.get('created_at')}")
            print("Answers keys & values:")
            for qid, ans in sorted(sample.get("answers", {}).items(), key=lambda x: int(x[0]) if x[0].isdigit() else 999):
                print(f"  QID: {qid} | Name: '{ans.get('name')}' | Text: '{ans.get('text')}' | Answer: {ans.get('answer')}")
    except Exception as e:
        print(f"Error fetching submissions: {e}")

if __name__ == "__main__":
    main()
