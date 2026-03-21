from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    # ローカル実行時は functions/md_generator/.env を読み込み、
    # GCP 実行時は環境変数（Cloud Functions の設定値）を優先して解決する。
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=("settings_",),
    )

    # 実行モード: local / gcp
    app_env: str = Field(default="local", alias="APP_ENV")

    # GCP リソース識別子（必須）
    gcp_project_id: str = Field(..., alias="GCP_PROJECT_ID")
    temp_bucket: str = Field(..., alias="TEMP_BUCKET")
    output_bucket: str = Field(..., alias="OUTPUT_BUCKET")
    firestore_jobs_collection: str = Field(...,
                                           alias="FIRESTORE_JOBS_COLLECTION")

    # Gemini 呼び出し設定
    gemini_model_name: str = Field(..., alias="GEMINI_MODEL_NAME")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_api_base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta",
        alias="GEMINI_API_BASE_URL",
    )

    # Markdown 生成時の整形挙動（Geminiを使うか/入力チャンク上限）
    enable_gemini_polish: bool = Field(
        default=True, alias="ENABLE_GEMINI_POLISH")
    gemini_max_input_chars: int = Field(
        default=120000, alias="GEMINI_MAX_INPUT_CHARS")

    # Gemini API の接続・読込タイムアウトと再試行制御
    gemini_connect_timeout_sec: float = Field(
        default=10.0, alias="GEMINI_CONNECT_TIMEOUT_SEC")
    gemini_read_timeout_sec: float = Field(
        default=90.0, alias="GEMINI_READ_TIMEOUT_SEC")
    gemini_request_max_attempts: int = Field(
        default=3, alias="GEMINI_REQUEST_MAX_ATTEMPTS")
    gemini_retry_base_sleep_sec: float = Field(
        default=1.0, alias="GEMINI_RETRY_BASE_SLEEP_SEC")

    # GCS からのJSON取得・出力書き込みに関するタイムアウト/再試行設定
    gcs_download_timeout_sec: float = Field(
        default=30.0, alias="GCS_DOWNLOAD_TIMEOUT_SEC")
    gcs_upload_timeout_sec: float = Field(
        default=30.0, alias="GCS_UPLOAD_TIMEOUT_SEC")
    gcs_exists_timeout_sec: float = Field(
        default=10.0, alias="GCS_EXISTS_TIMEOUT_SEC")
    gcs_download_max_attempts: int = Field(
        default=3, alias="GCS_DOWNLOAD_MAX_ATTEMPTS")
    gcs_download_base_sleep_sec: float = Field(
        default=1.0, alias="GCS_DOWNLOAD_BASE_SLEEP_SEC")

    # OCR JSON の並列ダウンロード数（大きすぎるとAPI制限にかかりやすい）
    gcs_parallel_download_workers: int = Field(
        default=8, alias="GCS_PARALLEL_DOWNLOAD_WORKERS")

    # Firestore I/O とログレベル設定
    firestore_timeout_sec: float = Field(
        default=20.0, alias="FIRESTORE_TIMEOUT_SEC")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @property
    def is_gcp(self) -> bool:
        # Cloud Functions 実行時に "gcp" を想定。
        return self.app_env.lower() == "gcp"

    @property
    def model_name(self) -> str:
        # 呼び出し側の互換性維持用エイリアス。
        return self.gemini_model_name

    @property
    def chunk_size(self) -> int:
        # markdown_logic 側が参照する入力チャンクサイズのエイリアス。
        return self.gemini_max_input_chars


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # 設定解決は重いため、プロセス内で1回だけ生成して再利用する。
    return Settings()
