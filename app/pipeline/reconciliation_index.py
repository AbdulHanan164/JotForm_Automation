import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger("webhook.reconciliation")

INDEX_DIR = Path("data/missing_docs_submissions")
INDEX_PATH = INDEX_DIR / "_index.json"

def _load_index() -> dict[str, Any]:
    if not INDEX_PATH.exists():
        return {"mzk_index": {}, "id_index": {}, "email_index": {}, "phone_index": {}, "submissions": {}}
    try:
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("Failed to load Missing Docs index: %s", exc)
        return {"mzk_index": {}, "id_index": {}, "email_index": {}, "phone_index": {}, "submissions": {}}

def _save_index(index: dict[str, Any]) -> None:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(INDEX_DIR), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
        os.replace(tmp, INDEX_PATH)
    except Exception as exc:
        logger.error("Failed to save Missing Docs index: %s", exc)
        if os.path.exists(tmp):
            os.unlink(tmp)

def save_and_index_submission(submission: dict[str, Any]) -> None:
    """
    Save raw submission JSON and index normalized keys for offline reconciliation.
    Downloads uploaded files locally as well.
    """
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    sub_id = submission.get("id") or submission.get("submissionID")
    if not sub_id:
        return
        
    sub_id = str(sub_id)
    
    # Save raw JSON
    raw_path = INDEX_DIR / f"{sub_id}.json"
    raw_path.write_text(json.dumps(submission, ensure_ascii=False, indent=2), encoding="utf-8")
    
    # Download files immediately
    from app.pipeline.reconciliation import MissingDocsReconciler
    reconciler = MissingDocsReconciler()
    
    answers = submission.get("answers", {})
    sub_mzk = reconciler.normalize_mzk(answers.get("184", {}).get("answer") or answers.get("291", {}).get("answer"))
    sub_id_num = reconciler.normalize_id(answers.get("32", {}).get("answer"))
    sub_email = (answers.get("30", {}).get("answer") or "").lower().strip()
    sub_phone = reconciler.normalize_phone(answers.get("208", {}).get("answer"))
    
    sub_first = answers.get("21", {}).get("answer") or ""
    sub_last = answers.get("20", {}).get("answer") or ""
    sub_fullname = reconciler.normalize_name(f"{sub_first} {sub_last}")
    
    # Checklist and file extraction
    checklist_keys = ["317", "318", "320", "321", "322", "323", "311"]
    checklist_selections = []
    for k in checklist_keys:
        val = answers.get(k, {}).get("answer")
        if val:
            if isinstance(val, list):
                checklist_selections.extend([str(x) for x in val if x])
            elif isinstance(val, str):
                checklist_selections.append(val)
                
    files_raw = answers.get("38", {}).get("answer") or []
    if isinstance(files_raw, str) and files_raw:
        files_raw = [files_raw]
    elif not isinstance(files_raw, list):
        files_raw = []
        
    camera_fields = ["37", "329", "330", "331"]
    for c in camera_fields:
        c_val = answers.get(c, {}).get("answer")
        if c_val:
            if isinstance(c_val, str) and c_val.startswith("http"):
                files_raw.append(c_val)
            elif isinstance(c_val, list):
                files_raw.extend([str(x) for x in c_val if isinstance(x, str) and x.startswith("http")])
                
    # Download files to local subfolder
    sub_docs_dir = INDEX_DIR / sub_id
    sub_docs_dir.mkdir(parents=True, exist_ok=True)
    local_files = []
    
    from app.documents.downloader import _download_file
    for url in files_raw:
        res = _download_file(url, sub_docs_dir, url.split("/")[-1])
        if res.get("local_path"):
            local_files.append(res["local_path"])
            
    # Load index
    index = _load_index()
    
    # Store submission metadata in index
    index["submissions"][sub_id] = {
        "mzk_ref": sub_mzk,
        "id_number": sub_id_num,
        "email": sub_email,
        "phone": sub_phone,
        "name": sub_fullname,
        "created_at": submission.get("created_at", ""),
        "file_names": [Path(f).name for f in local_files],
        "local_paths": local_files,
        "checklist_selections": checklist_selections
    }
    
    # Index normalized values
    if sub_mzk:
        index["mzk_index"].setdefault(sub_mzk, []).append(sub_id)
        index["mzk_index"][sub_mzk] = list(set(index["mzk_index"][sub_mzk]))
    if sub_id_num:
        index["id_index"].setdefault(sub_id_num, []).append(sub_id)
        index["id_index"][sub_id_num] = list(set(index["id_index"][sub_id_num]))
    if sub_email:
        index["email_index"].setdefault(sub_email, []).append(sub_id)
        index["email_index"][sub_email] = list(set(index["email_index"][sub_email]))
    if sub_phone:
        index["phone_index"].setdefault(sub_phone, []).append(sub_id)
        index["phone_index"][sub_phone] = list(set(index["phone_index"][sub_phone]))
        
    _save_index(index)
    logger.info("Local index updated for Missing Docs submission %s", sub_id)

def get_indexed_submissions() -> list[dict[str, Any]]:
    """
    Returns all locally stored Missing Documents submissions.
    """
    index = _load_index()
    out = []
    for sub_id in index["submissions"].keys():
        sub_path = INDEX_DIR / f"{sub_id}.json"
        if sub_path.exists():
            try:
                out.append(json.loads(sub_path.read_text(encoding="utf-8")))
            except Exception:
                pass
    return out
