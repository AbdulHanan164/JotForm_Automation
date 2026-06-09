from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    app_name: str    = "JotForm Webhook Receiver"
    app_version: str = "0.3.0"
    debug: bool      = False
    log_level: str   = "INFO"

    submissions_dir: Path = Path("data/submissions")   # raw full payloads
    processed_dir:   Path = Path("data/processed")     # clean summaries
    logs_dir:        Path = Path("logs")

    # Future integrations — fill in .env when ready
    hubspot_api_key:               str = ""
    openai_api_key:                str = ""
    nvidia_api_key:                str = ""
    google_drive_credentials_path: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

# Ensure all directories exist at startup
for _dir in (settings.submissions_dir, settings.processed_dir, settings.logs_dir):
    _dir.mkdir(parents=True, exist_ok=True)
