"""
Google Sheets Integration — מה זה קל Review Dashboard.

PURPOSE:
  After each webhook submission is processed, write a row to the
  operator's Google Sheet so the team can track all requests in one place.

SETUP:
  1. Create a Google Cloud project and enable the Sheets API.
  2. Create a Service Account → download credentials.json
  3. Share the Google Sheet with the service account email
     (e.g. jotform-bot@project.iam.gserviceaccount.com)
  4. Set GOOGLE_SHEETS_CREDENTIALS_PATH=/path/to/credentials.json in .env
  5. Set the google_sheet_id in config/services/arnona.yaml

DEPENDENCIES (add to requirements.txt when ready):
  google-auth>=2.0
  google-auth-httplib2>=0.1
  google-api-python-client>=2.0

CURRENT STATE: Mock-ready interface.
  - If credentials are not configured → logs a warning, skips silently.
  - If credentials ARE configured → writes real rows via the Sheets API.
  - Same interface either way — no code changes needed when you enable it.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("google_sheets")


class GoogleSheetsClient:
    """
    Thin wrapper around the Google Sheets API v4.
    All methods are safe to call even if credentials are not configured —
    they log a warning and return without raising.
    """

    def __init__(self, credentials_path: str):
        self.credentials_path = credentials_path
        self._service = None
        self._ready   = False
        self._init()

    def _init(self):
        if not self.credentials_path:
            logger.info("Google Sheets: no credentials path — running in mock mode")
            return
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            scopes = ["https://www.googleapis.com/auth/spreadsheets"]
            creds  = service_account.Credentials.from_service_account_file(
                self.credentials_path, scopes=scopes
            )
            self._service = build("sheets", "v4", credentials=creds)
            self._ready   = True
            logger.info("Google Sheets: connected")
        except ImportError:
            logger.warning(
                "Google Sheets: google-api-python-client not installed. "
                "Run: pip install google-auth google-auth-httplib2 google-api-python-client"
            )
        except Exception as exc:
            logger.error("Google Sheets init error: %s", exc)

    @property
    def is_ready(self) -> bool:
        return self._ready

    def append_row(
        self,
        spreadsheet_id: str,
        tab_name: str,
        values: list[Any],
    ) -> bool:
        """
        Append a single row to the sheet.
        Returns True on success, False on failure.
        """
        if not self._ready:
            logger.debug(
                "Google Sheets (mock): would append %d values to %s/%s",
                len(values), spreadsheet_id, tab_name,
            )
            return False

        try:
            body = {"values": [values]}
            self._service.spreadsheets().values().append(
                spreadsheetId  = spreadsheet_id,
                range          = f"{tab_name}!A1",
                valueInputOption = "USER_ENTERED",
                insertDataOption = "INSERT_ROWS",
                body           = body,
            ).execute()
            logger.info(
                "Sheets: appended row to %s/%s", spreadsheet_id, tab_name
            )
            return True
        except Exception as exc:
            logger.error("Sheets append error: %s", exc)
            return False

    def update_row(
        self,
        spreadsheet_id: str,
        tab_name:       str,
        row_index:      int,
        values:         list[Any],
    ) -> bool:
        """Update a specific row (1-indexed)."""
        if not self._ready:
            logger.debug("Google Sheets (mock): would update row %d", row_index)
            return False

        try:
            range_  = f"{tab_name}!A{row_index}"
            body    = {"values": [values]}
            self._service.spreadsheets().values().update(
                spreadsheetId    = spreadsheet_id,
                range            = range_,
                valueInputOption = "USER_ENTERED",
                body             = body,
            ).execute()
            return True
        except Exception as exc:
            logger.error("Sheets update error: %s", exc)
            return False

    def find_row_by_submission_id(
        self,
        spreadsheet_id: str,
        tab_name:       str,
        submission_id:  str,
        id_column:      int = 0,
    ) -> int | None:
        """
        Search for a row where column[id_column] == submission_id.
        Returns 1-indexed row number or None.
        """
        if not self._ready:
            return None
        try:
            resp = self._service.spreadsheets().values().get(
                spreadsheetId = spreadsheet_id,
                range         = f"{tab_name}!A:A",
            ).execute()
            rows = resp.get("values", [])
            for i, row in enumerate(rows):
                if row and row[0] == submission_id:
                    return i + 1   # 1-indexed
            return None
        except Exception as exc:
            logger.error("Sheets find error: %s", exc)
            return None


# ── Pipeline result → sheet row converter ────────────────────────────────────

def result_to_row(result, column_config: list[dict]) -> list[Any]:
    """
    Build a sheet row from a PipelineResult using the column config
    from the service YAML (google_sheets.columns).

    column_config example:
      [{"key": "submission_id", "header": "מזהה הגשה"},
       {"key": "city", "source_field": "עיר", "header": "עיר"}, ...]
    """
    row: list[Any] = []

    for col in column_config:
        key          = col.get("key", "")
        source_field = col.get("source_field")

        if source_field:
            # Pull from parsed fields
            value = result.parsed.get(source_field, "")
        elif key == "submission_id":
            value = result.submission_id
        elif key == "received_at":
            value = result.received_at
        elif key == "review_status":
            value = result.review_status
        elif key == "is_complete":
            value = "כן" if result.is_complete else "לא"
        elif key == "missing_count":
            value = len(result.missing.get("missing_info", []))
        elif key == "error_count":
            value = result.error_count
        elif key == "warning_count":
            value = result.warning_count
        elif key == "customer_name":
            customer = result.summary.get("דייר_נכנס", {})
            value = customer.get("שם", "")
        elif key == "customer_phone":
            customer = result.summary.get("דייר_נכנס", {})
            value = customer.get("טלפון", "")
        elif key == "address":
            value = result.summary.get("כתובת", "")
        elif key == "city":
            value = result.parsed.get("עיר", "")
        elif key == "services":
            value = result.parsed.get("שירות", "")
        else:
            value = ""

        row.append(str(value) if value else "")

    return row


def write_submission_to_sheets(
    result,
    sheet_id:      str,
    tab_name:      str,
    column_config: list[dict],
) -> bool:
    """
    Convenience function: write a pipeline result to Google Sheets.
    Creates client from config, appends row.
    Returns True on success.
    """
    try:
        from app.config import settings
        client = GoogleSheetsClient(settings.google_sheets_credentials_path)
        row    = result_to_row(result, column_config)
        return client.append_row(sheet_id, tab_name, row)
    except Exception as exc:
        logger.error("write_submission_to_sheets error: %s", exc)
        return False


# ── Singleton ─────────────────────────────────────────────────────────────────

_client: GoogleSheetsClient | None = None


def get_client() -> GoogleSheetsClient:
    """Return (or create) the singleton Sheets client."""
    global _client
    if _client is None:
        try:
            from app.config import settings
            _client = GoogleSheetsClient(settings.google_sheets_credentials_path)
        except Exception:
            _client = GoogleSheetsClient("")
    return _client
