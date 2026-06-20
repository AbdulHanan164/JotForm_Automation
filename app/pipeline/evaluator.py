import json
import logging
import re
from typing import Any

logger = logging.getLogger("webhook")


LABEL_CANONICAL_SECTION: dict[str, str] = {
    # Person fields — canonical = customer (incoming tenant)
    "שם_פרטי":   "customer",   # QID 21
    "שם_משפחה":  "customer",   # QID 20
    "טלפון":     "customer",   # QID 208
    "אימייל":    "customer",   # QID 30
    "תעודת_זהות": "customer",  # QID 32 (personal ID number, not doc upload)

    # Account number fields — canonical = arnona
    "מספר_לקוח":       "arnona",  # QID 136
    "מספר_נכס":        "arnona",  # QIDs 135, 137
    "מספר_זיהוי_נכס":  "arnona",  # QID 264  (single-section, listed for explicitness)
    "מספר_חשבון_תושב": "arnona",  # QID 63   (single-section, listed for explicitness)
    "מספר_חשבון_לקוח": "arnona",  # QID 64   (single-section, listed for explicitness)
}


def _extract_qid(jotform_id: str) -> str:
    """
    Extracts numerical QID from jotform_id.
    e.g. "q136_input136" -> "136"
    e.g. "136" -> "136"
    """
    if not jotform_id:
        return ""
    jotform_id = str(jotform_id)
    if jotform_id.isdigit():
        return jotform_id
    if jotform_id.startswith("q") and "_" in jotform_id:
        part = jotform_id.split("_")[0][1:]
        if part.isdigit():
            return part
    if jotform_id.startswith("input"):
        part = jotform_id[5:]
        if part.isdigit():
            return part
    
    m = re.search(r'\d+', jotform_id)
    if m:
        return m.group(0)
    return jotform_id


def build_label_visibility(
    visibility_map: dict[str, bool],
    field_map:      dict[str, dict],
    flat_answers:   dict[str, Any],
) -> tuple[dict[str, bool], dict[str, list[str]], list[dict[str, Any]]]:
    """
    Translates QID visibility into Hebrew label visibility using the Active-QID
    selection algorithm and section-primary resolution.

    Returns:
        label_visibility: {hebrew_label: bool}
        active_qids:      {hebrew_label: [qid, ...]}  — for audit
        audit_records:    list of dicts containing audit information per label
    """
    # Group QID candidates by label and section
    label_groups: dict[str, dict[str, list[dict]]] = {}
    
    for jotform_id, mapping in field_map.items():
        label = mapping.get("label")
        section = mapping.get("section", "")
        if not label:
            continue
            
        qid = _extract_qid(jotform_id)
        val = flat_answers.get(qid, "")
        
        # Check if the field has a non-empty value in submission
        has_value = False
        if val is not None:
            if isinstance(val, (list, tuple)):
                has_value = len(val) > 0
            elif isinstance(val, dict):
                has_value = any(str(v).strip() for v in val.values() if v is not None)
            else:
                s_val = str(val).strip()
                has_value = bool(s_val and s_val not in ("None", "null", ""))
        
        is_visible = visibility_map.get(qid, True)
        
        if label not in label_groups:
            label_groups[label] = {}
        if section not in label_groups[label]:
            label_groups[label][section] = []
            
        label_groups[label][section].append({
            "qid": qid,
            "has_value": has_value,
            "is_visible": is_visible,
            "section": section
        })

    label_visibility = {}
    active_qids_out = {}
    audit_records = []
    
    for label, sections in label_groups.items():
        canonical_section = LABEL_CANONICAL_SECTION.get(label)
        
        # Filter sections if canonical is defined
        if canonical_section and canonical_section in sections:
            relevant_qids_info = sections[canonical_section]
            canonical_used = canonical_section
        else:
            relevant_qids_info = []
            for sec_qids in sections.values():
                relevant_qids_info.extend(sec_qids)
            canonical_used = None
            
        active_info = [info for info in relevant_qids_info if info["has_value"]]
        passive_info = [info for info in relevant_qids_info if not info["has_value"]]
        
        active_qids = [info["qid"] for info in active_info]
        active_qids_out[label] = active_qids
        
        if active_info:
            visible = all(info["is_visible"] for info in active_info)
        else:
            visible = any(info["is_visible"] for info in passive_info)
            
        label_visibility[label] = visible
        
        # Audit compilation
        visible_qids = [info["qid"] for info in relevant_qids_info if info["is_visible"]]
        all_qids = [info["qid"] for info in relevant_qids_info]
        
        # Derive section string
        sections_list = list(set(info["section"] for info in relevant_qids_info))
        section_str = sections_list[0] if len(sections_list) == 1 else ",".join(sections_list)
        
        audit_records.append({
            "section": section_str,
            "label": label,
            "active_qids": active_qids,
            "visible_qids": visible_qids,
            "canonical_section_used": canonical_used or "none",
            "final_visibility_decision": visible
        })
        
    return label_visibility, active_qids_out, audit_records


