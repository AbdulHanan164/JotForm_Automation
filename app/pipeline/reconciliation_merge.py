import json
import logging
import os
import shutil
import tempfile
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict, Any

from app.documents.contracts import FileAnswer
from app.documents import storage

logger = logging.getLogger("webhook.reconciliation")

class ClassificationResult(TypedDict):
    document_type: str  # "id_photo", "lease_contract", "arnona_bill", "corp_cert", "tabu", "signature", or ""
    confidence: float   # 0.0 to 1.0
    reason: str        # Explanation of decision
    classifier: str    # "FilenameClassifier" | "CheckboxClassifier" | "OpenAIVisionClassifier" | ...

class DocumentClassifier(ABC):
    @abstractmethod
    def classify(self, file_path: str, context: dict[str, Any] | None = None) -> ClassificationResult:
        pass

class FilenameClassifier(DocumentClassifier):
    def classify(self, file_path: str, context: dict[str, Any] | None = None) -> ClassificationResult:
        filename = Path(file_path).name
        from urllib.parse import unquote
        fn = unquote(filename).lower()
        
        doc_type = ""
        reason = ""
        
        if any(x in fn for x in ["תעודת זהות", "תעודת_זהות", "תז שלי", "תז.pdf", "תז.jpg", "תז.png", "דרכון", "zehut", "passport", "ת.ז", "ת\"ז"]):
            doc_type = "id_photo"
            reason = f"Matched ID photo keywords in filename: '{filename}'"
        elif any(x in fn for x in ["חוזה", "שכירות", "הסכם", "מכר", "רכישה", "השכרה", "lease", "contract", "rent", "sale"]):
            doc_type = "lease_contract"
            reason = f"Matched lease contract keywords in filename: '{filename}'"
        elif any(x in fn for x in ["ארנונה", "arnona"]):
            doc_type = "arnona_bill"
            reason = f"Matched Arnona keywords in filename: '{filename}'"
        elif any(x in fn for x in ["טאבו", "tabu"]):
            doc_type = "tabu"
            reason = f"Matched Tabu keywords in filename: '{filename}'"
        elif any(x in fn for x in ["התאגדות", "חברה", "corp", "company"]):
            doc_type = "corp_cert"
            reason = f"Matched Corp Cert keywords in filename: '{filename}'"
        elif any(x in fn for x in ["חתימה", "signature", "sign"]):
            doc_type = "signature"
            reason = f"Matched signature keywords in filename: '{filename}'"
            
        if doc_type:
            return {
                "document_type": doc_type,
                "confidence": 0.95,
                "reason": reason,
                "classifier": "FilenameClassifier"
            }
            
        return {
            "document_type": "",
            "confidence": 0.0,
            "reason": f"No keywords matched in filename '{filename}'",
            "classifier": "FilenameClassifier"
        }

class CheckboxClassifier(DocumentClassifier):
    def classify(self, file_path: str, context: dict[str, Any] | None = None) -> ClassificationResult:
        ctx = context or {}
        checklist_selections = ctx.get("checklist_selections", [])
        
        if not checklist_selections:
            return {
                "document_type": "",
                "confidence": 0.0,
                "reason": "No checklist selections available in context",
                "classifier": "CheckboxClassifier"
            }
            
        # Map selections to doc types
        mapped_types = []
        for opt in checklist_selections:
            opt_lower = opt.lower()
            if any(x in opt_lower for x in ["תז", "ת\"ז", "זהות", "ת.ז"]):
                mapped_types.append("id_photo")
            if any(x in opt_lower for x in ["חוזה", "שכירות", "מכר", "הסכם"]):
                mapped_types.append("lease_contract")
            if "ארנונה" in opt_lower:
                mapped_types.append("arnona_bill")
            if "התאגדות" in opt_lower:
                mapped_types.append("corp_cert")
            if "טאבו" in opt_lower:
                mapped_types.append("tabu")
                
        mapped_types = list(set(mapped_types))
        
        if len(mapped_types) == 1:
            doc_type = mapped_types[0]
            return {
                "document_type": doc_type,
                "confidence": 0.80,
                "reason": f"Single checklist selection type mapped: {doc_type}",
                "classifier": "CheckboxClassifier"
            }
            
        # Sequential fallback for generic file names if multiple selections exist
        filename = Path(file_path).name.lower()
        generic_keywords = ["whatsapp", "screenshot", "image", "img", "scan", "photo", "лрг", "дог", "тз", "קריאת מונה", "מונה"]
        is_generic = any(x in filename for x in generic_keywords) or len(filename) < 12
        
        if is_generic and mapped_types:
            # Look for index of this generic file in sequential generic files list
            generic_files = ctx.get("generic_files", [])
            if file_path in generic_files:
                idx = generic_files.index(file_path)
                if idx < len(mapped_types):
                    doc_type = mapped_types[idx]
                    return {
                        "document_type": doc_type,
                        "confidence": 0.80,
                        "reason": f"Sequential checklist fallback mapping: file {idx + 1} -> doc_type '{doc_type}'",
                        "classifier": "CheckboxClassifier"
                    }
                    
        return {
            "document_type": "",
            "confidence": 0.0,
            "reason": f"Ambiguous checklist mapping with choices: {mapped_types}",
            "classifier": "CheckboxClassifier"
        }

