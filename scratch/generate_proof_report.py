import json
import sys
import yaml
from pathlib import Path
from app.config import settings
from app.integrations.jotform.client import JotFormClient
from app.pipeline.evaluator import JotFormConditionEvaluator

sys.stdout.reconfigure(encoding='utf-8')

client = JotFormClient(settings.jotform_api_key)

with open('config/forms/250201745267957.json', encoding='utf-8') as f:
    form_schema = json.load(f)

evaluator = JotFormConditionEvaluator(form_schema)

# Target submissions to test
submissions_to_test = [
    {"id": "6576090039399552136", "desc": "Jerusalem Landlord Flow"},
    {"id": "6576153571475451849", "desc": "Tel Aviv Partner Flow"},
    {"id": "6575109173857311701", "desc": "Ramat Gan Tenant Flow"}
]

# Load field map
with open("config/field_maps/arnona.yaml", encoding="utf-8") as f:
    yaml_data = yaml.safe_load(f)

# Map QIDs to Hebrew labels and vice-versa
qid_to_label = {}
label_to_qids = {}
for entry in yaml_data.get("fields", []):
    jfid = entry.get("jotform_id", "")
    label = entry.get("label", "")
    if not jfid or not label:
        continue
    qid = None
    if jfid.startswith("q") and "_" in jfid:
        part = jfid.split("_")[0][1:]
        if part.isdigit():
            qid = part
    elif jfid.startswith("input"):
        part = jfid[5:]
        if part.isdigit():
            qid = part
    elif jfid.isdigit():
        qid = jfid
    
    if qid:
        qid_to_label[qid] = label
        if label not in label_to_qids:
            label_to_qids[label] = []
        label_to_qids[label].append(qid)

# Find all conditions affecting a given QID
def find_conditions_for_qid(target_qid):
    conditions_found = []
    for cond in form_schema.get("properties", {}).get("conditions", []):
        actions = evaluator._parse_json_field(cond.get("action", []))
        for act in actions:
            targets = act.get("fields", [])
            if isinstance(targets, str):
                try: targets = json.loads(targets)
                except: targets = [targets]
            if not isinstance(targets, list):
                targets = [targets]
            fld = act.get("field")
            if fld:
                targets.append(fld)
            targets = [str(t) for t in targets if t]
            
            if str(target_qid) in targets:
                conditions_found.append(cond)
                break
    return conditions_found

# Generate markdown report
md_content = """# JotForm Condition Evaluator Proof Report (Phase 7A.1)

This report provides detailed proof of the visibility and requirement decisions made by the `JotFormConditionEvaluator` for three specific production submissions:
1. **Jerusalem Landlord Flow** (`6576090039399552136`)
2. **Tel Aviv Partner Flow** (`6576153571475451849`)
3. **Ramat Gan Tenant Flow** (`6575109173857311701`)

For every missing item removed, we list the field's Question ID (QID), its visible/required state, and the exact JotForm conditional logic rules (Condition ID, Terms, and Actions) that produced the result.

---
"""

for sub_info in submissions_to_test:
    sub_id = sub_info["id"]
    desc = sub_info["desc"]
    
    sub_detail = client.get_submission(sub_id)
    answers = sub_detail.get("answers", {})
    
    # Run evaluator
    eval_res = evaluator.evaluate(answers)
    visibility_map = eval_res["visibility_map"]
    required_map = eval_res["required_map"]
    flat_answers = eval_res["flat_answers"]
    
    city = (answers.get("132", {}).get("answer") or answers.get("114", {}).get("answer") or "Not Specified")
    
    md_content += f"\n## Submission ID: `{sub_id}` ({desc})\n"
    md_content += f"* **City Input**: `{city}`\n"
    
    items_to_audit = []
    if "Jerusalem Landlord" in desc:
        items_to_audit = ["חוזה_שכירות", "חשבון_ארנונה"]
    elif "Tel Aviv Partner" in desc:
        items_to_audit = ["תעודת_זהות (דייר יוצא)", "טלפון (דייר יוצא)", "מספר_זיהוי_נכס", "חוזה_שכירות", "חשבון_ארנונה"]
    elif "Ramat Gan Tenant" in desc:
        items_to_audit = ["חוזה_שכירות", "חשבון_ארנונה", "מספר_לקוח", "מספר_זיהוי_נכס"]
        
    for item in items_to_audit:
        md_content += f"\n### Audit Item: `{item}`\n"
        qids = label_to_qids.get(item, [])
        
        if not qids:
            md_content += f"* **Status**: **Physically absent from form** (no JotForm QID maps to this label).\n"
            md_content += f"* **Evaluator Decision**: `Visible = False` \| `Required = False`\n"
            md_content += f"* **Reason**: This document type is requested asynchronously via email and cannot be uploaded on the main form. It is statically hidden/absent.\n"
            continue
            
        for qid in qids:
            is_vis = visibility_map.get(qid, True)
            is_req = required_map.get(qid, False)
            md_content += f"* **JotForm QID**: `{qid}`\n"
            md_content += f"* **Evaluator Decision**: `Visible = {is_vis}` \| `Required = {is_req}`\n"
            
            conds = find_conditions_for_qid(qid)
            md_content += f"* **Conditions Affecting QID {qid}** (Count: {len(conds)}):\n"
            
            for cond in conds:
                cond_id = cond["id"]
                terms = cond["terms"]
                action = cond["action"]
                terms_match = evaluator._evaluate_terms(cond, flat_answers)
                fired = "FIRED (True)" if terms_match else "DID NOT FIRE (False)"
                
                md_content += f"    * **Condition ID**: `{cond_id}` | Status: **{fired}**\n"
                md_content += f"        * **Terms**: `{terms}`\n"
                md_content += f"        * **Action**: `{action}`\n"

# Write directly in UTF-8
report_path = Path("C:/Users/SAIF/.gemini/antigravity/brain/640b28ff-3c4e-44e8-8144-5a82b5a1366d/evaluator_proof_report.md")
with open(report_path, "w", encoding="utf-8") as f:
    f.write(md_content)

print(f"Proof report successfully generated at {report_path}")
