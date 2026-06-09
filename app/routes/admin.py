"""
Admin routes — v0.5.0

Routes:
  POST /admin/sync/{form_id}     — force re-sync a form from JotForm API
  POST /admin/sync/all           — sync all registered forms
  GET  /admin/forms              — list all synced form definitions
  GET  /admin/forms/{form_id}    — show synced definition for a form
  GET  /admin/services           — list all registered services (Python + YAML)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

from app.integrations.jotform.client import get_client
from app.integrations.jotform.sync import FormSync, load_synced_definition

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger("admin")

# All registered form IDs (Python-coded + YAML)
_KNOWN_FORM_IDS = [
    "251955479892982",   # arnona transfer
    # Add more as you create them
]


@router.post("/sync/{form_id}", summary="Force sync a form from JotForm API")
def sync_form(form_id: str, force: bool = True):
    """
    Pull the latest form definition from JotForm and update the local cache.
    Requires JOTFORM_API_KEY in .env.

    Returns the synced field count, rule count, and a YAML field map stub
    that can be pasted into config/services/{service}.yaml.
    """
    client = get_client()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "JotForm API key not configured. "
                "Add JOTFORM_API_KEY to .env and restart."
            ),
        )

    sync    = FormSync(client)
    result  = sync.sync_form(form_id, force=force)

    if not result.success:
        raise HTTPException(
            status_code=502,
            detail=f"JotForm sync failed for {form_id}: {result.error}",
        )

    return {
        "status":      "synced",
        "form_id":     result.form_id,
        "form_title":  result.form_title,
        "field_count": result.field_count,
        "rule_count":  result.rule_count,
        "yaml_stub":   result.yaml_stub,
        "next_step": (
            "Copy yaml_stub into config/services/{service}.yaml, "
            "verify section assignments, fill in required: values, "
            "then restart the server."
        ),
    }


@router.post("/sync/all", summary="Sync all known forms")
def sync_all_forms(force: bool = False):
    """Sync all registered form IDs."""
    client = get_client()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="JotForm API key not configured.",
        )

    sync    = FormSync(client)
    results = sync.sync_all(_KNOWN_FORM_IDS, force=force)

    return {
        "synced": [r.to_dict() for r in results if r.success],
        "failed": [r.to_dict() for r in results if not r.success],
    }


@router.get("/forms", summary="List all cached form definitions")
def list_forms():
    """List all forms that have been synced from JotForm."""
    forms_dir = Path("config/forms")
    synced_files = sorted(forms_dir.glob("*_synced.json")) if forms_dir.exists() else []

    forms = []
    for f in synced_files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            forms.append({
                "form_id":     data.get("form_id"),
                "form_title":  data.get("form_title"),
                "synced_at":   data.get("synced_at"),
                "field_count": data.get("field_count"),
                "rule_count":  data.get("rule_count"),
            })
        except Exception:
            pass

    return {"count": len(forms), "forms": forms}


@router.get("/forms/{form_id}", summary="Full synced definition for a form")
def get_form_definition(form_id: str):
    """Return the full synced form definition including fields and rules."""
    defn = load_synced_definition(form_id)
    if defn is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No synced definition for {form_id}. "
                f"Run POST /admin/sync/{form_id} first."
            ),
        )
    return JSONResponse(content=defn)


@router.get("/forms/{form_id}/yaml", summary="YAML field map stub for a form")
def get_form_yaml(form_id: str):
    """Return the auto-generated YAML stub for pasting into config/services/."""
    defn = load_synced_definition(form_id)
    if defn is None:
        raise HTTPException(status_code=404, detail=f"No synced definition for {form_id}.")
    yaml_stub = defn.get("yaml_stub", "# No YAML stub available")
    return PlainTextResponse(yaml_stub, media_type="text/plain; charset=utf-8")


@router.get("/services", summary="List all registered services")
def list_services():
    """Show all services registered in the pipeline (Python + YAML)."""
    from app.pipeline.orchestrator import _SERVICES
    services = []
    for form_id, svc in _SERVICES.items():
        services.append({
            "form_id":      form_id,
            "service_name": getattr(svc, "service_name", str(svc)),
            "type": (
                "yaml_driven"
                if svc.__class__.__name__ == "YAMLDrivenService"
                else "python_coded"
            ),
        })
    return {"count": len(services), "services": services}
