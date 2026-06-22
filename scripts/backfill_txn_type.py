import json
import sys
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.mappers.business_mapper import build_from_parsed

def run_backfill(dry_run=False):
    review_dir = settings.review_dir
    submissions_dir = settings.submissions_dir
    
    review_files = list(review_dir.glob("*.json"))
    print(f"Loaded {len(review_files)} review queue records from {review_dir}")
    
    mismatches = []
    
    # 1. Before update audit
    for fp in sorted(review_files):
        submission_id = fp.stem
        
        with open(fp, "r", encoding="utf-8") as f:
            item_data = json.load(f)
            
        bd = item_data.get("business_data", {})
        sub = bd.get("submission", {})
        stored_txn_type = sub.get("transaction_type", "")
        
        # Find raw file
        raw_files = list(submissions_dir.glob(f"*_{submission_id}_raw.json"))
        if not raw_files:
            continue
            
        with open(raw_files[0], "r", encoding="utf-8") as f:
            raw_data = json.load(f)
            
        parsed_dict = raw_data.get("_parsed", {})
        if not parsed_dict:
            continue
            
        try:
            bs = build_from_parsed(parsed_dict)
            recomputed_txn_type = bs.submission.transaction_type
        except Exception:
            continue
            
        if stored_txn_type != recomputed_txn_type:
            mismatches.append({
                "submission_id": submission_id,
                "old": stored_txn_type,
                "new": recomputed_txn_type,
                "file_path": fp,
                "item_data": item_data
            })
            
    print("\n=== BEFORE UPDATE: MISMATCHED RECORDS ===")
    if not mismatches:
        print("No mismatches found!")
    else:
        print(f"{'Submission':<25} | {'Old Type':<25} | {'New Type':<25}")
        print("-" * 81)
        for m in mismatches:
            print(f"{m['submission_id']:<25} | {m['old']:<25} | {m['new']:<25}")
            
    # 2. Update mismatched records
    if not dry_run and mismatches:
        print(f"\nUpdating {len(mismatches)} mismatched records...")
        for m in mismatches:
            item_data = m["item_data"]
            
            # Regression check: backup original state of other fields to verify no other edits are made
            orig_keys = set(item_data.keys())
            orig_business_data_keys = set(item_data.get("business_data", {}).keys())
            orig_submission_keys = set(item_data.get("business_data", {}).get("submission", {}).keys())
            
            # Check other critical fields
            orig_party_incoming = json.dumps(item_data.get("business_data", {}).get("incoming_tenant", {}), sort_keys=True)
            orig_missing_info = json.dumps(item_data.get("missing_info", []), sort_keys=True)
            orig_missing_docs = json.dumps(item_data.get("missing_docs", []), sort_keys=True)
            orig_status = item_data.get("status")
            
            # Update only the transaction_type
            item_data["business_data"]["submission"]["transaction_type"] = m["new"]
            
            # Verify no other fields added/removed/edited
            assert set(item_data.keys()) == orig_keys, "ReviewItem keys changed!"
            assert set(item_data["business_data"].keys()) == orig_business_data_keys, "BusinessData keys changed!"
            assert set(item_data["business_data"]["submission"].keys()) == orig_submission_keys, "Submission keys changed!"
            
            # Verify critical data remains unchanged
            assert json.dumps(item_data.get("business_data", {}).get("incoming_tenant", {}), sort_keys=True) == orig_party_incoming, "Party details changed!"
            assert json.dumps(item_data.get("missing_info", []), sort_keys=True) == orig_missing_info, "Missing info changed!"
            assert json.dumps(item_data.get("missing_docs", []), sort_keys=True) == orig_missing_docs, "Missing docs changed!"
            assert item_data.get("status") == orig_status, "Status changed!"
            
            # Overwrite file
            with open(m["file_path"], "w", encoding="utf-8") as f:
                json.dump(item_data, f, ensure_ascii=False, indent=2)
            print(f"Updated {m['submission_id']} -> {m['new']}")
            
    # 3. After update audit / verification
    reloaded_files = list(review_dir.glob("*.json"))
    after_results = []
    matches_count = 0
    mismatches_count = 0
    
    for fp in sorted(reloaded_files):
        submission_id = fp.stem
        
        with open(fp, "r", encoding="utf-8") as f:
            item_data = json.load(f)
            
        bd = item_data.get("business_data", {})
        sub = bd.get("submission", {})
        stored_txn_type = sub.get("transaction_type", "")
        
        raw_files = list(submissions_dir.glob(f"*_{submission_id}_raw.json"))
        if not raw_files:
            continue
            
        with open(raw_files[0], "r", encoding="utf-8") as f:
            raw_data = json.load(f)
            
        parsed_dict = raw_data.get("_parsed", {})
        if not parsed_dict:
            continue
            
        try:
            bs = build_from_parsed(parsed_dict)
            recomputed_txn_type = bs.submission.transaction_type
        except Exception:
            continue
            
        match = (stored_txn_type == recomputed_txn_type)
        if match:
            matches_count += 1
        else:
            mismatches_count += 1
            
        after_results.append({
            "submission_id": submission_id,
            "stored": stored_txn_type,
            "recomputed": recomputed_txn_type,
            "match": match
        })
        
    print("\n=== AFTER UPDATE: VERIFICATION AUDIT ===")
    print(f"{'Submission':<25} | {'Stored Type':<25} | {'Recomputed Type':<25} | {'Match?':<6}")
    print("-" * 88)
    for r in after_results:
        match_str = "Yes" if r["match"] else "No"
        print(f"{r['submission_id']:<25} | {r['stored']:<25} | {r['recomputed']:<25} | {match_str:<6}")
        
    print(f"\nVerification Summary:")
    print(f"Total: {len(after_results)}")
    print(f"Matches: {matches_count}")
    print(f"Mismatches: {mismatches_count}")
    
    if mismatches_count == 0:
        print("SUCCESS: 100% matches achieved.")
    else:
        print("ERROR: Stale mismatches still exist!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Perform audit only, do not write changes")
    args = parser.parse_args()
    
    run_backfill(dry_run=args.dry_run)
