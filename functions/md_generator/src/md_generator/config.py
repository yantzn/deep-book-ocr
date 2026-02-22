from __future__ import annotations

"""md_generator の設定モジュール。

環境変数を一元管理し、関数実行中はキャッシュ済み Settings を使い回す。
"""

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    md_generator 用の設定。
    env / .env から設定値を読み込む。

    主な方針:
    - APP_ENV でログ出力モード（local / gcp）を切り替える
    - Vertex AI（Gemini）はローカルでも常に実GCP（ADC）を利用する
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 実行環境: local | gcp
    app_env: str = Field(default="local", alias="APP_ENV")

    # Vertex AI 用のGCP設定
    gcp_project_id: str = Field(..., alias="GCP_PROJECT_ID")
    gcp_location: str = Field(default="us-central1", alias="GCP_LOCATION")

    # 実GCSモードでの出力バケット
    output_bucket: str = Field(..., alias="OUTPUT_BUCKET")

    # Gemini設定
    model_name: str = Field(default="gemini-1.5-pro", alias="MODEL_NAME")
    chunk_size: int = Field(default=10, alias="CHUNK_SIZE")

    @property
    def is_gcp(self) -> bool:
        """デプロイ先のGCP環境で実行中なら True を返す。"""
        return self.app_env.lower() == "gcp"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """設定インスタンスをキャッシュして返す。"""
    return Settings()
