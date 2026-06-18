"""
One-off, READ-ONLY validation of the JotForm submission adapter.

- Does NOT enable document jobs.
- Does NOT modify production behavior.
- Retrieves a real submission, inspects the raw shape, runs the adapter,
  and prints a REDACTED report (no names/emails/IDs printed).
- Saves the raw capture to data/ (gitignored) for local inspection only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from app.config import settings
from app.integrations.jotform.client import JotFormClient

FORM_ID = "250201745267957"


def _kind(answer):
    if answer is None or answer == "":
        return "empty"
    if isinstance(answer, str):
        return "url" if answer.startswith("http") else "text"
    if isinstance(answer, list):
        return "list"
    if isinstance(answer, dict):
        return "dict"
    return type(answer).__name__


def _redact_url(u: str) -> str:
    # show host + path shape, drop query string (may carry tokens)
    base = u.split("?")[0]
    return base


def main():
    if not settings.jotform_api_key:
        print("JOTFORM_API_KEY not set — aborting")
        sys.exit(1)

    client = JotFormClient(settings.jotform_api_key)

    print("=" * 70)
    print("STEP 1 — list recent submissions for form", FORM_ID)
    subs = client.get_submissions(FORM_ID, limit=10)
    print(f"  retrieved {len(subs)} submission(s)")
    if not subs:
        print("  no submissions found — aborting")
        sys.exit(2)

    # Prefer a submission that actually has file-type answers
    chosen = None
    for s in subs:
        answers = s.get("answers", {}) or {}
        has_file = any(
            (a.get("type", "").lower() in ("control_fileupload",)) or
            (isinstance(a.get("answer"), str) and a.get("answer", "").startswith("http")) or
            (isinstance(a.get("answer"), list) and any(str(x).startswith("http") for x in a.get("answer")))
            for a in answers.values() if isinstance(a, dict)
        )
        if has_file:
            chosen = s
            break
    chosen = chosen or subs[0]
    sub_id = chosen.get("id") or chosen.get("submissionID")
    print(f"  chosen submission id: {sub_id}")

    print("=" * 70)
    print("STEP 2 — get_submission(id): raw answer shape (REDACTED values)")
    raw = client.get_submission(sub_id)
    answers = raw.get("answers", {}) if isinstance(raw, dict) else {}
    print(f"  total answers: {len(answers)}")
    file_like = []
    for qid, ans in sorted(answers.items(), key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else 0):
        if not isinstance(ans, dict):
            continue
        atype = ans.get("type", "")
        name  = ans.get("name", "")
        k     = _kind(ans.get("answer"))
        if k in ("url", "list", "dict") or "file" in atype.lower() or "upload" in atype.lower():
            file_like.append((qid, atype, name, k, ans.get("answer")))
    print(f"  file-like answers: {len(file_like)}")
    for qid, atype, name, k, ans in file_like:
        sample = ""
        if k == "url":
            sample = _redact_url(ans)
        elif k == "list":
            sample = f"[{len(ans)} urls] " + ", ".join(_redact_url(str(x)) for x in ans[:2])
        elif k == "dict":
            sample = "keys=" + ",".join(list(ans.keys())[:6])
        print(f"    q{qid:<6} type={atype:<22} kind={k:<5} name={name!r}")
        if sample:
            print(f"            → {sample}")

    print("=" * 70)
    print("STEP 3 — get_submission_files(id): adapter output (FileAnswer[])")
    files = client.get_submission_files(sub_id)
    print(f"  FileAnswer count: {len(files)}")
    for fa in files:
        print(f"    qid={fa.question_id:<8} doc_type={fa.doc_type or '(unmapped)':<16} "
              f"label={fa.label!r:<18} url={_redact_url(fa.url)}")

    print("=" * 70)
    print("STEP 4 — cross-check: file-like answers vs mapped FileAnswers")
    print(f"  file-like raw answers : {len(file_like)}")
    print(f"  produced FileAnswers  : {len(files)}")
    mapped = sum(1 for f in files if f.doc_type)
    print(f"  mapped to doc_type    : {mapped}")
    print(f"  unmapped (→_unmapped) : {len(files) - mapped}")

    # Save raw capture (gitignored data/) for offline inspection
    out = settings.submissions_dir / f"_APIVALIDATION_{sub_id}.json"
    out.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=" * 70)
    print(f"raw capture saved (gitignored): {out}")
    print("DONE — no production behavior changed, document jobs still disabled.")


if __name__ == "__main__":
    main()
