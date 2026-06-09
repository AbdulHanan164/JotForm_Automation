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
from typing import Any

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
        return data.get("content", []) if isinstance(data, dict) else []

    def get_submission(self, submission_id: str) -> dict[str, Any]:
        """Fetch a specific submission by ID."""
        return self._get(f"/submission/{submission_id}")

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
