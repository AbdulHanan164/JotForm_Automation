"""
One-time DETECTION-ONLY backfill for existing review-queue records.

Recomputes ONLY parsing + document detection + missing-info detection from each
submission's archived raw payload, and rewrites ONLY those fields back into the
review-queue JSON. Everything else is preserved byte-for-byte:

  PRESERVED: status, reviewed_at, reviewed_by, review_notes, draft_email,
             final_email, documents_status, validation_issues, doc_extractions,
             received_at, service_name, form_title  + original file mtime

  RECOMPUTED: business_data, summary, missing_info, missing_docs,
              customer_name/phone/email, property_address, services, mzk_ref

No emails. No downloads. No document jobs. No status/approval changes.

Usage:
    python scripts/backfill_detection.py dryrun   # print table, write nothing
    python scripts/backfill_detection.py apply     # back up + rewrite
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/home/ubuntu/app")

from app.services.arnona.service import ArnonaService
from app.services.arnona.conditional_logic import arnona_logic_engine
from app.mappers.models import BusinessSubmission
from app.mappers.missing_detector import detect_missing
from app.review import queue as Q
from app.review.queue import build_from_pipeline

QUEUE_DIR = "/var/data/review_queue"
ARCHIVE_DIR = "/var/data/submissions"

# Fields recomputed by parsing/detection — everything else is preserved.
RECOMPUTED_KEYS = (
    "business_data", "summary", "missing_info", "missing_docs",
    "customer_name", "customer_phone", "customer_email",
    "property_address", "services",
)


class _Shim:
    """Minimal stand-in for PipelineResult, enough for build_from_pipeline()."""
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _labels(items):
    return [m.get("label", "?") for m in (items or [])]


def _archive_for(sid: str) -> str | None:
    matches = glob.glob(os.path.join(ARCHIVE_DIR, f"*_{sid}_raw.json"))
    return matches[0] if matches else None


def main(mode: str) -> None:
    apply = mode == "apply"
    svc = ArnonaService()

    backup_dir = None
    if apply:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_dir = Path(f"/var/data/review_queue_backup_{stamp}")
        backup_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    tot_info_b = tot_info_a = tot_docs_b = tot_docs_a = 0
    skipped = []

    for qpath in sorted(glob.glob(os.path.join(QUEUE_DIR, "*.json"))):
        existing = json.loads(Path(qpath).read_text(encoding="utf-8"))
        sid = existing["submission_id"]

        arch_path = _archive_for(sid)
        if not arch_path:
            skipped.append((sid, "no archived raw payload"))
            continue

        arch = json.loads(Path(arch_path).read_text(encoding="utf-8"))
        rr = arch.get("_raw_request", {})
        rf = arch.get("_raw_fields", {})
        merged = {**rr, **{k: v for k, v in rf.items()}}

        info_b = _labels(existing.get("missing_info"))
        docs_b = _labels(existing.get("missing_docs"))

        # ── Reprocess: parsing → detection ────────────────────────────────────
        parsed = svc.parse_fields(merged)
        summary = svc.build_summary(parsed)
        bd = parsed.get("_business") or {}
        bs = BusinessSubmission.from_dict(bd)
        visibility = arnona_logic_engine.evaluate(parsed)
        missing = detect_missing(bs, visibility)

        shim = _Shim(
            summary=summary, business_data=bd, parsed=parsed, missing=missing,
            submission_id=sid, service_name=existing.get("service_name", ""),
            form_title=existing.get("form_title", ""),
            received_at=existing.get("received_at", ""),
            validation_issues=[], doc_extractions=existing.get("doc_extractions", {}),
            email=None,
        )
        fresh = build_from_pipeline(shim).to_dict()

        info_a = _labels(missing.get("missing_info"))
        docs_a = _labels(missing.get("missing_docs"))

        # ── Selective merge: overwrite ONLY recomputed keys ──────────────────
        updated = dict(existing)            # preserve everything
        for k in RECOMPUTED_KEYS:
            updated[k] = fresh[k]
        # mzk_ref is a stable identifier — keep existing, fall back to fresh
        updated["mzk_ref"] = existing.get("mzk_ref") or fresh.get("mzk_ref", "")

        rows.append((existing.get("mzk_ref") or sid[-6:], info_b, info_a, docs_b, docs_a))
        tot_info_b += len(info_b); tot_info_a += len(info_a)
        tot_docs_b += len(docs_b); tot_docs_a += len(docs_a)

        if apply:
            st = os.stat(qpath)
            shutil.copy2(qpath, backup_dir / os.path.basename(qpath))
            Path(qpath).write_text(
                json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.utime(qpath, (st.st_atime, st.st_mtime))   # preserve sort order

    # ── Report ────────────────────────────────────────────────────────────────
    print(f"MODE: {'APPLY (files rewritten)' if apply else 'DRY RUN (no writes)'}")
    if backup_dir:
        print(f"Backup: {backup_dir}")
    print()
    for ref, ib, ia, db, da in rows:
        print(f"--- {ref} ---")
        print(f"  info  before({len(ib)}): {ib}")
        print(f"  info  after ({len(ia)}): {ia}")
        print(f"  docs  before({len(db)}): {db}")
        print(f"  docs  after ({len(da)}): {da}")
    if skipped:
        print("\nSKIPPED:")
        for sid, why in skipped:
            print(f"  {sid}: {why}")
    print(f"\nSUMMARY  submissions updated: {len(rows)}")
    print(f"  missing_info  total {tot_info_b} -> {tot_info_a}  (removed {tot_info_b - tot_info_a})")
    print(f"  missing_docs  total {tot_docs_b} -> {tot_docs_a}  (removed {tot_docs_b - tot_docs_a})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "dryrun")
