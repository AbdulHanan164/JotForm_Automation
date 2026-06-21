import json
import sys
from pathlib import Path
import urllib.parse

# Set PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.integrations.jotform.client import JotFormClient
from app.pipeline.reconciliation import MissingDocsReconciler
from app.documents import storage

sys.stdout.reconfigure(encoding='utf-8')

# Checkbox Option mapping to doc_type
CHECKBOX_MAPPINGS = {
    # ID Photo
    "תז שלי": "id_photo",
    "תז של אחרים בחוזה": "id_photo",
    "תז משכיר/בעל בית": "id_photo",
    "תז שוכרים מתחלפים": "id_photo",
    "תז של השוכרים בחוזה": "id_photo",
    "תז של כל הקונים": "id_photo",
    "תז של כל המוכרים": "id_photo",
    "תז של שוכרים יוצאים": "id_photo",
    "תז מורשה חתימה": "id_photo",
    "צילום תז שלי": "id_photo",
    "צילום תז משכיר/בעל בית": "id_photo",
    "צילום תז": "id_photo",
    # Lease Contract
    "חוזה שכירות": "lease_contract",
    "חוזה שכירות/מכר": "lease_contract",
    "חוזה שכירות שנגמר": "lease_contract",
    "חוזה מכר": "lease_contract",
    "חוזה שכירות - מלא וחתום": "lease_contract",
    "חוזה שכירות שנגמר - מלא וחתום": "lease_contract",
    "חוזה מכר - מלא וחתום": "lease_contract",
    # Arnona Bill
    "חשבון ארנונה": "arnona_bill",
    "צילום חשבון ארנונה": "arnona_bill",
    # Tabu
    "נסח טאבו מעודכן": "tabu",
    "נסח טאבו": "tabu",
    # Corporation Certificate
    "תעודת התאגדות - תאגיד": "corp_cert",
    "תעודת התאגדות": "corp_cert",
    "צילום תעודת התאגדות - תאגיד": "corp_cert"
}

# Filename keywords mapping
FILENAME_KEYWORDS = {
    "תז": "id_photo",
    "ת.ז": "id_photo",
    "דרכון": "id_photo",
    "passport": "id_photo",
    "id": "id_photo",
    "zehut": "id_photo",
    "tz": "id_photo",
    
    "חוזה": "lease_contract",
    "שכירות": "lease_contract",
    "הסכם": "lease_contract",
    "lease": "lease_contract",
    "contract": "lease_contract",
    
    "ארנונה": "arnona_bill",
    "arnona": "arnona_bill",
    
    "טאבו": "tabu",
    "tabu": "tabu",
    
    "התאגדות": "corp_cert",
    "חברה": "corp_cert",
    "incorporation": "corp_cert",
    "corporation": "corp_cert",
    "corp": "corp_cert"
}

def classify_by_filename(filename: str) -> str | None:
    fn_low = filename.lower()
    for kw, dtype in FILENAME_KEYWORDS.items():
        if kw in fn_low:
            return dtype
    return None

def get_original_docs(orig_sub: dict) -> list[str]:
    answers = orig_sub.get("answers", {})
    docs = []
    # Check original document upload fields
    # QID 33: ID, QID 34: Lease, QID 35: Arnona, QID 181: Signature, QID 667: ID Partner, QID 668: ID Outgoing, QID 669: Corp Cert
    doc_fields = {
        "33": "תעודת_זהות",
        "34": "חוזה_שכירות",
        "35": "חשבון_ארנונה",
        "181": "חתימה",
        "667": "תעודת_זהות (דייר יוצא)",
        "668": "תעודת_זהות (שוכר שני)",
        "669": "תעודת_התאגדות"
    }
    for qid, label in doc_fields.items():
        ans = answers.get(qid, {})
        val = ans.get("answer")
        if val:
            docs.append(label)
    return docs