class ClassifierPipeline(DocumentClassifier):
    def __init__(self):
        self.classifiers = [
            FilenameClassifier(),
            CheckboxClassifier()
        ]
        
    def classify(self, file_path: str, context: dict[str, Any] | None = None) -> ClassificationResult:
        # First try filename classifier
        res = self.classifiers[0].classify(file_path, context)
        if res["confidence"] >= 0.90:
            return res
            
        # Fallback to checkbox classifier
        cb_res = self.classifiers[1].classify(file_path, context)
        if cb_res["confidence"] > 0.0:
            return cb_res
            
        return res

# ── Document Merger ─────────────────────────────────────────────────────────

def download_and_merge_files(
    orig_sub_id: str,
    missing_sub_id: str,
    local_file_paths: list[str],
    checklist_selections: list[str]
) -> dict[str, Any]:
    """
    Classify local Missing Docs files, copy them to original submission folder,
    no-overwrite, and update original _manifest.json.
    """
    from app.config import settings
    orig_dir = settings.documents_dir / orig_sub_id
    orig_dir.mkdir(parents=True, exist_ok=True)
    
    # Load or create original manifest
    manifest_path = orig_dir / "_manifest.json"
    manifest_data = {}
    if manifest_path.exists():
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            pass
            
    if "submission_id" not in manifest_data:
        manifest_data["submission_id"] = orig_sub_id
    if "documents" not in manifest_data:
        manifest_data["documents"] = {}
        
    # Classify files
    pipeline = ClassifierPipeline()
    generic_keywords = ["whatsapp", "screenshot", "image", "img", "scan", "photo", "лрг", "дог", "тз", "קריאת מונה", "מונה"]
    generic_files = []
    
    for f in local_file_paths:
        name = Path(f).name.lower()
        if any(gk in name for gk in generic_keywords) or len(name) < 12:
            generic_files.append(f)
            
    context = {
        "checklist_selections": checklist_selections,
        "generic_files": generic_files
    }
    
    for f_path in local_file_paths:
        src = Path(f_path)
        if not src.exists():
            continue
            
        res = pipeline.classify(f_path, context)
        doc_type = res["document_type"]
        ext = src.suffix.lower()
        
        # Decide status and target filename based on classifier type and confidence
        if doc_type:
            classifier_name = res.get("classifier")
            confidence = res.get("confidence", 0.0)
            
            # Auto-merge only allowed for FilenameClassifier or future AI classifiers with confidence >= 0.90
            is_auto_merge_classifier = classifier_name in (
                "FilenameClassifier", 
                "OpenAIVisionClassifier", 
                "NvidiaVisionClassifier", 
                "GeminiVisionClassifier"
            )
            
            if is_auto_merge_classifier and confidence >= 0.90:
                status = "present"
            else:
                status = "needs_review"
            stem = storage.filename_stem_for(doc_type)
            
            # Non-overwrite logic
            dest_path = orig_dir / f"{stem}{ext}"
            if dest_path.exists():
                idx = 1
                while True:
                    dest_path = orig_dir / f"{stem}_followup_{idx}{ext}"
                    if not dest_path.exists():
                        break
                    idx += 1
        else:
            status = "needs_review"
            from app.documents.downloader import _safe_filename
            safe_name = _safe_filename(src.stem)
            dest_path = orig_dir / "_unmapped" / f"{safe_name}{ext}"
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            if dest_path.exists():
                idx = 1
                while True:
                    dest_path = orig_dir / "_unmapped" / f"{safe_name}_followup_{idx}{ext}"
                    if not dest_path.exists():
                        break
                    idx += 1
                    
        # Copy file
        shutil.copy2(src, dest_path)
        
        # Calculate SHA256
        content = dest_path.read_bytes()
        sha = storage.sha256_hex(content)
        
        file_entry = {
            "filename": dest_path.name,
            "local_path": str(dest_path),
            "sha256": sha,
            "size_bytes": len(content),
            "classifier": res["classifier"],
            "confidence": res["confidence"]
        }
        
        # Save to manifest
        if doc_type:
            doc_entry = manifest_data["documents"].setdefault(doc_type, {
                "status": "missing",
                "source_form": "251323124205946",
                "upload_date": datetime.now(timezone.utc).isoformat(),
                "files": []
            })
            
            # Status resolution: "present" takes priority. Once present, it stays present.
            if doc_entry["status"] != "present":
                doc_entry["status"] = status
                
            doc_entry["source_form"] = "251323124205946"
            doc_entry["upload_date"] = datetime.now(timezone.utc).isoformat()
            
            # Check if this file path is already in files list
            existing_paths = [x.get("local_path") for x in doc_entry["files"]]
            if str(dest_path) not in existing_paths:
                doc_entry["files"].append(file_entry)
        else:
            # Unmapped files recorded under special key
            unmapped_list = manifest_data.setdefault("unmapped_files", [])
            unmapped_list.append(file_entry)
            
    manifest_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    storage.write_manifest(orig_sub_id, manifest_data)
    return manifest_data

