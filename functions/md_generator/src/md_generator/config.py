from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# `functions/md_generator/.env` をローカル実行時の既定設定ファイルとして読む。
# Cloud Functions 実行時は環境変数が優先される。
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    # すべての設定は環境変数から読み込む。
    # 未定義の余剰キーは無視して、デプロイ環境差分に強くする。
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 実行環境の種別（local / gcp）。ログ初期化や外部接続方針の分岐に使う。
    app_env: str = Field(default="local", alias="APP_ENV")

    # GCP プロジェクト/リージョン。
    # Storage, Firestore, Vertex AI などのクライアント初期化で共通利用する。
    gcp_project_id: str = Field(
        default="deep-book-ocr", alias="GCP_PROJECT_ID")
    gcp_location: str = Field(default="us-central1", alias="GCP_LOCATION")

    # OCR 中間JSONの参照先と、最終Markdownの出力先。
    temp_bucket: str = Field(..., alias="TEMP_BUCKET")
    output_bucket: str = Field(..., alias="OUTPUT_BUCKET")

    # ジョブ状態（RUNNING/SUCCEEDED/FAILED）を保存する Firestore コレクション名。
    firestore_jobs_collection: str = Field(
        default="ocr_jobs", alias="FIRESTORE_JOBS_COLLECTION")

    # Markdown整形に使う Gemini 設定。
    # 大きすぎる入力で失敗しないよう、送信文字数上限を持つ。
    gemini_model_name: str = Field(
        default="gemini-1.5-pro", alias="GEMINI_MODEL_NAME")
    enable_gemini_polish: bool = Field(
        default=True, alias="ENABLE_GEMINI_POLISH")
    gemini_max_input_chars: int = Field(
        default=120000, alias="GEMINI_MAX_INPUT_CHARS")

    # アプリケーションログレベル。
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @property
    def is_gcp(self) -> bool:
        # Cloud Functions 上での実行かどうかの判定。
        return self.app_env.lower() == "gcp"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # 設定オブジェクトをプロセス内で再利用して、毎回の再パースを避ける。
    return Settings()
