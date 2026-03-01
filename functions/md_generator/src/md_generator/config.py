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

    # 実行環境の種別。Cloud Logging 初期化の分岐などで利用する（local | gcp）。
    app_env: str = Field(default="local", alias="APP_ENV")
    # アプリ全体のログ出力レベル。
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Vertex AI を呼び出す対象プロジェクトID。
    gcp_project_id: str = Field(..., alias="GCP_PROJECT_ID")
    # Vertex AI のリージョン（例: us-central1）。
    gcp_location: str = Field(default="us-central1", alias="GCP_LOCATION")

    # 生成した Markdown を保存する出力バケット名。
    output_bucket: str = Field(..., alias="OUTPUT_BUCKET")

    # 変換に使用する Gemini モデル名。
    model_name: str = Field(default="gemini-2.5-flash", alias="MODEL_NAME")
    # 1回の推論に渡すページ数（大きすぎると遅延/失敗率が上がる）。
    chunk_size: int = Field(default=10, alias="CHUNK_SIZE")

    @property
    def is_gcp(self) -> bool:
        # デプロイ先の GCP 環境で実行中なら True。
        return self.app_env.lower() == "gcp"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # 設定読み込みをプロセス内で1回に抑え、毎回の環境変数パースを避ける。
    return Settings()
