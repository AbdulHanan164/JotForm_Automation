"""
Field-map ↔ JotForm schema validation.

The field map is the only place that binds this application to a JotForm form.
Historically a drift between the two failed *silently*: a renamed or deleted
question simply parsed empty, which surfaced much later as a phantom "missing
information" demand to a customer.

This module compares the configured field map against the cached JotForm form
definition and produces a report instead. It is read-only and never raises:
callers get a report they can log or serve.

Checks performed
  form_id_divergence  the field map declares a different form than the registry
  placeholders        entries whose id can never match a real field
  duplicate_ids       the same JotForm id mapped more than once
  duplicate_labels    the same (label, section) pair mapped more than once
  obsolete            a mapped id that no longer exists in the form
  renamed             the id still exists but the question's name changed
  unmapped_required   a question JotForm marks required that nothing maps
  unmapped            questions with no mapping at all (informational)
  label_contract      labels the code depends on that the map does not define
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("webhook")

# Verdicts, worst first — used for the overall status.
_STATUS_ORDER = ("error", "warning", "ok", "unknown")


def _numeric(jotform_id: str) -> str:
    """"q211_22211" -> "211";  "211" -> "211"."""
    s = str(jotform_id or "").strip()
    if s.startswith("q"):
        s = s[1:]
    num = ""
    for ch in s:
        if ch.isdigit():
            num += ch
        else:
            break
    return num


def load_questions(form_id: str) -> dict[str, dict] | None:
    """The cached JotForm questions, keyed by numeric question id.

    config/forms/{form_id}.json is the raw API response and the only cached
    artefact that carries question ids, names, types and required flags. The
    *_synced.json companion is a converted, label-oriented view with no ids, so
    it cannot support obsolete/renamed detection.

    Returns None when the form has never been synced.
    """
    import json
    from pathlib import Path
    path = Path("config/forms") / f"{form_id}.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:                               # pragma: no cover
        logger.warning("Could not read cached schema %s: %s", path, exc)
        return None
    questions = raw.get("questions")
    if isinstance(questions, dict):
        return {str(k): v for k, v in questions.items() if isinstance(v, dict)}
    return None


def _is_required(field: dict) -> bool:
    return str(field.get("required", "")).strip().lower() in ("yes", "true", "1")


def _is_presentational(field: dict) -> bool:
    """Headings, page breaks and the like carry no answer worth mapping."""
    return str(field.get("type", "")).lower() in (
        "control_head", "control_pagebreak", "control_text", "control_divider",
        "control_button", "control_collapse", "control_image",
    )


def label_contract() -> set[str]:
    """Labels the PARSER must be able to resolve through the field map.

    Derived from the requirement rules' visibility keys — each of which is a
    real form-field label the engine looks up by name — so the contract cannot
    drift from the code relying on it. A label listed here but absent from the
    map means a requirement can never be satisfied.

    Document-type vocabulary is deliberately excluded: those names identify
    documents the customer sends by other means, so they legitimately have no
    form field. They are reported by doc_vocabulary() for information only.
    """
    labels: set[str] = set()
    try:
        from app.rules.requirements import INFO_RULES
        for rule in INFO_RULES:
            key = getattr(rule, "visibility_key", None)
            if key:
                labels.add(key)
    except Exception:                                     # pragma: no cover
        pass
    return labels


def doc_vocabulary() -> set[str]:
    """Canonical document labels — informational, not part of the contract."""
    try:
        from app.core import doc_types as dt
        return {heb for heb, _en in dt.CANONICAL_TYPES.values() if heb}
    except Exception:                                     # pragma: no cover
        return set()


def validate_field_map(
    *,
    form_id: str,
    entries: list[dict],
    schema_questions: dict[str, dict] | None,
    declared_form_id: str = "",
) -> dict[str, Any]:
    """Compare a field map against a cached JotForm schema.

    entries: [{jotform_id, label, section, verified}, ...] — the YAML as loaded.
    schema_questions: {qid: question} from load_questions(), or None when the
    form has never been synced (then id-level checks are skipped, not guessed).
    """
    report: dict[str, Any] = {
        "form_id": form_id,
        "status": "ok",
        "schema_available": bool(schema_questions),
        "counts": {},
        "form_id_divergence": None,
        "placeholders": [],
        "duplicate_ids": [],
        "duplicate_labels": [],
        "obsolete": [],
        "renamed": [],
        "unmapped_required": [],
        "unmapped": [],
        "label_contract_missing": [],
        "hints": [],
    }

    from app.core import forms as form_registry

    if declared_form_id and form_id and declared_form_id != form_id:
        report["form_id_divergence"] = {
            "field_map_declares": declared_form_id, "registry_says": form_id,
        }

    seen_ids: dict[str, int] = {}
    seen_labels: dict[tuple[str, str], int] = {}
    mapped_numeric: set[str] = set()
    defined_labels: set[str] = set()

    for e in entries or []:
        jid = str(e.get("jotform_id") or "").strip()
        label = str(e.get("label") or "").strip()
        section = str(e.get("section") or "").strip()
        if label:
            defined_labels.add(label)
        if form_registry.is_placeholder(jid):
            report["placeholders"].append(
                {"jotform_id": jid, "label": label, "section": section})
            continue
        seen_ids[jid] = seen_ids.get(jid, 0) + 1
        key = (label, section)
        seen_labels[key] = seen_labels.get(key, 0) + 1
        num = _numeric(jid)
        if num:
            mapped_numeric.add(num)

    report["duplicate_ids"] = [
        {"jotform_id": k, "times": n} for k, n in sorted(seen_ids.items()) if n > 1]
    report["duplicate_labels"] = [
        {"label": k[0], "section": k[1], "times": n}
        for k, n in sorted(seen_labels.items()) if n > 1]

    missing_contract = sorted(label_contract() - defined_labels)
    report["label_contract_missing"] = missing_contract
    # Informational only — these identify documents, not form fields.
    report["doc_labels_without_form_field"] = sorted(doc_vocabulary() - defined_labels)

    if schema_questions:
        idx = dict(schema_questions)
        for e in entries or []:
            jid = str(e.get("jotform_id") or "").strip()
            if form_registry.is_placeholder(jid):
                continue
            num = _numeric(jid)
            if not num:
                continue
            field = idx.get(num)
            if field is None:
                report["obsolete"].append(
                    {"jotform_id": jid, "label": e.get("label", ""),
                     "reason": "question id not present in the current form"})
                continue
            name = str(field.get("name") or "").strip()
            # a webhook id looks like q<qid>_<name>; a changed name means the
            # webhook key changed even though the qid still exists
            if name and "_" in jid:
                suffix = jid.split("_", 1)[1]
                if suffix and name and suffix != name:
                    report["renamed"].append(
                        {"jotform_id": jid, "label": e.get("label", ""),
                         "schema_name": name,
                         "expected_key": f"q{num}_{name}"})
        for qid, field in sorted(idx.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0):
            if _is_presentational(field):
                continue
            if qid in mapped_numeric:
                continue
            item = {"qid": qid, "name": field.get("name", ""),
                    "text": (field.get("text") or "")[:80],
                    "type": field.get("type", "")}
            if _is_required(field):
                report["unmapped_required"].append(item)
            else:
                report["unmapped"].append(item)

    report["counts"] = {
        "entries": len(entries or []),
        "placeholders": len(report["placeholders"]),
        "duplicate_ids": len(report["duplicate_ids"]),
        "duplicate_labels": len(report["duplicate_labels"]),
        "obsolete": len(report["obsolete"]),
        "renamed": len(report["renamed"]),
        "unmapped_required": len(report["unmapped_required"]),
        "unmapped": len(report["unmapped"]),
        "label_contract_missing": len(missing_contract),
        "doc_labels_without_form_field": len(report["doc_labels_without_form_field"]),
    }

    # ── overall status ────────────────────────────────────────────────────────
    if not schema_questions:
        report["status"] = "unknown"
        report["hints"].append(
            f"No cached schema for form {form_id}. POST /admin/sync/{form_id} "
            "to fetch it, then re-run this validation.")
    if report["obsolete"] or report["renamed"] or report["duplicate_ids"] \
            or report["form_id_divergence"] or missing_contract:
        report["status"] = "error"
    elif report["placeholders"] or report["unmapped_required"] \
            or report["duplicate_labels"]:
        if report["status"] != "unknown":
            report["status"] = "warning"

    if report["placeholders"]:
        report["hints"].append(
            f"{len(report['placeholders'])} placeholder mapping(s) parse empty for "
            "every submission — GET /discover/{submission_id} reveals the real ids.")
    if report["renamed"]:
        report["hints"].append(
            "A question was renamed in JotForm: update jotform_id to the "
            "expected_key shown for each entry.")
    if report["unmapped_required"]:
        report["hints"].append(
            f"{len(report['unmapped_required'])} question(s) JotForm marks required "
            "have no mapping, so they can never be parsed or validated.")
    return report


def validate_arnona() -> dict[str, Any]:
    """Validate the production arnona field map against its cached schema."""
    from app.core import forms as form_registry
    form_id = form_registry.main_form_id()

    entries: list[dict] = []
    declared = ""
    try:
        import yaml
        from pathlib import Path
        doc = yaml.safe_load(Path("config/field_maps/arnona.yaml").read_text(
            encoding="utf-8")) or {}
        declared = str(doc.get("form_id") or "").strip()
        entries = [e for e in (doc.get("fields") or []) if isinstance(e, dict)]
    except Exception as exc:
        return {"form_id": form_id, "status": "error",
                "error": f"could not read field map: {exc}"}

    return validate_field_map(form_id=form_id, entries=entries,
                              schema_questions=load_questions(form_id),
                              declared_form_id=declared)


def log_summary(report: dict[str, Any]) -> None:
    """One-line startup summary — a drift is reported, never silent."""
    c = report.get("counts", {})
    status = report.get("status")
    msg = ("FIELD MAP VALIDATION [%s] form=%s entries=%s placeholders=%s "
           "obsolete=%s renamed=%s dup_ids=%s unmapped_required=%s "
           "label_contract_missing=%s")
    args = (status, report.get("form_id"), c.get("entries"), c.get("placeholders"),
            c.get("obsolete"), c.get("renamed"), c.get("duplicate_ids"),
            c.get("unmapped_required"), c.get("label_contract_missing"))
    if status == "error":
        logger.error(msg, *args)
    elif status in ("warning", "unknown"):
        logger.warning(msg, *args)
    else:
        logger.info(msg, *args)
    for hint in report.get("hints", []):
        logger.warning("FIELD MAP: %s", hint)
