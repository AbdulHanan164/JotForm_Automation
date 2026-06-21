import json
import sys
import yaml
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

print("Starting Proof Analysis...")

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
    
    print(f"\n==================== SUBMISSION: {sub_id} ({desc}) ====================")
    
    items_to_audit = []
    if "Jerusalem Landlord" in desc:
        items_to_audit = ["חוזה_שכירות", "חשבון_ארנונה"]
    elif "Tel Aviv Partner" in desc:
        items_to_audit = ["תעודת_זהות (דייר יוצא)", "טלפון (דייר יוצא)", "מספר_זיהוי_נכס", "חוזה_שכירות", "חשבון_ארנונה"]
    elif "Ramat Gan Tenant" in desc:
        items_to_audit = ["חוזה_שכירות", "חשבון_ארנונה", "מספר_לקוח", "מספר_זיהוי_נכס"]
        
    for item in items_to_audit:
        print(f"\n* Item: {item}")
        qids = label_to_qids.get(item, [])
        if not qids:
            print("  -> Status: Physically absent from form (no QID maps to it).")
            print("  -> Visible = False | Required = False")
            print("  -> Reason: Statically hidden (does not exist in form definition).")
            continue
            
        for qid in qids:
            is_vis = visibility_map.get(qid, True)
            is_req = required_map.get(qid, False)
            print(f"  -> QID: {qid} | Visible: {is_vis} | Required: {is_req}")
            
            conds = find_conditions_for_qid(qid)
            print(f"  -> Conditions affecting QID {qid} (Count: {len(conds)}):")
            
            for cond in conds:
                cond_id = cond["id"]
                terms = cond["terms"]
                action = cond["action"]
                terms_match = evaluator._evaluate_terms(cond, flat_answers)
                fired = "FIRED (True)" if terms_match else "DID NOT FIRE (False)"
                
                print(f"     - Cond ID: {cond_id} | Status: {fired}")
                print(f"       Terms : {terms}")
                print(f"       Action: {action}")
