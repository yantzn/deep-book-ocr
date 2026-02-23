from __future__ import annotations

"""
Cloud Functions (Gen2) / Functions Framework エントリポイント。

責務:
- GCS finalize イベントから入力PDFを特定
- PDF以外を除外
- Document AI バッチOCRを起動
"""

import logging
import time
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
    level_name = settings.log_level.upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
    else:
        root.setLevel(level)

    logger.info("Logging configured: level=%s app_env=%s",
                level_name, settings.app_env)

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

    処理の流れ:
    1) CloudEvent から bucket/object を取得
    2) PDF 以外を除外
    3) Document AI バッチ処理を起動
    4) operation 名をログへ出力
    """
    try:
        # --- 1) イベント情報の取り出し ---
        event_id = cloud_event.get("id")
        event_type = cloud_event.get("type")
        data: dict[str, Any] = cloud_event.data or {}
        bucket = data["bucket"]
        name = data["name"]
        generation = data.get("generation")

        logger.info(
            "OCR trigger received: event_id=%s type=%s bucket=%s name=%s generation=%s",
            event_id,
            event_type,
            bucket,
            name,
            generation,
        )

        # --- 2) PDF 以外を除外 ---
        if not name.lower().endswith(".pdf"):
            logger.info(
                "Skipped non-PDF object: event_id=%s bucket=%s name=%s",
                event_id,
                bucket,
                name,
            )
            return ("PDF以外のためスキップしました。", 200)

        # --- 3) Document AI バッチ起動 ---
        started_at = time.perf_counter()
        op_name = services.docai_service.start_ocr_batch_job(bucket, name)
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        output_prefix = f"{settings.temp_bucket_uri()}{name}_json/"

        # --- 4) 起動結果をログ出力 ---
        logger.info(
            "OCR batch submitted: event_id=%s operation=%s output_prefix=%s elapsed_ms=%d",
            event_id,
            op_name,
            output_prefix,
            elapsed_ms,
        )
        return ("OCR処理を開始しました。", 200)

    except KeyError as e:
        logger.error(
            "Invalid CloudEvent payload: missing_key=%s payload_keys=%s",
            e,
            sorted((cloud_event.data or {}).keys()),
        )
        return (f"不正なリクエスト: CloudEventのデータが不足しています: {e}", 400)

    except Exception:
        logger.exception("Unexpected error while submitting OCR batch")
        return ("サーバー内部エラー", 500)
