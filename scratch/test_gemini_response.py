import os
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from scratch.phase10c_validation import MATCHED_PAIRS, CACHE_PATH, download_to_temp
from google import genai
from google.genai import types

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

    # Initialize Gemini client
    api_key = settings.gemini_api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("No GEMINI_API_KEY found")
        return

    print("Calling Gemini model gemini-2.5-flash...")
    client = genai.Client(api_key=api_key)

    # Call Gemini model
    prompt = """Examine the image and classify it. Respond ONLY with a JSON object:
{
  "document_type": "id_photo | lease_contract | arnona_bill",
  "confidence": 0.95,
  "reason": "..."
}"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            types.Part.from_bytes(data=tmp.read_bytes(), mime_type="image/jpeg"),
            prompt
        ],
        config=types.GenerateContentConfig(
            temperature=0.0,
            max_output_tokens=256,
            thinking_config=types.ThinkingConfig(thinking_budget=0)
        )
    )

    print("--- RESPONSE TEXT ---")
    print(repr(response.text))
    print("---------------------")
    if response.candidates:
        candidate = response.candidates[0]
        print("Finish Reason:", candidate.finish_reason)
        print("Safety Ratings:", candidate.safety_ratings)
        print("Usage Metadata:", response.usage_metadata)

    # Cleanup
    try:
        tmp.unlink()
    except Exception:
        pass

if __name__ == "__main__":
    test()
