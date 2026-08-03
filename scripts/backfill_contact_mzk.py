"""
One-time CONTACT + MZK backfill for existing review-queue records.

Two earlier fixes changed how four quick-view fields are derived, but review
items are only written when a submission arrives, so records created before
those fixes kept the old values:

  * MZK reference was read from q291_uniqueId291, which JotForm returns as a
    constant on every submission. The incrementing reference is q184_uniqueId.
  * customer_name / phone / email were read from the incoming tenant only, so
    terminations (which have no incoming tenant) showed the "not provided"
    placeholder even though the outgoing tenant carried the data.

This script rewrites ONLY those four fields, recomputed with exactly the same
precedence the live pipeline now uses:

  RECOMPUTED: mzk_ref, customer_name, customer_phone, customer_email

  PRESERVED:  status, reviewed_at, reviewed_by, review_notes, draft_email,
              final_email, business_data, summary, missing_info, missing_docs,
              validation_issues, doc_extractions, documents_status,
              operator_summary, detail_record, received_at, service_name,
              property_address, services  + the original file mtime

Document manifests under DOCUMENTS_DIR are never opened. No emails are sent,
no documents are downloaded, no statuses change.

Usage:
    python scripts/backfill_contact_mzk.py dryrun   # print table, write nothing
    python scripts/backfill_contact_mzk.py apply    # back up + rewrite
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402

PLACEHOLDER = "לא סופק"

# Only these four keys may ever be written by this script.
BACKFILL_FIELDS = ("mzk_ref", "customer_name", "customer_phone", "customer_email")


def _clean(value) -> str:
    """Treat the Hebrew "not provided" placeholder as absent."""
    s = (value or "").strip() if isinstance(value, str) else ""
    return "" if s == PLACEHOLDER else s


def _contact(business_data: dict, summary: dict) -> tuple[str, str, str]:
    """Mirror app/review/queue.py: incoming -> outgoing -> summary."""
    incoming = business_data.get("incoming_tenant") or {}
    outgoing = business_data.get("outgoing_tenant") or {}
    legacy = summary.get("דייר_נכנס", {}) if isinstance(summary, dict) else {}

    name = (_clean(incoming.get("full_name"))
            or _clean(outgoing.get("full_name"))
            or _clean(legacy.get("שם")))
    phone = (_clean(incoming.get("phone"))
             or _clean(outgoing.get("phone"))
             or _clean(legacy.get("טלפון")))
    email = (_clean(incoming.get("email"))
             or _clean(outgoing.get("email"))
             or _clean(legacy.get("אימייל")))
    return name, phone, email


def _archived_mzk(submission_id: str) -> str:
    """Read the real MZK reference (q184_uniqueId) from the archived payload."""
    matches = glob.glob(str(settings.submissions_dir / f"*_{submission_id}_raw.json"))
    if not matches:
        return ""
    try:
        raw = json.loads(Path(matches[0]).read_text(encoding="utf-8"))
    except Exception:
        return ""
    for container in ("_raw_request", "_parsed"):
        block = raw.get(container) or {}
        if isinstance(block, dict):
            val = block.get("q184_uniqueId")
            if isinstance(val, str) and val.strip():
                return val.strip()
    unmapped = ((raw.get("_parsed") or {}).get("_unmapped") or {})
    val = unmapped.get("q184_uniqueId")
    return val.strip() if isinstance(val, str) else ""


def main(mode: str) -> None:
    apply = mode == "apply"
    queue_dir = settings.review_dir

    backup_dir = None
    if apply:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_dir = queue_dir.parent / f"review_queue_backup_{stamp}"
        backup_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(glob.glob(str(queue_dir / "*.json")))
    changed = unchanged = skipped = 0

    print(f"{'submission':<21} {'field':<16} {'before':<24} -> after")
    print("-" * 96)

    for qpath in files:
        try:
            item = json.loads(Path(qpath).read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  SKIP {os.path.basename(qpath)}: unreadable ({exc})")
            skipped += 1
            continue

        sid = item.get("submission_id") or Path(qpath).stem
        bd = item.get("business_data") or {}
        summary = item.get("summary") or {}

        name, phone, email = _contact(bd, summary)
        mzk = _archived_mzk(sid)

        new_values = {
            "mzk_ref": mzk or item.get("mzk_ref", ""),
            "customer_name": name or item.get("customer_name", ""),
            "customer_phone": phone or item.get("customer_phone", ""),
            "customer_email": email or item.get("customer_email", ""),
        }

        diffs = {k: (item.get(k, ""), v) for k, v in new_values.items()
                 if item.get(k, "") != v}
        if not diffs:
            unchanged += 1
            continue

        for field, (before, after) in diffs.items():
            print(f"{sid:<21} {field:<16} {str(before)[:24]:<24} -> {after}")

        if apply:
            shutil.copy2(qpath, backup_dir / os.path.basename(qpath))
            stat = os.stat(qpath)
            for field, value in new_values.items():
                item[field] = value
            Path(qpath).write_text(
                json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.utime(qpath, (stat.st_atime, stat.st_mtime))
        changed += 1

    print("-" * 96)
    print(f"MODE       : {'APPLY (files rewritten)' if apply else 'DRY RUN (no writes)'}")
    if backup_dir:
        print(f"Backup     : {backup_dir}")
    print(f"records    : {len(files)}")
    print(f"changed    : {changed}")
    print(f"unchanged  : {unchanged}")
    print(f"skipped    : {skipped}")
    print(f"fields written: {', '.join(BACKFILL_FIELDS)}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "dryrun")
