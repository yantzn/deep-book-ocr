from __future__ import annotations

"""
ocr_trigger の設定モジュール。

方針:
- 環境変数を型付きで受け取り、URI整形ルールを統一する
- .env はカレントディレクトリに依存させず、関数ルートの .env を参照する
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# src/ocr_trigger/config.py -> functions/ocr_trigger/.env
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """
    ocr_trigger 関数の設定。
    環境変数 / .env から設定値を読み込む。
    """

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 実行環境の種別。Cloud Logging 初期化の分岐などで利用する（local | gcp）。
    app_env: str = Field(default="local", alias="APP_ENV")
    # アプリ全体のログ出力レベル（DEBUG/INFO/WARNING/ERROR を想定）。
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Document AI / GCP API を呼び出す対象プロジェクトID。
    gcp_project_id: str = Field(
        default="deep-book-ocr", alias="GCP_PROJECT_ID")
    # Document AI Processor のリージョン（例: us / eu）
    processor_location: str = Field(default="us", alias="PROCESSOR_LOCATION")
    # Processor の短縮ID（Terraform 出力値を想定）。
    processor_id: str = Field(..., alias="PROCESSOR_ID")

    # OCR JSON を出力する一時バケット（gs:// 付き/なしの両方を許容）。
    temp_bucket: str = Field(..., alias="TEMP_BUCKET")

    @property
    def is_gcp(self) -> bool:
        """デプロイ先のGCP環境で実行中なら True。"""
        return self.app_env.lower() == "gcp"

    def temp_bucket_uri(self) -> str:
        """TEMP_BUCKET を 'gs://.../' 形式へ正規化する。"""
        # 入力揺れ（gs:// 有無、末尾スラッシュ有無）を吸収する。
        t = self.temp_bucket.strip()
        if t.startswith("gs://"):
            return t.rstrip("/") + "/"
        return f"gs://{t.rstrip('/')}/"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """設定インスタンスをキャッシュして返す。"""
    return Settings()
