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

    # local | gcp
    app_env: str = Field(default="local", alias="APP_ENV")

    # GCP project
    gcp_project_id: str = Field(
        default="deep-book-ocr", alias="GCP_PROJECT_ID")

    # Document AI processor
    processor_location: str = Field(default="us", alias="PROCESSOR_LOCATION")
    # processor id or full resource
    processor_id: str = Field(..., alias="PROCESSOR_ID")

    # Document AI output bucket (gs://... or bucket name)
    temp_bucket: str = Field(..., alias="TEMP_BUCKET")

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # (将来拡張用) submit に時間がかかるケースに備えた設定値。
    # 今の実装は operation を待たず即返すが、ログや検証で利用する。
    docai_submit_timeout_sec: int = Field(
        default=120, alias="DOCAI_SUBMIT_TIMEOUT_SEC")

    @property
    def is_gcp(self) -> bool:
        # ログ初期化や実行モード分岐で使う環境判定フラグ。
        return self.app_env.lower() == "gcp"

    def processor_id_normalized(self) -> str:
        """
        Document AI の processor_id を正規化。
        - projects/.../locations/.../processors/... を渡されたら ... の部分だけにする
        """
        # 入力揺れ（idのみ / 完全リソース名）を吸収して後段処理を単純化する。
        v = self.processor_id.strip()
        if "/processors/" in v:
            return v.split("/processors/")[-1].strip("/")
        return v

    def temp_bucket_uri(self) -> str:
        """TEMP_BUCKET を gs://<bucket>/ 形式に揃える（末尾 / 付与）。"""
        # bucket 名のみ渡された場合も URI へ正規化し、呼び出し側の分岐をなくす。
        t = self.temp_bucket.strip()
        if t.startswith("gs://"):
            return t.rstrip("/") + "/"
        return f"gs://{t.rstrip('/')}/"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # 設定の再パースを避けるため、プロセス内で1回だけ生成して再利用する。
    return Settings()
