import json
import logging
from pathlib import Path

logger = logging.getLogger("webhook")

_SCHEMA_CACHE: dict[str, dict] = {}

def get_schema(form_id: str) -> dict | None:
    """
    Reads config/forms/{form_id}.json and caches it in memory.
    Returns None if file not found.
    """
    if not form_id:
        return None
    
    if form_id in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[form_id]
        
    schema_path = Path("config/forms") / f"{form_id}.json"
    if not schema_path.exists():
        logger.warning("Form schema file not found: %s", schema_path)
        return None
        
    try:
        with schema_path.open("r", encoding="utf-8") as f:
            schema = json.load(f)
            _SCHEMA_CACHE[form_id] = schema
            logger.info("Loaded and cached form schema for %s", form_id)
            return schema
    except Exception as e:
        logger.error("Failed to load schema for form %s: %s", form_id, e)
        return None