# ── Update Review Item ───────────────────────────────────────────────────────

def update_review_item_after_merge(orig_sub_id: str) -> None:
    """
    Loads ReviewItem, updates present documents, recalculates missing,
    re-drafts missing email, and saves it.
    """
    from app.review import queue as Q
    from app.mappers.models import BusinessSubmission
    from app.mappers.missing_detector import detect_missing
    from app.services.arnona.service import ArnonaService
    from app.documents.storage import hebrew_label_for
    
    item = Q.load(orig_sub_id)
    if not item:
        return
        
    # Read manifest
    from app.config import settings
    manifest_path = settings.documents_dir / orig_sub_id / "_manifest.json"
    if not manifest_path.exists():
        return
        
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return
        
    docs_manifest = manifest.get("documents", {})
    
    # Get status of each doc_type
    docs_bd = item.business_data.setdefault("documents", {})
    summary_docs = item.summary.setdefault("מסמכים", {})
    
    present_count = 0
    total_count = 0
    
    for doc_type in ["id_photo", "lease_contract", "signature", "arnona_bill", "corp_cert", "tabu"]:
        entry = docs_manifest.get(doc_type)
        if entry:
            status = entry.get("status")
            heb_label = hebrew_label_for(doc_type)
            
            if status == "present":
                docs_bd[doc_type] = "✅"
                if heb_label:
                    summary_docs[heb_label] = "✅"
                present_count += 1
            else:
                # needs_review or missing
                docs_bd[doc_type] = "❌"
                if heb_label:
                    summary_docs[heb_label] = "❌"
            total_count += 1
            
    if present_count == total_count:
        item.documents_status = "ready"
    elif present_count > 0:
        item.documents_status = "partial"
    else:
        item.documents_status = "failed"
        
    # Recalculate missing detection
    bs = BusinessSubmission.from_dict(item.business_data)
    bs.submission_id = orig_sub_id
    
    missing_res = detect_missing(bs)
    item.missing_docs = missing_res.get("missing_docs", [])
    
    # Re-draft email
    arnona_svc = ArnonaService()
    new_email = arnona_svc.draft_email(item.summary, {"missing_info": item.missing_info, "missing_docs": item.missing_docs})
    item.draft_email = new_email
    
    Q.save(item)
    logger.info("Updated original review item %s after document merge", orig_sub_id)

# ── Pipeline / Webhook triggers ──────────────────────────────────────────────

