"""
JotForm API client.

Fetches form definitions, questions, and conditional logic rules
directly from the JotForm API.

Configuration:
  JOTFORM_API_KEY in .env   — get from JotForm > Account > API
  JOTFORM_API_URL           — default: api.jotform.com

Endpoints used:
  GET /form/{formID}             — form metadata (title, status)
  GET /form/{formID}/questions   — all fields with types and labels
  GET /form/{formID}/properties  — conditional logic, settings

Rate limits: JotForm allows 1000 req/day on free, 10000 on paid plans.
Cache all responses in config/forms/{formID}.json to minimise API calls.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.documents.contracts import FileAnswer

logger = logging.getLogger("jotform.client")

CACHE_DIR = Path("config/forms")
CACHE_TTL_SECONDS = 3600 * 6   # re-fetch every 6 hours


def _cache_path(form_id: str) -> Path:
    return CACHE_DIR / f"{form_id}.json"


def _is_cache_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < CACHE_TTL_SECONDS


class JotFormClient:
    """
    Thin wrapper around the JotForm REST API.
    All responses are cached to config/forms/{formID}.json.
    """

    BASE = "https://api.jotform.com"

    def __init__(self, api_key: str):
        self.api_key = api_key
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # ── Public methods ────────────────────────────────────────────────────────

    def get_form_definition(self, form_id: str, force: bool = False) -> dict[str, Any]:
        """
        Return the full form definition: metadata + questions + properties.
        Uses local cache unless force=True or cache is stale.
        """
        cache = _cache_path(form_id)

        if not force and _is_cache_fresh(cache):
            logger.debug("Form %s loaded from cache", form_id)
            return json.loads(cache.read_text(encoding="utf-8"))

        logger.info("Fetching form %s from JotForm API...", form_id)
        definition = {
            "form_id":    form_id,
            "metadata":   self._get(f"/form/{form_id}"),
            "questions":  self._get(f"/form/{form_id}/questions"),
            "properties": self._get(f"/form/{form_id}/properties"),
            "fetched_at": time.time(),
        }

        cache.write_text(json.dumps(definition, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Form %s cached at %s", form_id, cache)
        return definition

    def get_submissions(self, form_id: str, limit: int = 20) -> list[dict]:
        """Fetch recent submissions for a form."""
        data = self._get(f"/form/{form_id}/submissions", params={"limit": limit})
        # _get already unwraps the {"content": ...} envelope, so the list arrives
        # directly. Keep the dict branch as a defensive fallback.
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("content", [])
        return []

    def get_submission(self, submission_id: str) -> dict[str, Any]:
        """Fetch a specific submission by ID."""
        return self._get(f"/submission/{submission_id}")

    def get_submission_files(self, submission_id: str) -> list["FileAnswer"]:
        """Return finalized downloadable files for a submission as FileAnswer[].

        This is the SINGLE adapter that depends on the JotForm Submission API
        response shape. It is built against JotForm's documented format
        (``answers`` keyed by question id, each with ``type``/``name``/
        ``answer``), where file-upload answers are a URL string or a list of
        URL strings.

        ⚠️ VALIDATE-LIVE (Group C): the exact serialization for THIS form's
        signature widget (base64 e-sign) vs file-upload fields must be confirmed
        against a real ``get_submission`` response before the document pipeline
        is enabled. Any correction stays inside this one method — nothing
        downstream consumes raw JotForm JSON.
        """
        from app.documents.contracts import FileAnswer
        from app.documents import storage

        data    = self.get_submission(submission_id)
        answers = data.get("answers", {}) if isinstance(data, dict) else {}
        qid_labels = _document_qid_labels()

        out: list[FileAnswer] = []
        for qid, ans in answers.items():
            if not isinstance(ans, dict):
                continue
            # Only JotForm-hosted uploads are real documents. This excludes
            # widget answers that are website/marketing links (e.g. a typeA
            # widget pointing at mazekal.co.il) — validated against a real
            # production submission (q185). Both file-upload fields and the
            # e-sign signature widget serve their files from jotform/uploads.
            urls = [u for u in _extract_file_urls(ans.get("answer")) if _is_jotform_upload(u)]
            if not urls:
                continue

            label    = qid_labels.get(str(qid), "") or ans.get("name") or ans.get("text") or ""
            doc_type = storage.doc_type_for_label(label)
            for url in urls:
                out.append(FileAnswer(
                    question_id = f"q{qid}",
                    doc_type    = doc_type,
                    label       = label,
                    url         = url,
                ))

        logger.info("get_submission_files(%s): %d file(s)", submission_id, len(out))
        return out

    # ── Internal HTTP ─────────────────────────────────────────────────────────

    def _get(self, path: str, params: dict | None = None) -> Any:
        try:
            import urllib.request, urllib.parse
            base_params = {"apiKey": self.api_key}
            if params:
                base_params.update(params)
            qs   = urllib.parse.urlencode(base_params)
            url  = f"{self.BASE}{path}?{qs}"
            req  = urllib.request.Request(url, headers={"User-Agent": "mazekal-webhook/0.5"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read().decode("utf-8")
                data = json.loads(body)
                # JotForm wraps responses in {"responseCode": 200, "content": {...}}
                return data.get("content", data)
        except Exception as exc:
            logger.error("JotForm API error %s: %s", path, exc)
            raise


def _is_jotform_upload(url: str) -> bool:
    """True only for JotForm-hosted upload URLs (the real document files).

    Matches www/eu/hipaa JotForm hosts under an /uploads/ path. Deliberately
    excludes arbitrary widget links (e.g. marketing URLs) that are not
    downloadable documents.
    """
    if not isinstance(url, str) or not url.startswith("http"):
        return False
    low = url.lower()
    return "jotform" in low and "/uploads/" in low


def _extract_file_urls(answer: Any) -> list[str]:
    """Pull downloadable http(s) URLs out of a JotForm answer value.

    Handles the documented shapes: a bare URL string, a list of URL strings,
    or a nested dict (some widgets). Non-URL values (e.g. base64 e-sign blobs)
    are ignored — they are not retrievable by URL.
    """
    if isinstance(answer, str):
        return [answer] if answer.startswith("http") else []
    if isinstance(answer, list):
        return [a for a in answer if isinstance(a, str) and a.startswith("http")]
    if isinstance(answer, dict):
        urls: list[str] = []
        for v in answer.values():
            urls.extend(_extract_file_urls(v))
        return urls
    return []


def _document_qid_labels() -> dict[str, str]:
    """Map numeric JotForm question id → Hebrew label for document fields.

    The webhook field map is keyed by ids like ``"q35_input35"`` while the
    Submission API keys answers by the numeric id ``"35"``. This bridges them
    so file answers can be tagged with their canonical doc label.
    """
    from app.services.arnona import field_map as fm

    out: dict[str, str] = {}
    for jfid, meta in fm.FIELD_MAP.items():
        if meta.get("section") != "documents":
            continue
        digits = "".join(c for c in jfid.split("_")[0] if c.isdigit())
        if digits:
            out[digits] = meta.get("label", "")
    return out


def get_client() -> JotFormClient | None:
    """Return a configured client or None if API key is not set."""
    try:
        from app.config import settings
        if not settings.jotform_api_key:
            logger.warning("JOTFORM_API_KEY not set — form sync disabled")
            return None
        return JotFormClient(settings.jotform_api_key)
    except Exception as exc:
        logger.error("Could not create JotForm client: %s", exc)
        return None
