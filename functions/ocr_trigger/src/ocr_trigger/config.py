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
    )

    # local | gcp
    app_env: str = Field(default="local", alias="APP_ENV")

    gcp_project_id: str = Field(
        default="deep-book-ocr", alias="GCP_PROJECT_ID")
    processor_location: str = Field(default="us", alias="PROCESSOR_LOCATION")

    # processor id でもフルリソース名でも受ける
    processor_id: str = Field(..., alias="PROCESSOR_ID")

    # gs:// あり/なし どちらも許容
    temp_bucket: str = Field(..., alias="TEMP_BUCKET")

    @property
    def is_gcp(self) -> bool:
        return self.app_env.lower() == "gcp"

    def processor_id_normalized(self) -> str:
        """
        Document AI の processor_id を正規化。
        - projects/.../locations/.../processors/<ID> を渡されたら <ID> にする
        """
        v = self.processor_id.strip()
        if "/processors/" in v:
            return v.split("/processors/")[-1].strip("/")
        return v

    def temp_bucket_uri(self) -> str:
        """
        TEMP_BUCKET を gs://<bucket>/ 形式に揃える（末尾 / 付与）。
        """
        t = self.temp_bucket.strip()
        if t.startswith("gs://"):
            return t.rstrip("/") + "/"
        return f"gs://{t.rstrip('/')}/"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
