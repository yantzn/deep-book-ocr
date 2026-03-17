from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ローカル実行時に参照する既定の .env ファイル。
# Cloud Functions 本番では環境変数が優先される。
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """
    ocr_trigger の設定。
    - Cloud Functions / Cloud Run では環境変数で注入
    - ローカルでは functions/ocr_trigger/.env から読み込む
    """

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        # デプロイ環境で追加される未使用キーがあっても失敗しないようにする。
        extra="ignore",
    )

    # 実行環境の識別子。ローカル実行か GCP 本番かを切り替える。
    # local | gcp
    app_env: str = Field(default="local", alias="APP_ENV")

    # プロジェクト/リージョンなど GCP 基本設定。
    # GCP project
    gcp_project_id: str = Field(..., alias="GCP_PROJECT_ID")
    gcp_location: str = Field(..., alias="GCP_LOCATION")

    # 利用する Document AI プロセッサ設定。
    # Document AI processor
    processor_location: str = Field(..., alias="PROCESSOR_LOCATION")
    # processor id or full resource
    processor_id: str = Field(..., alias="PROCESSOR_ID")

    # OCR 一時出力先とジョブ管理先。
    # Document AI output bucket (gs://... or bucket name)
    temp_bucket: str = Field(..., alias="TEMP_BUCKET")
    firestore_jobs_collection: str = Field(...,
                                           alias="FIRESTORE_JOBS_COLLECTION")

    # DocAI 監視 Workflow 実行に必要な設定。
    docai_monitor_workflow_name: str = Field(
        ...,
        alias="DOCAI_MONITOR_WORKFLOW_NAME",
    )
    workflow_region: str = Field(..., alias="WORKFLOW_REGION")

    # ログレベルと DocAI submit API 呼び出しのタイムアウト秒。
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    docai_submit_timeout_sec: int = Field(
        default=120,
        alias="DOCAI_SUBMIT_TIMEOUT_SEC",
    )
    firestore_timeout_sec: float = Field(
        default=20.0,
        alias="FIRESTORE_TIMEOUT_SEC",
    )
    workflow_execute_timeout_sec: float = Field(
        default=20.0,
        alias="WORKFLOW_EXECUTE_TIMEOUT_SEC",
    )

    @property
    def is_gcp(self) -> bool:
        """実行環境が GCP 本番かどうかを返す。"""
        return self.app_env.lower() == "gcp"

    def processor_id_normalized(self) -> str:
        """
        PROCESSOR_ID が
        - processor id 単体
        - projects/.../locations/.../processors/... の完全修飾名
        のどちらでも扱えるようにする。
        """
        value = self.processor_id.strip()
        if "/processors/" in value:
            # 完全修飾名の場合は末尾の processor id のみ抽出する。
            return value.split("/processors/")[-1].strip("/")
        return value

    def temp_bucket_uri(self) -> str:
        """
        TEMP_BUCKET を gs://bucket/ 形式へ正規化する。
        """
        value = self.temp_bucket.strip()
        if value.startswith("gs://"):
            # 既に gs:// 形式なら末尾スラッシュだけ整える。
            return value.rstrip("/") + "/"
        # バケット名のみ指定された場合は gs:// を補完する。
        return f"gs://{value.rstrip('/')}/"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Settings を 1 プロセス内でキャッシュして再利用する。"""
    return Settings()
