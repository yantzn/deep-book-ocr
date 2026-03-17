from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=("settings_",),
    )

    app_env: str = Field(default="local", alias="APP_ENV")
    gcp_project_id: str = Field(..., alias="GCP_PROJECT_ID")

    temp_bucket: str = Field(..., alias="TEMP_BUCKET")
    output_bucket: str = Field(..., alias="OUTPUT_BUCKET")
    firestore_jobs_collection: str = Field(...,
                                           alias="FIRESTORE_JOBS_COLLECTION")

    gemini_model_name: str = Field(
        ...,
        alias="GEMINI_MODEL_NAME",
    )
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_api_base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta",
        alias="GEMINI_API_BASE_URL",
    )
    enable_gemini_polish: bool = Field(
        default=True,
        alias="ENABLE_GEMINI_POLISH",
    )
    gemini_max_input_chars: int = Field(
        default=120000,
        alias="GEMINI_MAX_INPUT_CHARS",
    )
    gemini_timeout_sec: float = Field(
        default=60.0,
        alias="GEMINI_TIMEOUT_SEC",
    )
    gemini_request_max_attempts: int = Field(
        default=2,
        alias="GEMINI_REQUEST_MAX_ATTEMPTS",
    )
    gemini_retry_base_sleep_sec: float = Field(
        default=1.0,
        alias="GEMINI_RETRY_BASE_SLEEP_SEC",
    )

    gcs_download_timeout_sec: float = Field(
        default=30.0,
        alias="GCS_DOWNLOAD_TIMEOUT_SEC",
    )
    gcs_upload_timeout_sec: float = Field(
        default=30.0,
        alias="GCS_UPLOAD_TIMEOUT_SEC",
    )
    gcs_exists_timeout_sec: float = Field(
        default=10.0,
        alias="GCS_EXISTS_TIMEOUT_SEC",
    )
    gcs_download_max_attempts: int = Field(
        default=3,
        alias="GCS_DOWNLOAD_MAX_ATTEMPTS",
    )
    gcs_download_base_sleep_sec: float = Field(
        default=1.0,
        alias="GCS_DOWNLOAD_BASE_SLEEP_SEC",
    )

    firestore_timeout_sec: float = Field(
        default=20.0,
        alias="FIRESTORE_TIMEOUT_SEC",
    )

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @property
    def is_gcp(self) -> bool:
        return self.app_env.lower() == "gcp"

    @property
    def model_name(self) -> str:
        return self.gemini_model_name

    @property
    def chunk_size(self) -> int:
        return self.gemini_max_input_chars


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
