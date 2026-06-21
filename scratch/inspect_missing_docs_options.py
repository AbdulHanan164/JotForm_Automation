import json
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

with open("scratch/missing_docs_form_definition.json", encoding="utf-8") as f:
    defn = json.load(f)

questions = defn.get("questions", {})
checkbox_qids = ["311", "317", "318", "320", "321", "322", "323"]

for qid in checkbox_qids:
    q = questions.get(qid)
    if not q:
        continue
    label = q.get("text") or q.get("label") or ""
    label_clean = re.sub(r'<[^>]+>', '', label).strip()
    options = q.get("options", "")
    print(f"QID: {qid} | Label: {label_clean}")
    print(f"Options: {options}")
    print("-" * 50)
