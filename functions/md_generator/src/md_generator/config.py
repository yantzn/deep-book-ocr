from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# src/md_generator/config.py -> functions/md_generator/.env を参照
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """
    md_generator 用設定。

    重要:
    - 文字化け対策として、JSON読み込みは UTF-8 固定で行う（entrypoint側で実施）
    - ローカル/GCPでログ初期化を分岐（entrypoint側で実施）
    """

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        # pydantic warning回避（任意だが推奨）
        protected_namespaces=("settings_",),
    )

    # local | gcp
    app_env: str = Field(default="local", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Vertex AI
    gcp_project_id: str = Field(..., alias="GCP_PROJECT_ID")
    gcp_location: str = Field(default="us-central1", alias="GCP_LOCATION")

    # Output
    output_bucket: str = Field(..., alias="OUTPUT_BUCKET")

    # Gemini
    model_name: str = Field(default="gemini-1.5-pro", alias="MODEL_NAME")
    chunk_size: int = Field(default=10, alias="CHUNK_SIZE")

    @property
    def is_gcp(self) -> bool:
        return self.app_env.lower() == "gcp"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
