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

    # ── JotForm form registry ─────────────────────────────────────────────────
    # Replacing a form is a configuration change, never a code change. See
    # app/core/forms.py, which also derives ids from config/services/*.yaml and
    # config/field_maps/*.yaml so a new service registers itself.
    main_form_id:         str = "250201745267957"   # primary intake form
    missing_docs_form_id: str = "251323124205946"   # documents follow-up form

    # enable_schema_visibility: use JotForm's own conditional logic (from the
    #   cached form schema) to decide which fields are visible, instead of the
    #   legacy hand-written engine. OFF by default so correcting the form
    #   registry does not silently change what customers are asked for.
    #   Measured effect of turning it ON, over 28 archived submissions:
    #   19 produce FEWER missing-information demands (fields JotForm hides for
    #   that flow were previously being requested), 9 are identical.
    enable_schema_visibility: bool = False

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

    # ── AI / OCR ─────────────────────────────────────────────────────────────
    # gemini_api_key  — Gemini Flash Vision document classifier (Phase 10C+).
    #   Get from: https://aistudio.google.com/app/apikey
    #   Set GEMINI_API_KEY in .env
    gemini_api_key:  str = ""
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