def format_terms_summary(cond: dict) -> str:
    terms_raw = cond.get("terms", "[]")
    if isinstance(terms_raw, str):
        try:
            terms = json.loads(terms_raw)
        except:
            terms = []
    else:
        terms = terms_raw
        
    if not isinstance(terms, list):
        terms = [terms]
        
    term_strs = []
    for t in terms:
        field = t.get("field", "")
        op = t.get("operator", "")
        val = t.get("value", "")
        term_strs.append(f"field[{field}] {op} '{val}'")
        
    link = cond.get("link", "All")
    if link == "All":
        return " AND ".join(term_strs)
    elif link == "Any":
        return " OR ".join(term_strs)
    elif link == "None":
        return "NOT (" + " AND ".join(term_strs) + ")"
    return " AND ".join(term_strs)


def build_explanations(
    conditions:     list[dict],
    flat_answers:   dict[str, Any],
    visibility_map: dict[str, bool],
    evaluator_instance: Any,
) -> dict[str, list[dict]]:
    """
    For every QID touched by at least one condition, records condition evaluations.
    """
    explanations: dict[str, list[dict]] = {}
    
    for cond in conditions:
        cond_id = str(cond.get("id", ""))
        fired = evaluator_instance._evaluate_terms(cond, flat_answers)
        terms_summary = format_terms_summary(cond)
        
        actions = evaluator_instance._parse_json_field(cond.get("action", []))
        for act in actions:
            vis_type = act.get("visibility", "")
            act_type = act.get("type", "")
            
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
            
            action_name = vis_type or act_type or "Action"
            action_str = f"{action_name} → {targets}"
            
            for t in targets:
                if fired:
                    if vis_type in ("Show", "ShowMultiple") or act_type in ("show", "showmultiple"):
                        effect = "visible"
                    elif vis_type in ("Hide", "HideMultiple") or act_type in ("hide", "hidemultiple"):
                        effect = "hidden"
                    elif vis_type in ("Require", "RequireMultiple") or act_type in ("require", "requiremultiple"):
                        effect = "required"
                    else:
                        effect = "no_change"
                else:
                    if vis_type in ("Require", "RequireMultiple") or act_type in ("require", "requiremultiple"):
                        effect = "unrequired"
                    else:
                        effect = "no_change"
                        
                if t not in explanations:
                    explanations[t] = []
                    
                explanations[t].append({
                    "condition_id": cond_id,
                    "fired": fired,
                    "terms_summary": terms_summary,
                    "action": action_str,
                    "effect": effect
                })
                
    return explanations