def reconcile_and_merge_for_original(orig_sub_id: str, parsed: dict[str, Any]) -> None:
    """
    Triggered during original pipeline. Checks local index for matching
    Missing Documents, copies files, updates parsed documents structure.
    """
    from app.pipeline.reconciliation import MissingDocsReconciler
    from app.pipeline.reconciliation_index import _load_index
    
    reconciler = MissingDocsReconciler()
    index = _load_index()
    
    # Find matches in local index
    matched_ids = []
    
    # Extract identity fields from original parsed
    answers = parsed.get("answers")
    if answers and isinstance(answers, dict):
        orig_mzk_raw = answers.get("184", {}).get("answer") or answers.get("291", {}).get("answer")
        orig_id_raw = answers.get("32", {}).get("answer")
        orig_email = (answers.get("30", {}).get("answer") or "").lower().strip()
        orig_phone = reconciler.normalize_phone(answers.get("208", {}).get("answer"))
    else:
        bd = parsed.get("_business") or parsed
        orig_mzk_raw = parsed.get("mzk_ref") or parsed.get("summary", {}).get("מידע_פנימי", {}).get("מספר_פנייה")
        incoming = bd.get("incoming_tenant") or {}
        orig_id_raw = incoming.get("id_number")
        orig_email = (incoming.get("email") or "").lower().strip()
        orig_phone = reconciler.normalize_phone(incoming.get("phone"))
        
    orig_mzk = reconciler.normalize_mzk(orig_mzk_raw)
    orig_id = reconciler.normalize_id(orig_id_raw)
    
    # Lookup index
    if orig_mzk and orig_mzk in index["mzk_index"]:
        matched_ids.extend(index["mzk_index"][orig_mzk])
    if orig_id and orig_id in index["id_index"]:
        matched_ids.extend(index["id_index"][orig_id])
    if orig_id and orig_email:
        # Check if matched by email
        for sub_id in index["email_index"].get(orig_email, []):
            sub_meta = index["submissions"].get(sub_id, {})
            if sub_meta.get("id_number") == orig_id:
                matched_ids.append(sub_id)
    if orig_id and orig_phone:
        # Check if matched by phone
        for sub_id in index["phone_index"].get(orig_phone, []):
            sub_meta = index["submissions"].get(sub_id, {})
            if sub_meta.get("id_number") == orig_id:
                matched_ids.append(sub_id)
                
    matched_ids = list(set(matched_ids))
    if not matched_ids:
        return
        
    for missing_id in matched_ids:
        sub_meta = index["submissions"].get(missing_id)
        if not sub_meta:
            continue
            
        logger.info("Found local reconciled match for %s -> missing doc submission %s", orig_sub_id, missing_id)
        
        # Download/Merge
        manifest = download_and_merge_files(
            orig_sub_id,
            missing_id,
            sub_meta["local_paths"],
            sub_meta["checklist_selections"]
        )
        
        # Update parsed documents in-memory
        for doc_type, entry in manifest.get("documents", {}).items():
            if entry.get("status") == "present":
                heb_label = hebrew_label_for(doc_type)
                if heb_label:
                    parsed.setdefault("documents", {})[heb_label] = {
                        "present": True,
                        "url": entry["files"][0]["source_url"] if entry["files"] else ""
                    }
                    
    # Re-build business data in parsed
    try:
        from app.mappers.business_mapper import build_from_parsed
        parsed["_business"] = build_from_parsed(parsed).to_dict()
    except Exception as exc:
        logger.warning("Failed to rebuild business data after merge: %s", exc)

def reconcile_and_merge_for_missing_docs(missing_sub_raw: dict[str, Any]) -> None:
    """
    Triggered when a new Missing Documents submission comes in.
    """
    from app.review import queue as Q
    from app.pipeline.reconciliation import MissingDocsReconciler
    
    sub_id = str(missing_sub_raw.get("id") or missing_sub_raw.get("submissionID"))
    
    # Save & Index first
    from app.pipeline.reconciliation_index import save_and_index_submission
    save_and_index_submission(missing_sub_raw)
    
    # Reload from index to get local file paths
    from app.pipeline.reconciliation_index import _load_index
    index = _load_index()
    sub_meta = index["submissions"].get(sub_id)
    if not sub_meta:
        return
        
    # Query actionable items in original review queue
    review_items = Q.load_all(limit=150)
    actionable_items = [item for item in review_items if item.is_actionable]
    
    reconciler = MissingDocsReconciler()
    for item in actionable_items:
        # Match original submission against the missing doc submission
        matches = reconciler.match_submission(item.to_dict(), [missing_sub_raw])
        if matches:
            logger.info("Found match for incoming missing docs submission %s -> original %s (confidence %s)",
                        sub_id, item.submission_id, matches[0]["confidence"])
            
            # Merge
            download_and_merge_files(
                item.submission_id,
                sub_id,
                sub_meta["local_paths"],
                sub_meta["checklist_selections"]
            )
            
            # Update original review queue item
            update_review_item_after_merge(item.submission_id)
