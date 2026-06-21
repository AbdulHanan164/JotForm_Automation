import os
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from scratch.phase10c_validation import MATCHED_PAIRS, CACHE_PATH, download_to_temp
from app.pipeline.reconciliation_merge import ClassifierPipeline

def test():
    # Load cache
    with open(CACHE_PATH, encoding="utf-8") as f:
        all_subs = json.load(f)
    by_id = {s["id"]: s for s in all_subs}

    # Let's take the first 3 files
    pipeline = ClassifierPipeline()

    processed = 0
    for pair in MATCHED_PAIRS[:3]:
        mid = pair["missing_id"]
        sub = by_id.get(mid)
        if not sub:
            continue

        val = sub.get("answers", {}).get("38", {}).get("answer")
        url = val[0] if isinstance(val, list) else val
        if not url:
            continue

        processed += 1
        print(f"\n[{processed}] Downloading file from:", url)
        tmp = download_to_temp(url, ".jpeg")
        if not tmp:
            continue

        print(f"[{processed}] Running ClassifierPipeline on:", tmp)
        res = pipeline.classify(str(tmp))

        print(f"--- RESULT FOR {pair['orig_name']} ---")
        print(json.dumps(res, indent=2, ensure_ascii=False))
        print("-------------------------")

        # Cleanup
        try:
            tmp.unlink()
        except Exception:
            pass

if __name__ == "__main__":
    test()
