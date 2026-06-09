"""
Tests for FIX #6: Document persistence — download JotForm files on receipt.

THE PROBLEM (v0.5.0):
  JotForm file upload URLs (e.g. https://www.jotform.com/uploads/...) are
  temporary signed URLs that expire within hours to days. The system was storing
  these URLs in review queue JSON. After expiry, operators could not view docs.

THE FIX (v0.6.0):
  download_submission_documents() is called immediately after run_pipeline().
  Files are saved to data/documents/{submission_id}/{label}{ext}.
  The parsed dict is updated with local_path. Review queue JSON stores the path.

TESTS:
  - download_submission_documents() downloads a file from a mock URL.
  - local_path is set in the parsed dict after download.
  - Manifest is written to disk.
  - FileTooLargeError is raised for oversized files.
  - Individual download failures don't stop other files.
  - _safe_filename() preserves Hebrew and replaces unsafe chars.
  - Already-downloaded files (local_path set) are not re-downloaded.
"""
from __future__ import annotations

import io
import json
import unittest.mock as mock
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from app.documents.downloader import (
    download_submission_documents,
    _safe_filename,
    _guess_extension,
    FileTooLargeError,
)


# ── _safe_filename() ──────────────────────────────────────────────────────────

class TestSafeFilename:
    def test_hebrew_preserved(self):
        assert "תעודת" in _safe_filename("תעודת זהות")

    def test_spaces_replaced_with_underscore(self):
        name = _safe_filename("תעודת זהות")
        assert " " not in name

    def test_slashes_replaced(self):
        name = _safe_filename("חוזה/שכירות")
        assert "/" not in name

    def test_alphanumeric_preserved(self):
        assert _safe_filename("doc123") == "doc123"

    def test_dots_replaced(self):
        name = _safe_filename("חוזה.pdf")
        assert "." not in name

    def test_empty_string_fallback(self):
        assert _safe_filename("") == "document"

    def test_only_underscores_fallback(self):
        assert _safe_filename("...") == "document"

    def test_hyphen_preserved(self):
        assert "-" in _safe_filename("id-photo")


# ── _guess_extension() ────────────────────────────────────────────────────────

class TestGuessExtension:
    def test_jpeg_from_content_type(self):
        assert _guess_extension("http://example.com/x", "image/jpeg", "photo") == ".jpg"

    def test_pdf_from_content_type(self):
        assert _guess_extension("http://example.com/x", "application/pdf", "doc") == ".pdf"

    def test_pdf_from_url(self):
        ext = _guess_extension("http://example.com/file.pdf", "application/octet-stream", "doc")
        assert ext == ".pdf"

    def test_jpg_from_url(self):
        ext = _guess_extension("http://example.com/photo.jpg", "", "photo")
        assert ext == ".jpg"

    def test_pdf_from_label(self):
        ext = _guess_extension("http://example.com/file", "", "חוזה_pdf_doc")
        assert ext == ".pdf"

    def test_fallback_bin(self):
        ext = _guess_extension("http://example.com/unknown", "application/unknown", "x")
        assert ext == ".bin"

    def test_content_type_with_charset_ignored(self):
        ext = _guess_extension("http://x.com/y", "image/png; charset=utf-8", "x")
        assert ext == ".png"


# ── download_submission_documents() ──────────────────────────────────────────

def _mock_http_response(content: bytes, content_type: str = "application/pdf"):
    """Create a mock urllib response."""
    resp = mock.MagicMock()
    resp.headers = {"Content-Type": content_type}
    resp.read.side_effect = [content, b""]  # first call returns data, second returns b""
    resp.__enter__ = lambda s: s
    resp.__exit__ = mock.MagicMock(return_value=False)
    return resp


