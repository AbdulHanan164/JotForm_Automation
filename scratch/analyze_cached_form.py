import json
from pathlib import Path

def main():
    with open("scratch/missing_docs_form_definition.json", encoding="utf-8") as f:
        defn = json.load(f)
        
    questions = defn.get("questions", {})
    
    out_lines = []
    out_lines.append("=== FORM FIELDS INVENTORY ===")
    
    # Sort questions by QID as integer if possible
    sorted_qids = sorted(questions.keys(), key=lambda x: int(x) if x.isdigit() else 999)
    
    for qid in sorted_qids:
        q = questions[qid]
        qtype = q.get("type", "")
        # Get label/text/name
        label = q.get("text") or q.get("label") or q.get("name") or ""
        # Clean label of HTML tags
        import re
        label_clean = re.sub(r'<[^>]+>', '', label).strip()
        label_clean = label_clean.replace("\xa0", " ").replace("\n", " ")
        if len(label_clean) > 80:
            label_clean = label_clean[:80] + "..."
            
        required = q.get("required") == "Yes" or q.get("required") is True or q.get("required") == "true"
        
        # Check if it's an upload field
        upload_field = qtype in ("control_fileupload", "control_widget")
        if not upload_field and "upload" in qtype.lower():
            upload_field = True
            
        name = q.get("name", "")
        
        out_lines.append(f"QID: {qid} | Name: '{name}' | Type: {qtype} | Required: {required} | Upload: {upload_field} | Label: '{label_clean}'")
        
    # Write to file
    with open("scratch/missing_docs_inventory.txt", "w", encoding="utf-8") as out_f:
        out_f.write("\n".join(out_lines))
    print("Inventory saved to scratch/missing_docs_inventory.txt")

    # Let's inspect submissions answers keys
    try:
        with open("scratch/missing_docs_submissions.json", encoding="utf-8") as sf:
            subs = json.load(sf)
        if subs:
            sub_lines = []
            sub_lines.append(f"=== SUBMISSIONS INVENTORY (Count: {len(subs)}) ===")
            for i, s in enumerate(subs[:3]):
                sub_lines.append(f"\n--- Submission {i+1}: {s.get('id')} ({s.get('created_at')}) ---")
                answers = s.get("answers", {})
                for qid in sorted(answers.keys(), key=lambda x: int(x) if x.isdigit() else 999):
                    ans = answers[qid]
                    val = ans.get("answer")
                    name = ans.get("name")
                    text = ans.get("text")
                    # Clean text
                    text_clean = re.sub(r'<[^>]+>', '', text or "").strip()
                    if len(text_clean) > 80:
                        text_clean = text_clean[:80] + "..."
                    sub_lines.append(f"  QID: {qid} | Name: '{name}' | Text: '{text_clean}' | Value: {val}")
            with open("scratch/missing_docs_subs_details.txt", "w", encoding="utf-8") as out_sub:
                out_sub.write("\n".join(sub_lines))
            print("Submission details saved to scratch/missing_docs_subs_details.txt")
    except Exception as e:
        print(f"Error processing submissions: {e}")

if __name__ == "__main__":
    main()
