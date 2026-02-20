from __future__ import annotations

"""ocr_trigger の設定モジュール。

環境変数を型付きで受け取り、URI整形ルールを統一する。
"""

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    ocr_trigger 関数の設定。
    環境変数 / .env から設定値を読み込む。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 実行環境: local | gcp
    app_env: str = Field(default="local", alias="APP_ENV")

    gcp_project_id: str = Field(
        default="deep-book-ocr", alias="GCP_PROJECT_ID")
    processor_location: str = Field(default="us", alias="PROCESSOR_LOCATION")
    processor_id: str = Field(..., alias="PROCESSOR_ID")

    # 例: "gs://deep-book-ocr-temp" と "deep-book-ocr-temp" の両方を許容
    temp_bucket: str = Field(..., alias="TEMP_BUCKET")

    @property
    def is_gcp(self) -> bool:
        """デプロイ先のGCP環境で実行中なら True を返す。"""
        return self.app_env.lower() == "gcp"

    def temp_bucket_uri(self) -> str:
        """TEMP_BUCKET を 'gs://<bucket>/' 形式へ正規化する。"""
        t = self.temp_bucket.strip()
        if t.startswith("gs://"):
            return t.rstrip("/") + "/"
        return f"gs://{t.rstrip('/')}/"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    パフォーマンスのため設定インスタンスをキャッシュして返す。
    """
    return Settings()
