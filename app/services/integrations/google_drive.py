"""
Google Drive integration stub.

When ready to implement:
  pip install google-auth google-auth-oauthlib google-api-python-client
  Set GOOGLE_DRIVE_CREDENTIALS_PATH in .env
"""
from pathlib import Path
from typing import Any


def upload_summary(filepath: Path, folder_id: str = "") -> str:
    """Upload a summary JSON to Google Drive. Returns the file URL."""
    raise NotImplementedError

def upload_id_photo(image_base64: str, filename: str, folder_id: str = "") -> str:
    """Upload a base64 ID photo to Google Drive. Returns the file URL."""
    raise NotImplementedError
