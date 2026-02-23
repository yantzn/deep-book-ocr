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
        # pydantic warning回避（任意だが推奨）
        protected_namespaces=("settings_",),
    )

    # local | gcp
    app_env: str = Field(default="local", alias="APP_ENV")

    gcp_project_id: str = Field(..., alias="GCP_PROJECT_ID")
    gcp_location: str = Field(default="us-central1", alias="GCP_LOCATION")

    output_bucket: str = Field(..., alias="OUTPUT_BUCKET")

    model_name: str = Field(default="gemini-1.5-pro", alias="MODEL_NAME")
    chunk_size: int = Field(default=10, alias="CHUNK_SIZE")

    @property
    def is_gcp(self) -> bool:
        return self.app_env.lower() == "gcp"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
