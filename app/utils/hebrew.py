"""
Utility helpers for handling Hebrew / RTL text and Unicode escape sequences.
JotForm encodes Hebrew as \\uXXXX in rawRequest JSON — Python's json.loads
decodes these automatically. These helpers cover edge cases.
"""

import re


def decode_unicode_escapes(text: str) -> str:
    """
    Decode any remaining \\uXXXX sequences that survived JSON parsing.
    Safe no-op if the string is already decoded.
    """
    try:
        return text.encode("utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return text


def clean_text(value: str) -> str:
    """Strip whitespace and normalise line endings."""
    if not isinstance(value, str):
        return value
    return value.strip().replace("\r\n", "\n").replace("\r", "\n")


def is_base64_image(value: str) -> bool:
    """Return True if the value is an inline base64 data URI."""
    return isinstance(value, str) and value.startswith("data:image")


def strip_base64(value: str, placeholder: str = "[IMAGE_DATA]") -> str:
    """Replace inline base64 blobs with a short placeholder for logging."""
    if is_base64_image(value):
        mime = value.split(";")[0].replace("data:", "")
        length = len(value)
        return f"[BASE64 {mime} | {length} chars]"
    return value


def safe_str(value) -> str:
    """Convert any value to a clean string, handling dicts/lists gracefully."""
    if value is None:
        return ""
    if isinstance(value, dict):
        # e.g. date fields: {"day": "09", "month": "06", "year": "2026"}
        parts = [value.get("day", ""), value.get("month", ""), value.get("year", "")]
        non_empty = [p for p in parts if p]
        return "-".join(non_empty) if non_empty else str(value)
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def format_date(value) -> str:
    """
    Normalise JotForm date fields to DD-MM-YYYY.
    Accepts dict {"day": "09", "month": "06", "year": "2026"} or a string.
    """
    if isinstance(value, dict):
        day   = value.get("day", "")
        month = value.get("month", "")
        year  = value.get("year", "")
        if day and month and year:
            return f"{day.zfill(2)}-{month.zfill(2)}-{year}"
        # Empty/partial date widget ({"day":"","month":"","year":""}) — never
        # stringify the dict itself; an absent date is an empty string.
        return ""
    return safe_str(value)


def split_csv_field(value: str) -> list[str]:
    """Split a comma-separated Hebrew field into a clean list."""
    if not value:
        return []
    return [v.strip() for v in re.split(r"[,\n]+", value) if v.strip()]
