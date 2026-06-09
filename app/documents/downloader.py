"""
Document Persistence — v0.6.0.

PROBLEM SOLVED:
  JotForm-uploaded documents (ID photos, lease PDFs) are served via
  temporary signed URLs that expire within hours to days. The system
  was storing these URLs in review queue JSON. After expiry, operators
  could no longer view documents for past submissions.

SOLUTION:
  On every webhook, immediately download all uploaded files and store
  them locally at:  data/documents/{submission_id}/{label}{ext}

  The parsed dict is updated to add a local_path key to each file field.
  The original JotForm URL is preserved as url for backward compatibility.

DESIGN CHOICES:
  - No new dependencies: uses stdlib urllib.request.
  - Non-blocking to individual failures: one bad download doesn't stop others.
  - Respects the existing parsed dict structure (section-keyed format).
  - JotForm file URLs may require the API key — handled if JOTFORM_API_KEY set.
  - Files are stored with the label as filename for human readability.

FILE LAYOUT:
  data/documents/
    {submission_id}/
      תעודת_זהות.jpg        ← ID photo
      חוזה_שכירות.pdf       ← lease agreement
      חתימה.png             ← signature
      חשבון_ארנונה.pdf      ← arnona bill
      _manifest.json        ← what was downloaded, when, from where
"""
from __future__ import annotations

import json
import logging
import mimetypes
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("downloader")

# Maximum file size to download (50 MB)
_MAX_BYTES = 50 * 1024 * 1024

# Download timeout in seconds
_TIMEOUT = 30

# File types that are expected for uploaded documents
_COMMON_EXTS = {
    "image/jpeg":       ".jpg",
    "image/png":        ".png",
    "image/gif":        ".gif",
    "application/pdf":  ".pdf",
    "image/tiff":       ".tiff",
    "image/webp":       ".webp",
}


def download_submission_documents(
    parsed:        dict[str, Any],
    submission_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Download all uploaded files for a submission.

    Walks all sections of the parsed dict looking for file/signature fields
    (identified by having a "url" key that starts with "http").

    Returns:
      (updated_parsed, manifest)
      - updated_parsed: same structure as parsed, but each file field now has
        a local_path key filled in if download succeeded.
      - manifest: {label: {url, local_path, size_bytes, downloaded_at, error}}
    """
    from app.config import settings
    docs_dir = settings.documents_dir / submission_id
    docs_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {}
    downloaded = 0
    failed = 0

    for section_name, section_data in parsed.items():
        if not isinstance(section_data, dict):
            continue

        for label, value in section_data.items():
            if not isinstance(value, dict):
                continue

            url = value.get("url", "")
            if not url or not url.startswith("http"):
                continue  # not a file URL — skip

            if value.get("local_path"):
                continue  # already downloaded

            # Download
            result = _download_file(url, docs_dir, label)
            manifest[f"{section_name}.{label}"] = result

            if result.get("local_path"):
                value["local_path"] = result["local_path"]
                downloaded += 1
                logger.info(
                    "Downloaded %s.%s → %s (%d bytes)",
                    section_name, label,
                    result["local_path"],
                    result.get("size_bytes", 0),
                )
            else:
                failed += 1
                logger.warning(
                    "Failed to download %s.%s from %s: %s",
                    section_name, label, url, result.get("error", "unknown"),
                )

    # Write manifest
    manifest_path = docs_dir / "_manifest.json"
    manifest_data = {
        "submission_id": submission_id,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "downloaded": downloaded,
        "failed": failed,
        "files": manifest,
    }
    try:
        manifest_path.write_text(
            json.dumps(manifest_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("Could not write manifest: %s", exc)

    logger.info(
        "Document download complete: %d downloaded, %d failed (submission %s)",
        downloaded, failed, submission_id,
    )

    return parsed, manifest_data


def _download_file(url: str, dest_dir: Path, label: str) -> dict[str, Any]:
    """
    Download a single file.

    Returns a result dict with:
      url, local_path (if success), size_bytes, downloaded_at, error (if fail)
    """
    result: dict[str, Any] = {
        "url":          url,
        "local_path":   "",
        "size_bytes":   0,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "error":        "",
    }

    try:
        # Add JotForm API key to URL if available
        request_url = _with_api_key(url)

        req = urllib.request.Request(
            request_url,
            headers={"User-Agent": "mazekal-webhook/0.6"},
        )

        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            content_type = resp.headers.get("Content-Type", "")
            ext = _guess_extension(url, content_type, label)

            # Sanitize label for use as filename
            safe_label = _safe_filename(label)
            local_path = dest_dir / f"{safe_label}{ext}"

            # Read with size limit
            data = _read_with_limit(resp)
            local_path.write_bytes(data)

            result["local_path"] = str(local_path)
            result["size_bytes"] = len(data)

    except urllib.error.HTTPError as exc:
        result["error"] = f"HTTP {exc.code}: {exc.reason}"
    except urllib.error.URLError as exc:
        result["error"] = f"URL error: {exc.reason}"
    except FileTooLargeError:
        result["error"] = f"File exceeds size limit ({_MAX_BYTES // 1024 // 1024} MB)"
    except Exception as exc:
        result["error"] = str(exc)

    return result


def _with_api_key(url: str) -> str:
    """Append JotForm API key to URL if configured."""
    try:
        from app.config import settings
        key = settings.jotform_api_key
        if key and "jotform.com" in url:
            sep = "&" if "?" in url else "?"
            return f"{url}{sep}apiKey={key}"
    except Exception:
        pass
    return url


def _guess_extension(url: str, content_type: str, label: str) -> str:
    """
    Determine file extension from content-type, URL, or label.
    Priority: content_type → URL path → label name → .bin fallback
    """
    # From content-type
    base_ct = content_type.split(";")[0].strip().lower()
    if base_ct in _COMMON_EXTS:
        return _COMMON_EXTS[base_ct]

    # From URL path
    url_path = url.split("?")[0]
    if "." in url_path.split("/")[-1]:
        url_ext = Path(url_path).suffix.lower()
        if url_ext:
            return url_ext

    # From label (e.g. label contains "pdf" or "jpg")
    label_lower = label.lower()
    if "pdf" in label_lower:
        return ".pdf"
    if "jpg" in label_lower or "jpeg" in label_lower:
        return ".jpg"
    if "png" in label_lower:
        return ".png"

    # Fallback
    return ".bin"


def _safe_filename(label: str) -> str:
    """Convert a Hebrew label to a safe filename."""
    # Keep Hebrew characters, replace spaces/slashes/dots with underscores
    safe = "".join(
        c if (c.isalnum() or c in "-_" or "֐" <= c <= "׿") else "_"
        for c in label
    )
    return safe.strip("_") or "document"


def _read_with_limit(resp) -> bytes:
    """Read response body with size limit."""
    chunks = []
    total = 0
    while True:
        chunk = resp.read(65536)  # 64 KB chunks
        if not chunk:
            break
        total += len(chunk)
        if total > _MAX_BYTES:
            raise FileTooLargeError(f"Exceeded {_MAX_BYTES} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


class FileTooLargeError(Exception):
    pass


def get_document_path(submission_id: str, label: str) -> Path | None:
    """
    Look up the local path for a downloaded document.
    Returns None if not found.
    """
    from app.config import settings
    docs_dir = settings.documents_dir / submission_id
    safe_label = _safe_filename(label)

    for ext in (".pdf", ".jpg", ".png", ".tiff", ".bin", ".webp"):
        path = docs_dir / f"{safe_label}{ext}"
        if path.exists():
            return path

    return None