class JotFormConditionEvaluator:
    """
    Evaluator for JotForm conditional logic.
    Reads the original Form Schema JSON and evaluates visibility,
    requirement, and calculation copy logic against a submission payload.
    """

    def __init__(self, form_schema: dict):
        self.schema = form_schema
        self.questions = self._extract_questions()
        self.conditions = self._extract_conditions()

    def _extract_questions(self) -> dict:
        qs = self.schema.get("questions", {})
        if "content" in qs:
            qs = qs["content"]
        return qs

    def _extract_conditions(self) -> list:
        return self.schema.get("properties", {}).get("conditions", [])

    def flatten_submission(self, payload: dict) -> dict[str, Any]:
        """
        Flattens a JotForm payload into a standard map of {qid_string: raw_value}.
        """
        flat = {}

        if "answers" in payload and isinstance(payload["answers"], dict):
            for qid, ans in payload["answers"].items():
                if isinstance(ans, dict):
                    val = ans.get("answer")
                    if val is not None:
                        flat[str(qid)] = val
            return flat

        for k, val in payload.items():
            if k.isdigit():
                flat[k] = val
                continue

            if k.startswith("q") and "_" in k:
                part = k.split("_")[0][1:]
                if part.isdigit():
                    flat[part] = val
                    continue

            if k.startswith("input"):
                part = k[5:]
                if part.isdigit():
                    flat[part] = val
                    continue

            if k == "rawRequest" and isinstance(val, str):
                try:
                    rr = json.loads(val)
                    flat.update(self.flatten_submission(rr))
                except Exception:
                    pass

        return flat

    def evaluate(self, submission_payload: dict) -> dict[str, list[str]]:
        """
        Evaluates visibility and requirements.
        """
        flat_answers = self.flatten_submission(submission_payload)

        visibility: dict[str, bool] = {}
        required: dict[str, bool] = {}

        for qid, q in self.questions.items():
            qid_str = str(qid)
            is_hidden = q.get("hidden") in ("Yes", True, "true")
            qtype = q.get("type", "")
            if qtype in ("control_autoincrement", "control_widget") and q.get("name") != "typeA":
                is_hidden = True
            
            visibility[qid_str] = not is_hidden
            required[qid_str] = q.get("required") in ("Yes", True, "true")

        fields_targeted_by_show = set()
        for cond in self.conditions:
            actions = self._parse_json_field(cond.get("action", []))
            for act in actions:
                vis = act.get("visibility", "")
                act_type = act.get("type", "")
                if vis in ("Show", "ShowMultiple") or act_type in ("show", "showmultiple"):
                    targets = act.get("fields", [])
                    if isinstance(targets, str):
                        try: targets = json.loads(targets)
                        except: targets = [targets]
                    if not isinstance(targets, list):
                        targets = [targets]
                    fld = act.get("field")
                    if fld:
                        targets.append(fld)
                    
                    for t in targets:
                        if t:
                            fields_targeted_by_show.add(str(t))

        for qid_str in fields_targeted_by_show:
            visibility[qid_str] = False

        for _ in range(3):
            for cond in self.conditions:
                terms_match = self._evaluate_terms(cond, flat_answers)

                actions = self._parse_json_field(cond.get("action", []))
                for act in actions:
                    self._apply_action(act, terms_match, visibility, required, flat_answers)

        visible_fields = [qid for qid, vis in visibility.items() if vis]
        hidden_fields = [qid for qid, vis in visibility.items() if not vis]
        
        required_fields = [qid for qid, req in required.items() if req and visibility.get(qid, True)]

        doc_qids = {"33", "34", "35", "667", "668", "669", "181"}
        required_documents = [qid for qid in required_fields if qid in doc_qids]

        return {
            "visible_fields": sorted(visible_fields),
            "hidden_fields": sorted(hidden_fields),
            "required_fields": sorted(required_fields),
            "required_documents": sorted(required_documents),
            "visibility_map": visibility,
            "required_map": required,
            "flat_answers": flat_answers
        }

    def _evaluate_terms(self, cond: dict, flat_answers: dict[str, Any]) -> bool:
        terms_raw = cond.get("terms", "[]")
        terms = self._parse_json_field(terms_raw)
        if not terms:
            return False

        link = cond.get("link", "All")
        results = [self._eval_term(t, flat_answers) for t in terms]

        if link == "All":
            return all(results)
        elif link == "Any":
            return any(results)
        elif link == "None":
            return all(not r for r in results)
        return False

    def _eval_term(self, term: dict, flat_answers: dict[str, Any]) -> bool:
        field_id = str(term.get("field", ""))
        operator = term.get("operator", "")
        compare_value = term.get("value", "")

        raw_val = flat_answers.get(field_id, "")
        
        if isinstance(raw_val, list):
            values = [str(v).strip() for v in raw_val]
            str_value = ", ".join(values)
        elif isinstance(raw_val, dict):
            if "year" in raw_val and "month" in raw_val and "day" in raw_val:
                str_value = f"{raw_val['year']}-{raw_val['month']}-{raw_val['day']}"
            else:
                str_value = str(raw_val)
                values = [str_value]
        else:
            str_value = str(raw_val).strip()
            values = [str_value]

        cv = str(compare_value).strip()

        if operator == "equals":
            return str_value == cv
        elif operator == "notEquals":
            return str_value != cv
        elif operator == "contains":
            return cv in str_value or any(cv in v for v in values)
        elif operator == "notContains":
            return cv not in str_value
        elif operator == "isEmpty":
            return not bool(str_value) or str_value in ("None", "null", "")
        elif operator == "isFilled":
            return bool(str_value) and str_value not in ("None", "null", "")
        elif operator in ("greaterThan", "lessThan"):
            try:
                v_num = float(str_value)
                c_num = float(cv)
                if operator == "greaterThan":
                    return v_num > c_num
                return v_num < c_num
            except:
                return False
        elif operator == "startsWith":
            return str_value.startswith(cv)
        elif operator == "endsWith":
            return str_value.endswith(cv)
        return False

    def _apply_action(self, act: dict, terms_match: bool, visibility: dict[str, bool], required: dict[str, bool], flat_answers: dict[str, Any]) -> None:
        vis_type = act.get("visibility", "")
        act_type = act.get("type", "")
        
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

        if vis_type in ("Show", "ShowMultiple") or act_type in ("show", "showmultiple"):
            if terms_match:
                for t in targets:
                    visibility[t] = True
        
        elif vis_type in ("Hide", "HideMultiple") or act_type in ("hide", "hidemultiple"):
            if terms_match:
                for t in targets:
                    visibility[t] = False

        elif vis_type in ("Require", "RequireMultiple") or act_type in ("require", "requiremultiple"):
            if terms_match:
                for t in targets:
                    required[t] = True
            else:
                for t in targets:
                    q_def = self.questions.get(t, {})
                    is_static = q_def.get("required") in ("Yes", True, "true")
                    if not is_static:
                        required[t] = False

        elif act.get("equation") or act_type == "calculation":
            if terms_match:
                result_field = str(act.get("resultField", ""))
                equation = str(act.get("equation", ""))
                if equation.startswith("{") and equation.endswith("}"):
                    src_qid = equation[1:-1]
                    if src_qid in flat_answers:
                        flat_answers[result_field] = flat_answers[src_qid]

    def _parse_json_field(self, val: Any) -> list:
        if not val:
            return []
        if isinstance(val, list):
            return val
        if isinstance(val, str):
            try:
                res = json.loads(val)
                return res if isinstance(res, list) else [res]
            except Exception:
                return []
        return [val]
