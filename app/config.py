"""
Application configuration — v0.6.0.

All secrets come from .env (never committed to git).
See .env.example for the full list of required variables.
"""
from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    app_name:    str  = "JotForm Webhook Receiver"
    app_version: str  = "0.6.0"
    debug:       bool = False
    log_level:   str  = "INFO"

    # ── Data directories ──────────────────────────────────────────────────────
    submissions_dir:   Path = Path("data/submissions")    # raw full payloads
    processed_dir:     Path = Path("data/processed")      # clean business summaries
    review_dir:        Path = Path("data/review_queue")   # human review queue
    documents_dir:     Path = Path("data/documents")      # downloaded uploaded files
    document_jobs_dir: Path = Path("data/document_jobs")  # durable doc-acquisition jobs
    logs_dir:          Path = Path("logs")

    # ── Document acquisition (Group A infra) ──────────────────────────────────
    # enable_document_jobs: feature flag for the background document pipeline
    #   (Group B). OFF by default → the webhook keeps its current behavior
    #   exactly. Only flip ON after the JotForm API response shape is validated
    #   against a real submission.
    enable_document_jobs: bool = False
    doc_download_timeout: int  = 30   # seconds per file
    doc_max_attempts:     int  = 3    # job retry cap

    # ── Security — MUST be set before production ──────────────────────────────
    #
    # OPERATOR_API_KEY  — protects the review, admin, submissions, and discover
    #                     endpoints. Use a strong random string (32+ chars).
    #                     Generate: python -c "import secrets; print(secrets.token_urlsafe(32))"
    #
    # WEBHOOK_SECRET    — added as ?token= query param in the JotForm webhook URL.
    #                     JotForm: Settings → Integrations → Webhook → URL:
    #                       https://yourserver.com/webhook?token=<WEBHOOK_SECRET>
    #                     Generate: python -c "import secrets; print(secrets.token_urlsafe(32))"
    #
    operator_api_key: str = ""   # "" = auth DISABLED (dev/test only)
    webhook_secret:   str = ""   # "" = signature check DISABLED (dev/test only)

    # ── JotForm API — form sync ───────────────────────────────────────────────
    # Get from: JotForm > Account > API  (https://www.jotform.com/myaccount/api)
    jotform_api_key: str = ""

    # ── Google Sheets — review dashboard ─────────────────────────────────────
    # Path to service account credentials JSON file
    google_sheets_credentials_path: str = ""

    # ── AI / OCR (not used in v0.6) ───────────────────────────────────────────
    openai_api_key:  str = ""
    nvidia_api_key:  str = ""

    # ── Legacy (kept for backward compatibility, unused in v0.6) ─────────────
    hubspot_api_key:               str = ""
    google_drive_credentials_path: str = ""

    class Config:
        env_file          = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

# ── Ensure all data directories exist at startup ──────────────────────────────
for _dir in (
    settings.submissions_dir,
    settings.processed_dir,
    settings.review_dir,
    settings.documents_dir,
    settings.document_jobs_dir,
    settings.logs_dir,
):
    _dir.mkdir(parents=True, exist_ok=True)
