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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.documents.contracts import FileAnswer

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
            # Multi-file upload fields carry every URL in "urls"; "url" remains
            # the first one for single-file consumers.
            urls = [u for u in (value.get("urls") or []) if isinstance(u, str)]
            if not urls and url:
                urls = [url]
            urls = [u for u in urls if u.startswith("http")]
            if not urls:
                continue  # not a file URL — skip

            if value.get("local_path"):
                continue  # already downloaded

            local_paths: list[str] = []
            for idx, one_url in enumerate(urls):
                # The first file keeps the plain filename and manifest key, so
                # single-file behavior is byte-for-byte unchanged. Extras are
                # suffixed so nothing overwrites and every file is recorded.
                name_suffix = "" if idx == 0 else f"_{idx + 1}"
                key = (f"{section_name}.{label}" if idx == 0
                       else f"{section_name}.{label}#{idx + 1}")
                result = _download_file(one_url, docs_dir, label,
                                        name_suffix=name_suffix)
                manifest[key] = result

                if result.get("local_path"):
                    local_paths.append(result["local_path"])
                    downloaded += 1
                    logger.info(
                        "Downloaded %s → %s (%d bytes)",
                        key, result["local_path"], result.get("size_bytes", 0),
                    )
                else:
                    failed += 1
                    logger.warning(
                        "Failed to download %s from %s: %s",
                        key, one_url, result.get("error", "unknown"),
                    )

            if local_paths:
                value["local_path"] = local_paths[0]
                if len(local_paths) > 1:
                    value["local_paths"] = local_paths

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


def download_files(submission_id: str, files: list["FileAnswer"]) -> dict[str, Any]:
    """Download an explicit list of ``FileAnswer`` for a submission (Group A).

    Unlike ``download_submission_documents`` (which walks a parsed dict for http
    URLs), this takes a known list produced by the JotForm API adapter. Each
    file is downloaded independently — one failure never stops the rest — then
    persisted via ``storage.store_file`` and recorded in ``_manifest.json``.

    Returns the manifest dict:
      {submission_id, downloaded, failed, files: {key: entry}}
    where each entry carries source_url, local_path, size_bytes, sha256, error.
    """
    from app.documents import storage

    entries: dict[str, Any] = {}
    downloaded = 0
    failed = 0

    for fa in files:
        key = fa.question_id or fa.label or f"file_{len(entries)}"
        entry: dict[str, Any] = {
            "question_id":   fa.question_id,
            "doc_type":      fa.doc_type,
            "label":         fa.label,
            "source_url":    fa.url,
            "local_path":    "",
            "size_bytes":    0,
            "sha256":        "",
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "error":         "",
        }
        try:
            content, content_type = _fetch_bytes(fa.url)
            ext  = _guess_extension(fa.url, content_type, fa.label)
            path = storage.store_file(submission_id, fa, content, ext)
            entry["local_path"] = str(path)
            entry["size_bytes"] = len(content)
            entry["sha256"]     = storage.sha256_hex(content)
            downloaded += 1
            logger.info("download_files: %s → %s (%d bytes)", key, path, len(content))
        except FileTooLargeError:
            entry["error"] = f"File exceeds size limit ({_MAX_BYTES // 1024 // 1024} MB)"
            failed += 1
        except urllib.error.HTTPError as exc:
            entry["error"] = f"HTTP {exc.code}: {exc.reason}"
            failed += 1
        except urllib.error.URLError as exc:
            entry["error"] = f"URL error: {exc.reason}"
            failed += 1
        except Exception as exc:
            entry["error"] = str(exc)
            failed += 1

        if entry["error"]:
            logger.warning("download_files: %s failed: %s", key, entry["error"])
        entries[key] = entry

    manifest = {
        "submission_id": submission_id,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "downloaded":    downloaded,
        "failed":        failed,
        "files":         entries,
    }
    storage.write_manifest(submission_id, manifest)
    logger.info(
        "download_files complete: %d ok, %d failed (submission %s)",
        downloaded, failed, submission_id,
    )
    return manifest


def _fetch_bytes(url: str) -> tuple[bytes, str]:
    """Fetch a URL with the JotForm API key (if set), a timeout, and a size cap.

    Returns (content_bytes, content_type). Raises on HTTP/URL errors and
    FileTooLargeError — callers handle per-file isolation.
    """
    try:
        from app.config import settings
        timeout = settings.doc_download_timeout or _TIMEOUT
    except Exception:
        timeout = _TIMEOUT

    request_url = _with_api_key(url)
    req = urllib.request.Request(
        request_url,
        headers={"User-Agent": "mazekal-webhook/0.6"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content_type = resp.headers.get("Content-Type", "")
        data = _read_with_limit(resp)
    return data, content_type


def _download_file(url: str, dest_dir: Path, label: str,
                   name_suffix: str = "") -> dict[str, Any]:
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
            base_ct = content_type.split(";")[0].strip().lower()
            if base_ct in ("text/html", "application/xhtml+xml"):
                # An upload URL that is not accessible (missing api key, expired
                # link) answers with a redirect to an HTML page. Writing that to
                # disk as a .png would look like a successful download, so it is
                # recorded as the failure it actually is.
                result["error"] = (
                    f"expected a file but received {base_ct} "
                    "(upload URL not accessible)"
                )
                return result
            ext = _guess_extension(url, content_type, label)

            # Sanitize label for use as filename
            safe_label = _safe_filename(label)
            local_path = dest_dir / f"{safe_label}{name_suffix}{ext}"

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
    """Append JotForm API key to URL if configured, and ensure the URL is quoted properly."""
    try:
        from app.config import settings
        key = settings.jotform_api_key
        if key and "jotform.com" in url:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}apiKey={key}"
    except Exception:
        pass

    try:
        from urllib.parse import urlsplit, urlunsplit, quote
        parts = urlsplit(url)
        # safe includes '%' so an already-encoded path is not double-encoded
        # (%D7%90 must not become %25D7%2590); literal spaces and Hebrew in a
        # raw JotForm filename are still encoded correctly.
        quoted_path = quote(parts.path, safe='/%')
        url = urlunsplit((parts.scheme, parts.netloc, quoted_path, parts.query, parts.fragment))
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
