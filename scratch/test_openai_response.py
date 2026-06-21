import os
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from scratch.phase10c_validation import MATCHED_PAIRS, CACHE_PATH, download_to_temp
from app.pipeline.reconciliation_merge import OpenAIVisionClassifier

def test():
    # Load cache
    with open(CACHE_PATH, encoding="utf-8") as f:
        all_subs = json.load(f)
    by_id = {s["id"]: s for s in all_subs}

    mid = MATCHED_PAIRS[0]["missing_id"]
    sub = by_id.get(mid)
    if not sub:
        print("Submission not found in cache")
        return

    # Get first url
    val = sub.get("answers", {}).get("38", {}).get("answer")
    url = val[0] if isinstance(val, list) else val
    if not url:
        print("No URL found for q38")
        return

    print("Downloading file from:", url)
    tmp = download_to_temp(url, ".jpeg")
    if not tmp:
        print("Download failed")
        return

    print("File downloaded to:", tmp)
    print("File size:", tmp.stat().st_size)

    # Initialize OpenAI classifier
    clf = OpenAIVisionClassifier()

    print("Calling OpenAI classifier with key configured in settings...")
    res = clf.classify(str(tmp))

    print("--- CLASSIFIER RESULT ---")
    print(json.dumps(res, indent=2, ensure_ascii=False))
    print("-------------------------")

    # Cleanup
    try:
        tmp.unlink()
    except Exception:
        pass

if __name__ == "__main__":
    test()