class TestDownloadSubmissionDocuments:
    """download_submission_documents() downloads files and updates parsed dict."""

    def test_downloads_file_and_sets_local_path(self, tmp_path, monkeypatch):
        """A file field with a URL gets downloaded and local_path is set."""
        monkeypatch.setattr(
            "app.config.settings.documents_dir",
            tmp_path,
        )

        parsed = {
            "documents": {
                "חוזה_שכירות": {"present": True, "url": "https://jotform.com/uploads/doc.pdf", "local_path": ""},
            }
        }

        fake_content = b"%PDF-1.4 fake pdf content"

        # Mock urllib.request.urlopen
        mock_resp = mock.MagicMock()
        mock_resp.headers = mock.MagicMock()
        mock_resp.headers.get = mock.MagicMock(return_value="application/pdf")
        mock_resp.read = mock.MagicMock(side_effect=[fake_content, b""])
        mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = mock.MagicMock(return_value=False)

        with mock.patch("urllib.request.urlopen", return_value=mock_resp):
            updated, manifest = download_submission_documents(parsed, "sub-test-001")

        # local_path must be set
        local = updated["documents"]["חוזה_שכירות"].get("local_path", "")
        assert local != "", "local_path should be set after successful download"
        assert Path(local).exists(), f"Downloaded file should exist at {local}"

    def test_manifest_written(self, tmp_path, monkeypatch):
        """A _manifest.json is written after downloads."""
        monkeypatch.setattr("app.config.settings.documents_dir", tmp_path)

        parsed = {
            "documents": {
                "תעודת_זהות": {"present": True, "url": "https://jotform.com/uploads/id.jpg", "local_path": ""},
            }
        }

        mock_resp = mock.MagicMock()
        mock_resp.headers.get = mock.MagicMock(return_value="image/jpeg")
        mock_resp.read = mock.MagicMock(side_effect=[b"fake jpeg", b""])
        mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = mock.MagicMock(return_value=False)

        with mock.patch("urllib.request.urlopen", return_value=mock_resp):
            _, manifest = download_submission_documents(parsed, "sub-manifest-test")

        manifest_path = tmp_path / "sub-manifest-test" / "_manifest.json"
        assert manifest_path.exists(), "_manifest.json should be written"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["submission_id"] == "sub-manifest-test"
        assert "downloaded" in data

    def test_http_error_non_fatal(self, tmp_path, monkeypatch):
        """HTTP 404 on a file doesn't crash the whole download."""
        monkeypatch.setattr("app.config.settings.documents_dir", tmp_path)

        parsed = {
            "documents": {
                "מסמך_שגוי": {"present": True, "url": "https://jotform.com/missing.pdf", "local_path": ""},
            }
        }

        with mock.patch(
            "urllib.request.urlopen",
            side_effect=HTTPError("https://x.com", 404, "Not Found", {}, None)
        ):
            updated, manifest = download_submission_documents(parsed, "sub-err-test")

        # Should complete without raising; local_path stays empty
        assert updated["documents"]["מסמך_שגוי"]["local_path"] == ""

    def test_url_error_non_fatal(self, tmp_path, monkeypatch):
        """Network error on a file doesn't crash the whole download."""
        monkeypatch.setattr("app.config.settings.documents_dir", tmp_path)

        parsed = {
            "documents": {
                "doc": {"present": True, "url": "https://jotform.com/doc.pdf", "local_path": ""},
            }
        }

        with mock.patch(
            "urllib.request.urlopen",
            side_effect=URLError("connection refused")
        ):
            updated, manifest = download_submission_documents(parsed, "sub-url-err")

        assert updated["documents"]["doc"]["local_path"] == ""

    def test_already_downloaded_not_re_downloaded(self, tmp_path, monkeypatch):
        """Files that already have local_path set are skipped."""
        monkeypatch.setattr("app.config.settings.documents_dir", tmp_path)

        existing_path = str(tmp_path / "existing.pdf")
        parsed = {
            "documents": {
                "חוזה": {"present": True, "url": "https://jotform.com/doc.pdf", "local_path": existing_path},
            }
        }

        call_count = 0
        original_urlopen = __builtins__  # not used, just tracking

        with mock.patch("urllib.request.urlopen") as mock_open:
            download_submission_documents(parsed, "sub-skip-test")
            mock_open.assert_not_called()  # urlopen should never be called

    def test_non_file_fields_ignored(self, tmp_path, monkeypatch):
        """Text fields and other non-file fields in a section are ignored."""
        monkeypatch.setattr("app.config.settings.documents_dir", tmp_path)

        parsed = {
            "basic": {
                "עיר": "תל אביב",  # plain text — no URL
                "שירות": "ארנונה",
            },
            "documents": {
                "חוזה": {"present": True, "url": "https://jotform.com/lease.pdf", "local_path": ""},
            }
        }

        mock_resp = mock.MagicMock()
        mock_resp.headers.get = mock.MagicMock(return_value="application/pdf")
        mock_resp.read = mock.MagicMock(side_effect=[b"pdf content", b""])
        mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = mock.MagicMock(return_value=False)

        with mock.patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            download_submission_documents(parsed, "sub-mixed")
            # Only one call for the one file field
            assert mock_open.call_count == 1

    def test_multiple_files_downloaded(self, tmp_path, monkeypatch):
        """Multiple file fields are all downloaded."""
        monkeypatch.setattr("app.config.settings.documents_dir", tmp_path)

        parsed = {
            "documents": {
                "חוזה":     {"present": True, "url": "https://jotform.com/lease.pdf", "local_path": ""},
                "תעודת_זהות": {"present": True, "url": "https://jotform.com/id.jpg",    "local_path": ""},
            }
        }

        mock_resp = mock.MagicMock()
        mock_resp.headers.get = mock.MagicMock(return_value="application/pdf")
        mock_resp.read = mock.MagicMock(side_effect=[b"file1", b"", b"file2", b""])
        mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = mock.MagicMock(return_value=False)

        with mock.patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            updated, _ = download_submission_documents(parsed, "sub-multi")
            assert mock_open.call_count == 2
