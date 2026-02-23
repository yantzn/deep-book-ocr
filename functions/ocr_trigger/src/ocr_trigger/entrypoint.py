from __future__ import annotations

"""
Cloud Functions (Gen2) / Functions Framework エントリポイント。

責務:
- GCS finalize イベントから入力PDFを特定
- PDF以外を除外
- Document AI バッチOCRを起動
"""

import logging
from typing import Any

import functions_framework
from cloudevents.http import CloudEvent

from . import config, gcp_services

logger = logging.getLogger(__name__)


def setup_logging(settings: config.Settings) -> None:
    """
    ログ初期化。
    - ローカル: 標準logging
    - GCP: Cloud Logging を有効化（ただし import は遅延してローカルで壊れないようにする）
    """
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )

    if settings.is_gcp:
        try:
            import google.cloud.logging as cloud_logging  # noqa: WPS433

            cloud_logging.Client().setup_logging()
            logger.info("Cloud Logging initialized")
        except Exception:
            logger.exception("Failed to initialize Cloud Logging")


# モジュールロード時に一度だけ初期化（Functionsのベストプラクティス）
settings = config.get_settings()
setup_logging(settings)
services = gcp_services.build_services(settings)


@functions_framework.cloud_event
def start_ocr(cloud_event: CloudEvent) -> tuple[str, int]:
    """
    OCR処理を起動する Cloud Function のエントリポイント。

    トリガ: GCS finalize イベント（PDFアップロード）
    """
    try:
        data: dict[str, Any] = cloud_event.data or {}
        bucket = data["bucket"]
        name = data["name"]

        if not name.lower().endswith(".pdf"):
            logger.info("PDF以外のためスキップします: %s", name)
            return ("PDF以外のためスキップしました。", 200)

        op_name = services.docai_service.start_ocr_batch_job(bucket, name)
        logger.info("OCR処理を開始しました: operation=%s", op_name)
        return ("OCR処理を開始しました。", 200)

    except KeyError as e:
        logger.error("CloudEventデータが不正です。欠損キー: %s", e)
        return (f"不正なリクエスト: CloudEventのデータが不足しています: {e}", 400)

    except Exception:
        logger.exception("想定外のエラーが発生しました")
        return ("サーバー内部エラー", 500)
