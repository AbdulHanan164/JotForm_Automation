"""
Operator insights — STRICTLY READ-ONLY advisory signals.

Everything here is derived from data that already exists in a stored ReviewItem
(plus the document manifest on disk). Nothing in this module writes, updates,
approves, sends, merges or re-classifies anything: it only describes what is
already there so the operator can decide faster.

Design rules (enforced by review, not by the type system):
  * no file is ever opened for writing
  * no ReviewItem is ever mutated or saved
  * the existing pipeline, requirements engine and email generator are not
    called — their OUTPUT is read from the stored item
  * every number is explainable: each score reports the factors behind it

Consumed by app/routes/insights.py only.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

PLACEHOLDER = "לא סופק"
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
# An image smaller than this is often a screenshot of a screenshot, a crop, or
# a blank capture — worth a human glance before it is accepted as an ID.
_SMALL_IMAGE_BYTES = 15_000


# ── helpers ───────────────────────────────────────────────────────────────────

def _clean(value: Any) -> str:
    s = str(value or "").strip()
    return "" if s in ("", PLACEHOLDER, "—") else s


def _labels(items: list[dict] | None) -> list[str]:
    out = []
    for it in items or []:
        out.append(_clean(it.get("label")) if isinstance(it, dict) else _clean(it))
    return [x for x in out if x]


def _role(item: Any, name: str) -> dict:
    bd = getattr(item, "business_data", None) or {}
    r = bd.get(name) or {}
    return r if isinstance(r, dict) else {}


def _txn(item: Any) -> str:
    bd = getattr(item, "business_data", None) or {}
    return _clean((bd.get("submission") or {}).get("transaction_type"))


def _age_days(item: Any) -> float:
    raw = _clean(getattr(item, "received_at", ""))
    if not raw:
        return 0.0
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0)
    except Exception:
        return 0.0


def _manifest(submission_id: str) -> dict:
    """Read the document manifest. Read-only; returns {} when unavailable."""
    try:
        from app.config import settings
        path = os.path.join(str(settings.documents_dir), submission_id, "_manifest.json")
        if not os.path.isfile(path):
            return {}
        with open(path, encoding="utf-8") as fh:
            return json.load(fh) or {}
    except Exception:
        return {}


def _status(item: Any) -> str:
    """Plain status value. ReviewStatus is an Enum, so str() would yield
    "ReviewStatus.PENDING_REVIEW" and never match the stored value."""
    st = getattr(item, "status", "")
    return str(getattr(st, "value", st) or "")


def _issue_text(issue: dict) -> str:
    """The human-readable text of a validation issue.

    Real issues carry label/description/rule_triggered (not "message"), so
    reading only "message" produced the useless placeholder "validation issue".
    Preference order is most-descriptive-first.
    """
    for key in ("label", "description", "message", "rule_triggered", "rule"):
        v = _clean(issue.get(key))
        if v:
            return v
    return "validation issue"


def _whose_contact(item: Any, value: str, field: str) -> str:
    """Which participant a displayed contact value actually belongs to."""
    for role, who in (("incoming_tenant", "the incoming party"),
                      ("outgoing_tenant", "the outgoing party"),
                      ("landlord", "the owner"),
                      ("partner", "the second party")):
        if value and value == _clean(_role(item, role).get(field)):
            return who
    return "the submitter"


def _band(score: int, high: int = 80, mid: int = 55) -> str:
    return "high" if score >= high else ("medium" if score >= mid else "low")


# ── 1. confidence score ───────────────────────────────────────────────────────

def confidence(item: Any) -> dict:
    """How confident we can be that the parse captured this case correctly.

    Purely descriptive: it measures how much of what the operator needs was
    actually resolved, not whether the case should be approved.
    """
    factors: list[dict] = []

    def add(name: str, got: int, mx: int, note: str) -> None:
        factors.append({"name": name, "got": got, "max": mx, "note": note})

    name = _clean(getattr(item, "customer_name", ""))
    phone = _clean(getattr(item, "customer_phone", ""))
    email = _clean(getattr(item, "customer_email", ""))
    add("customer name", 10 if name else 0, 10, name or "not resolved")
    add("phone", 10 if phone else 0, 10, phone or "not resolved")
    add("email", 10 if email else 0, 10, email or "not resolved")

    mzk = _clean(getattr(item, "mzk_ref", ""))
    add("case reference", 10 if mzk else 0, 10, mzk or "no MZK")

    bd = getattr(item, "business_data", None) or {}
    prop = bd.get("property") or {}
    addr = _clean(getattr(item, "property_address", "")) or _clean(prop.get("full_address"))
    city = _clean(prop.get("city"))
    add("address", 10 if addr else 0, 10, addr or "not resolved")
    add("city", 5 if city else 0, 5, city or "not resolved")

    add("transaction type", 10 if _txn(item) else 0, 10, _txn(item) or "unclassified")

    roles = [r for r in ("incoming_tenant", "outgoing_tenant", "landlord", "partner")
             if _clean(_role(item, r).get("full_name"))]
    add("participants identified", min(10, len(roles) * 5), 10,
        ", ".join(roles) if roles else "none named")

    man = _manifest(getattr(item, "submission_id", ""))
    downloaded = int(man.get("downloaded") or 0)
    failed = int(man.get("failed") or 0)
    if man:
        doc_pts = 15 if (downloaded and not failed) else (7 if downloaded else 0)
        note = f"{downloaded} downloaded, {failed} failed"
    else:
        doc_pts, note = 0, "no manifest"
    add("documents retrieved", doc_pts, 15, note)

    issues = getattr(item, "validation_issues", None) or []
    errors = [i for i in issues if i.get("severity") == "error"]
    warns = [i for i in issues if i.get("severity") == "warning"]
    add("no contradictions", 10 if not errors else 0, 10,
        f"{len(errors)} error(s)" if errors else "none")
    add("no warnings", 5 if not warns else 0, 5,
        f"{len(warns)} warning(s)" if warns else "none")

    got = sum(f["got"] for f in factors)
    mx = sum(f["max"] for f in factors)
    score = int(round(100.0 * got / mx)) if mx else 0
    return {"score": score, "band": _band(score), "factors": factors,
            "got": got, "max": mx}


# ── 2. recommendation badge ───────────────────────────────────────────────────

def recommendation(item: Any) -> dict:
    """Advisory only — mirrors the decision the operator already makes."""
    mi = _labels(getattr(item, "missing_info", None))
    md = _labels(getattr(item, "missing_docs", None))
    issues = getattr(item, "validation_issues", None) or []
    errors = [i for i in issues if i.get("severity") == "error"]
    status = _status(item)

    if status not in ("pending_review", "needs_info"):
        return {"badge": "already handled", "tone": "neutral",
                "reason": f"status is {status} — no action suggested"}
    if errors:
        return {"badge": "Review carefully", "tone": "warn",
                "reason": f"{len(errors)} contradiction(s) need a human decision"}
    if mi or md:
        parts = []
        if mi:
            parts.append(f"{len(mi)} detail(s): " + ", ".join(mi[:4]))
        if md:
            parts.append(f"{len(md)} document(s): " + ", ".join(md[:4]))
        return {"badge": "Likely Needs Info", "tone": "info",
                "reason": "; ".join(parts)}
    return {"badge": "Likely Approve", "tone": "ok",
            "reason": "nothing missing and no contradictions found"}


# ── 3. queue priority ─────────────────────────────────────────────────────────

def priority(item: Any) -> dict:
    """Urgency for ordering attention. Display only — the queue is not re-sorted."""
    mi = _labels(getattr(item, "missing_info", None))
    md = _labels(getattr(item, "missing_docs", None))
    issues = getattr(item, "validation_issues", None) or []
    errors = [i for i in issues if i.get("severity") == "error"]
    age = _age_days(item)
    reasons: list[str] = []
    score = 0

    if not mi and not md:
        score += 50
        reasons.append("complete — ready for a decision")
    elif len(mi) + len(md) <= 2:
        score += 30
        reasons.append("almost complete — small follow-up")
    else:
        score += 10
        reasons.append(f"{len(mi) + len(md)} items outstanding")

    if errors:
        score += 25
        reasons.append(f"{len(errors)} contradiction(s)")

    aged = int(min(20, age * 2))
    if aged:
        score += aged
        reasons.append(f"waiting {age:.0f} day(s)")

    man = _manifest(getattr(item, "submission_id", ""))
    if man and int(man.get("failed") or 0):
        score += 10
        reasons.append("a document failed to download")

    if _status(item) == "needs_info":
        score += 5
        reasons.append("customer was already asked")

    score = max(0, min(100, score))
    band = "urgent" if score >= 70 else ("high" if score >= 45 else
                                        ("normal" if score >= 25 else "low"))
    return {"score": score, "band": band, "reasons": reasons,
            "age_days": round(age, 1)}


# ── 4. risk indicators ────────────────────────────────────────────────────────

def risk_flags(item: Any, type_counts: dict[str, int] | None = None) -> list[dict]:
    """Unusual signals worth a second look. Never blocks anything."""
    out: list[dict] = []
    add = lambda level, text: out.append({"level": level, "text": text})

    issues = getattr(item, "validation_issues", None) or []
    for i in issues:
        sev = i.get("severity")
        if sev in ("error", "warning"):
            add("high" if sev == "error" else "medium", _issue_text(i))

    if not _clean(getattr(item, "customer_email", "")):
        add("high", "no email address — the drafted letter has no recipient")
    if not _clean(getattr(item, "customer_phone", "")):
        add("medium", "no phone number")
    if not _clean(getattr(item, "customer_name", "")):
        add("high", "customer name not resolved")
    if not _clean(getattr(item, "property_address", "")):
        add("medium", "property address not resolved")

    man = _manifest(getattr(item, "submission_id", ""))
    if man:
        if int(man.get("failed") or 0):
            add("high", f"{man['failed']} document(s) failed to download")
        if not int(man.get("downloaded") or 0):
            add("high", "no documents were retrieved")
    else:
        add("medium", "no document manifest for this case")

    mi = _labels(getattr(item, "missing_info", None))
    md = _labels(getattr(item, "missing_docs", None))
    if len(mi) + len(md) >= 6:
        add("medium", f"{len(mi) + len(md)} outstanding items — unusually incomplete")

    txn = _txn(item)
    if not txn:
        add("high", "transaction type not classified")
    elif type_counts and type_counts.get(txn, 0) <= 1:
        add("low", f"rare transaction type in the current queue ({txn})")

    age = _age_days(item)
    if age >= 7:
        add("medium", f"waiting {age:.0f} days")

    return out


# ── 5. review summary ─────────────────────────────────────────────────────────

def summary_text(item: Any) -> list[str]:
    """A compact, one-glance recap of the case."""
    bd = getattr(item, "business_data", None) or {}
    prop = bd.get("property") or {}
    dates = bd.get("dates") or {}
    lines: list[str] = []
    lines.append(f"{_clean(getattr(item, 'customer_name', '')) or 'unnamed customer'}"
                 f" · {_clean(getattr(item, 'mzk_ref', '')) or getattr(item, 'submission_id', '')}")
    lines.append(f"Request: {_txn(item) or 'unclassified'}"
                 f" · services: {_clean(getattr(item, 'services', '')) or '—'}")
    lines.append(f"Property: {_clean(getattr(item, 'property_address', '')) or '—'}"
                 f" (city: {_clean(prop.get('city')) or '—'})")
    for role, label in (("incoming_tenant", "incoming"), ("outgoing_tenant", "outgoing"),
                        ("partner", "second"), ("landlord", "owner")):
        nm = _clean(_role(item, role).get("full_name"))
        if nm:
            lines.append(f"  {label}: {nm}")
    md = [f"{k}: {_clean(v)}" for k, v in dates.items() if _clean(v)]
    if md:
        lines.append("Dates: " + ", ".join(md))
    lines.append(f"Contact: {_clean(getattr(item, 'customer_phone', '')) or 'no phone'}"
                 f" / {_clean(getattr(item, 'customer_email', '')) or 'no email'}")
    mi = _labels(getattr(item, "missing_info", None))
    dm = _labels(getattr(item, "missing_docs", None))
    lines.append("Outstanding: "
                 + (", ".join(mi + dm) if (mi or dm) else "nothing — complete"))
    man = _manifest(getattr(item, "submission_id", ""))
    if man:
        lines.append(f"Documents on file: {man.get('downloaded', 0)}"
                     f" (failed {man.get('failed', 0)})")
    lines.append(f"Status: {_status(item)}")
    return lines


# ── 6. duplicate detection ────────────────────────────────────────────────────

def _ids(item: Any) -> set[str]:
    out = set()
    for role in ("incoming_tenant", "outgoing_tenant", "partner", "landlord"):
        v = _clean(_role(item, role).get("id_number"))
        if v:
            out.add(v)
    return out


def duplicates(item: Any, others: list[Any] | None) -> list[dict]:
    """Cases that may be the same customer or property. Never merges anything."""
    if not others:
        return []
    sid = getattr(item, "submission_id", "")
    mzk = _clean(getattr(item, "mzk_ref", ""))
    email = _clean(getattr(item, "customer_email", "")).lower()
    phone = _clean(getattr(item, "customer_phone", ""))
    addr = _clean(getattr(item, "property_address", ""))
    ids = _ids(item)

    found: list[dict] = []
    for other in others:
        osid = getattr(other, "submission_id", "")
        if not osid or osid == sid:
            continue
        why: list[str] = []
        strength = 0
        if mzk and mzk == _clean(getattr(other, "mzk_ref", "")):
            why.append("same case reference (MZK)"); strength = max(strength, 3)
        shared = ids & _ids(other)
        if shared:
            why.append("same ID number: " + ", ".join(sorted(shared))); strength = max(strength, 3)
        if email and email == _clean(getattr(other, "customer_email", "")).lower():
            why.append("same email"); strength = max(strength, 2)
        if phone and phone == _clean(getattr(other, "customer_phone", "")):
            why.append("same phone"); strength = max(strength, 2)
        if addr and addr == _clean(getattr(other, "property_address", "")):
            why.append("same property address"); strength = max(strength, 2)
        if why:
            found.append({
                "submission_id": osid,
                "mzk_ref": _clean(getattr(other, "mzk_ref", "")),
                "customer_name": _clean(getattr(other, "customer_name", "")),
                "status": _status(other),
                "reasons": why,
                "strength": {3: "strong", 2: "possible"}.get(strength, "weak"),
            })
    found.sort(key=lambda d: {"strong": 0, "possible": 1, "weak": 2}[d["strength"]])
    return found


# ── 7. consistency checker ────────────────────────────────────────────────────

def consistency(item: Any) -> list[dict]:
    """Contradictions between what is stored and what is being asked for.

    Reports only — nothing is corrected here.
    """
    out: list[dict] = []
    add = lambda level, text: out.append({"level": level, "text": text})

    for i in getattr(item, "validation_issues", None) or []:
        add(i.get("severity") or "info", _issue_text(i))

    mi = set(_labels(getattr(item, "missing_info", None)))
    bd = getattr(item, "business_data", None) or {}
    prop = bd.get("property") or {}

    # A contact can be on screen while still being requested, because the
    # requirement concerns the INCOMING party's own field. That is not a
    # contradiction when the two values belong to different participants, so the
    # message names whose value is shown instead of implying an inconsistency.
    for label_he, field, shown, article in (
            ("אימייל", "email", _clean(getattr(item, "customer_email", "")), "an email address"),
            ("טלפון", "phone", _clean(getattr(item, "customer_phone", "")), "a phone number")):
        if label_he not in mi or not shown:
            continue
        target = _clean(_role(item, "incoming_tenant").get(field))
        if target:
            add("warning", f"{article} is displayed, yet the case still asks for one")
        else:
            add("info", f"the request is for the incoming party's own {field}, which is "
                        f"empty — {article} shown ({shown}) belongs to "
                        f"{_whose_contact(item, shown, field)}, so this is not a contradiction")
    if "עיר" in mi and _clean(prop.get("city")):
        add("warning", "a city is displayed, yet the case still asks for one")
    if "עיר" in mi and not _clean(prop.get("city")):
        addr = _clean(getattr(item, "property_address", ""))
        if addr and "," in addr:
            add("info", "the city appears inside the address but the city field is empty")

    # a document is requested although a file with that label was downloaded
    man = _manifest(getattr(item, "submission_id", ""))
    stored_labels = set()
    for key in (man.get("files") or {}):
        stored_labels.add(key.split(".")[-1].split("#")[0])
    for label in _labels(getattr(item, "missing_docs", None)):
        if label in stored_labels:
            add("warning", f"'{label}' is requested although a file with that label was downloaded")

    inc, out_ = _role(item, "incoming_tenant"), _role(item, "outgoing_tenant")
    shown_phone = _clean(getattr(item, "customer_phone", ""))
    shown_email = _clean(getattr(item, "customer_email", ""))
    if shown_phone and shown_email:
        p_from = ("incoming" if shown_phone == _clean(inc.get("phone"))
                  else "outgoing" if shown_phone == _clean(out_.get("phone")) else "")
        e_from = ("incoming" if shown_email == _clean(inc.get("email"))
                  else "outgoing" if shown_email == _clean(out_.get("email")) else "")
        if p_from and e_from and p_from != e_from:
            add("error", f"phone belongs to the {p_from} party but email to the {e_from} party")

    if not out:
        add("ok", "no contradictions found")
    return out


# ── 8. document quality indicators ────────────────────────────────────────────

def document_quality(item: Any) -> dict:
    """Per-file indicators. Nothing is rejected; the operator decides."""
    sid = getattr(item, "submission_id", "")
    man = _manifest(sid)
    files: list[dict] = []
    notes: list[str] = []

    if not man:
        return {"files": [], "notes": ["no document manifest for this case"],
                "downloaded": 0, "failed": 0, "signature": False}

    try:
        from app.config import settings
        base = os.path.join(str(settings.documents_dir), sid)
    except Exception:
        base = ""

    for key, entry in (man.get("files") or {}).items():
        local = _clean(entry.get("local_path"))
        err = _clean(entry.get("error"))
        name = os.path.basename(local) if local else ""
        size = 0
        exists = False
        if local and base and os.path.isfile(local):
            exists = True
            try:
                size = os.path.getsize(local)
            except Exception:
                size = int(entry.get("size_bytes") or 0)
        else:
            size = int(entry.get("size_bytes") or 0)
        ext = os.path.splitext(name)[1].lower()

        flags: list[str] = []
        if err:
            flags.append(f"download failed: {err}")
        if local and not exists:
            flags.append("recorded but not present on disk")
        if exists and size == 0:
            flags.append("empty file")
        is_signature = "חתימה" in key or name.startswith("חתימה")
        if (exists and ext in _IMAGE_EXTS and not is_signature
                and 0 < size < _SMALL_IMAGE_BYTES):
            # Signature captures are normally only a few KB, so the rule is
            # applied to substantive documents (IDs, contracts) only.
            flags.append(f"very small image ({size} bytes) — may be illegible")
        if not ext:
            flags.append("no file extension")

        files.append({"key": key, "name": name or "(none)", "bytes": size,
                      "ext": ext or "—", "exists": exists,
                      "flags": flags, "ok": not flags})

    downloaded = int(man.get("downloaded") or 0)
    failed = int(man.get("failed") or 0)
    signature = any("חתימה" in f["key"] or f["name"].startswith("חתימה") for f in files)
    if failed:
        notes.append(f"{failed} document(s) failed to download")
    if not signature:
        notes.append("no signature file found for this case")
    small = [f for f in files if any("very small" in x for x in f["flags"])]
    if small:
        notes.append(f"{len(small)} image(s) look small enough to be worth checking")
    if not notes:
        notes.append("all retrieved files look plausible")
    return {"files": files, "notes": notes, "downloaded": downloaded,
            "failed": failed, "signature": signature}


# ── 9. operator insights ──────────────────────────────────────────────────────

def operator_insights(item: Any, dups: list[dict], docq: dict,
                      cons: list[dict], rec: dict) -> list[str]:
    """Plain-language suggestions. The operator takes every action."""
    tips: list[str] = []
    mi = _labels(getattr(item, "missing_info", None))
    md = _labels(getattr(item, "missing_docs", None))
    email = _clean(getattr(item, "customer_email", ""))
    phone = _clean(getattr(item, "customer_phone", ""))

    if rec.get("badge") == "Likely Approve":
        tips.append("Nothing outstanding was found — this case looks ready for your approval.")
    if mi or md:
        if email:
            tips.append(f"A letter is drafted for {email} requesting "
                        f"{len(mi)} detail(s) and {len(md)} document(s).")
        elif phone:
            tips.append(f"Items are outstanding but there is no email address — "
                        f"the phone on file is {phone}.")
        else:
            tips.append("Items are outstanding and there is neither an email nor a phone "
                        "number on file — contact details must be found first.")
    if docq.get("failed"):
        tips.append("At least one document did not download; the customer may need to resend it.")
    if not docq.get("signature", True):
        tips.append("No signature file is on record — worth confirming before approving.")
    for f in docq.get("files", []):
        for fl in f["flags"]:
            if "very small" in fl:
                tips.append(f"Open '{f['name']}' before accepting it — {fl}.")
    strong = [d for d in dups if d["strength"] == "strong"]
    if strong:
        tips.append("Possible duplicate of " +
                    ", ".join(f"{d['mzk_ref'] or d['submission_id']}" for d in strong) +
                    " — check before acting on both.")
    errs = [c for c in cons if c["level"] == "error"]
    if errs:
        tips.append("A contradiction was found in the data — resolve it before approving.")
    if not tips:
        tips.append("No specific suggestions — the case looks routine.")
    return tips


# ── aggregate ─────────────────────────────────────────────────────────────────

def build(item: Any, others: list[Any] | None = None,
          type_counts: dict[str, int] | None = None) -> dict:
    """All nine advisory signals for one case. Pure; performs no writes."""
    conf = confidence(item)
    rec = recommendation(item)
    prio = priority(item)
    dups = duplicates(item, others)
    docq = document_quality(item)
    cons = consistency(item)
    return {
        "submission_id": getattr(item, "submission_id", ""),
        "mzk_ref": _clean(getattr(item, "mzk_ref", "")),
        "customer_name": _clean(getattr(item, "customer_name", "")),
        "transaction_type": _txn(item),
        "status": _status(item),
        "confidence": conf,
        "recommendation": rec,
        "priority": prio,
        "risks": risk_flags(item, type_counts),
        "summary": summary_text(item),
        "duplicates": dups,
        "consistency": cons,
        "documents": docq,
        "tips": operator_insights(item, dups, docq, cons, rec),
        "advisory_only": True,
    }


def build_queue(items: list[Any]) -> list[dict]:
    """Compact per-case rows for the overview, highest priority first.

    Sorting here affects THIS view only — the real review queue and the
    dashboard list keep their existing order.
    """
    counts: dict[str, int] = {}
    for it in items:
        t = _txn(it)
        counts[t] = counts.get(t, 0) + 1

    rows = []
    for it in items:
        conf = confidence(it)
        rec = recommendation(it)
        prio = priority(it)
        risks = risk_flags(it, counts)
        dups = duplicates(it, items)
        rows.append({
            "submission_id": getattr(it, "submission_id", ""),
            "mzk_ref": _clean(getattr(it, "mzk_ref", "")),
            "customer_name": _clean(getattr(it, "customer_name", "")) or "—",
            "transaction_type": _txn(it) or "—",
            "status": _status(it),
            "confidence": conf["score"], "confidence_band": conf["band"],
            "recommendation": rec["badge"], "tone": rec["tone"],
            "priority": prio["score"], "priority_band": prio["band"],
            "age_days": prio["age_days"],
            "risk_count": len(risks),
            "high_risk": sum(1 for r in risks if r["level"] == "high"),
            "duplicate_count": len(dups),
            "missing_total": (len(_labels(getattr(it, "missing_info", None)))
                              + len(_labels(getattr(it, "missing_docs", None)))),
        })
    rows.sort(key=lambda r: (-r["priority"], -r["high_risk"], r["mzk_ref"]))
    return rows