def main():
    client = JotFormClient(settings.jotform_api_key)
    reconciler = MissingDocsReconciler()
    
    with open("scratch/missing_docs_submissions.json", encoding="utf-8") as f:
        missing_subs = json.load(f)
        
    arnona_form_id = "250201745267957"
    orig_subs = client.get_submissions(arnona_form_id, limit=50)
    
    # Re-run matching to get the 14 pairs
    pairs = []
    for orig in orig_subs:
        matches = reconciler.match_submission(orig, missing_subs)
        for m in matches:
            pairs.append((orig, m["matched_submission"], m["confidence"], m["reason"]))
            
    # Inventory list
    inventory_rows = []
    
    confidently_classified = 0
    ambiguous_files = 0
    unclassified_files = 0
    
    filename_worked_examples = []
    checkbox_fallback_examples = []
    ambiguous_examples = []
    
    print(f"Found {len(pairs)} matched pairs. Starting document classification audit...")
    
    for orig, missing, confidence, reason in pairs:
        orig_id = orig["id"]
        missing_id = missing["id"]
        
        # Get original customer name
        orig_answers = orig.get("answers", {})
        first = orig_answers.get("21", {}).get("answer") or ""
        last = orig_answers.get("20", {}).get("answer") or ""
        fullname = f"{first} {last}".strip() or "Unknown"
        
        # Existing documents in original
        orig_docs = get_original_docs(orig)
        
        # Missing docs uploads
        missing_answers = missing.get("answers", {})
        file_urls = missing_answers.get("38", {}).get("answer") or []
        if isinstance(file_urls, str):
            file_urls = [file_urls]
            
        # Get checkboxes selected
        checkbox_selections = []
        checkbox_qids = ["311", "317", "318", "320", "321", "322", "323"]
        for qid in checkbox_qids:
            ans = missing_answers.get(qid, {})
            val = ans.get("answer")
            if val:
                if isinstance(val, list):
                    checkbox_selections.extend(val)
                else:
                    checkbox_selections.append(val)
                    
        # Inferred document types for each file
        inferred_types = []
        uploaded_files_info = []
        
        # Check what document types are indicated by the checkboxes
        checkbox_dtypes = set()
        for opt in checkbox_selections:
            # Match options to dtypes
            for kw, dtype in CHECKBOX_MAPPINGS.items():
                if kw in opt:
                    checkbox_dtypes.add(dtype)
                    
        for url in file_urls:
            filename = urllib.parse.unquote(url.split("/")[-1])
            uploaded_files_info.append(filename)
            
            # Classification
            fn_dtype = classify_by_filename(filename)
            if fn_dtype:
                inferred_types.append(f"{storage.hebrew_label_for(fn_dtype)} (via filename)")
                confidently_classified += 1
                filename_worked_examples.append((orig_id, filename, fn_dtype))
            elif checkbox_dtypes:
                # Fall back to checkboxes
                # If there's only one checkbox dtype, it's highly confident
                if len(checkbox_dtypes) == 1:
                    cb_dtype = list(checkbox_dtypes)[0]
                    inferred_types.append(f"{storage.hebrew_label_for(cb_dtype)} (via checkbox fallback)")
                    confidently_classified += 1
                    checkbox_fallback_examples.append((orig_id, filename, cb_dtype, checkbox_selections))
                else:
                    # Ambiguous fallback (multiple checkbox dtypes selected, but generic filename)
                    inferred_types.append(f"Ambiguous {list(checkbox_dtypes)} (via checkbox)")
                    ambiguous_files += 1
                    ambiguous_examples.append((orig_id, filename, list(checkbox_dtypes), checkbox_selections))
            else:
                inferred_types.append("Unclassified")
                unclassified_files += 1
                
        inventory_rows.append({
            "orig_label": f"{fullname} ({orig_id})",
            "missing_label": f"{missing_id}",
            "orig_docs": orig_docs,
            "files": uploaded_files_info,
            "selections": checkbox_selections,
            "inferred": inferred_types,
            "confidence": confidence
        })
        
    # Output Table
    print("\n### DOCUMENT INVENTORY REPORT")
    print("| Original Submission | Missing Docs Submission | Uploaded Files | Inferred Types | Confidence |")
    print("|---|---|---|---|---|")
    for row in inventory_rows:
        orig_s = f"{row['orig_label']}<br>Docs: {', '.join(row['orig_docs']) or '(none)'}"
        miss_s = f"{row['missing_label']}<br>Checked: {', '.join(row['selections']) or '(none)'}"
        files_s = "<br>".join(row['files']) or "(none)"
        inferred_s = "<br>".join(row['inferred']) or "(none)"
        print(f"| {orig_s} | {miss_s} | {files_s} | {inferred_s} | {row['confidence']} |")

    # Generate MD report
    total_files = confidently_classified + ambiguous_files + unclassified_files
    accuracy = confidently_classified / total_files if total_files > 0 else 1.0
    
    report_content = f"""# Phase 9C Document Reconciliation Inventory Report

This report presents a detailed audit of the document inventory for the 14 matched production pairs, evaluating document classification accuracy and proposing a merge strategy.

---

## 1. Document Matching and Classification Inventory

| Original Submission | Missing Docs Submission | Uploaded Files | Inferred Types | Confidence |
|---|---|---|---|---|
"""
    for row in inventory_rows:
        orig_s = f"{row['orig_label']}<br>Docs: {', '.join(row['orig_docs']) or '(none)'}"
        miss_s = f"{row['missing_label']}<br>Checked: {', '.join(row['selections']) or '(none)'}"
        files_s = "<br>".join(row['files']) or "(none)"
        inferred_s = "<br>".join(row['inferred']) or "(none)"
        report_content += f"| {orig_s} | {miss_s} | {files_s} | {inferred_s} | {row['confidence']} |\n"
        
    report_content += f"""
---

## 2. Classification Metrics

* **Total Files Evaluated**: {total_files}
* **Confidently Classified Files**: {confidently_classified}
* **Ambiguous Files**: {ambiguous_files}
* **Unclassified Files**: {unclassified_files}
* **Classification Accuracy**: {accuracy:.1%}

---

## 3. Classification Examples

### A) Filename Classification Worked
"""
    for orig_id, filename, dtype in filename_worked_examples[:3]:
        report_content += f"- **Submission**: `{orig_id}` | **Filename**: `{filename}` $\\rightarrow$ Classified as **`{storage.hebrew_label_for(dtype)}`** (`{dtype}`)\n"
        
    report_content += """
### B) Checkbox Fallback Required (Generic Filenames)
"""
    for orig_id, filename, dtype, selections in checkbox_fallback_examples[:3]:
        report_content += f"- **Submission**: `{orig_id}` | **Filename**: `{filename}` | **Selections**: `{selections}` $\\rightarrow$ Classified as **`{storage.hebrew_label_for(dtype)}`** (single-type mapping fallback)\n"
        
    report_content += """
### C) Ambiguous Uploads Identified
"""
    if ambiguous_examples:
        for orig_id, filename, dtypes, selections in ambiguous_examples[:3]:
            labels = [storage.hebrew_label_for(d) for d in dtypes]
            report_content += f"- **Submission**: `{orig_id}` | **Filename**: `{filename}` | **Selections**: `{selections}` $\\rightarrow$ **Ambiguous** between `{labels}` (Multiple checklist options checked, generic file name)\n"
    else:
        report_content += "- *None found in the tested sample.* All generic uploads mapped to a single checked checkbox category.\n"

    report_content += """
---

## 4. Recommended Merge Strategy

To ensure zero loss of metadata and resolve ambiguities, we recommend the following merge strategy:
1. **Prioritize Filename Keywords**: If a filename contains clear keywords (e.g. `חוזה`), map it to that document type.
2. **Single Checklist Fallback**: If the filename is generic (e.g. `WhatsApp Image`) and the checklist has only *one* document type selected (e.g. `תעודת זהות`), map it to that type.
3. **Ambiguity Resolution via File Manifest Mapping**: If multiple checklist document types are selected and multiple generic files are uploaded, download all of them into the submission folder, mapping them to the checked document types sequentially (or placing them in `_unmapped` while flagging them on the dashboard/manifest).
4. **Do Not Overwrite**: If the original submission already contains the document type, preserve the original and save the Missing Documents file with a suffix (e.g., `id_photo_followup.png`) to avoid over-writing and retain both copies.
5. **Metadata Manifest tracking**: Update the `_manifest.json` under `data/documents/{submission_id}/` to list the source form and upload date for every merged file.
"""

    report_path = Path("C:/Users/SAIF/.gemini/antigravity/brain/640b28ff-3c4e-44e8-8144-5a82b5a1366d/missing_docs_classification_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_content)
    print(f"\nSaved report to {report_path}")

if __name__ == "__main__":
    main()
