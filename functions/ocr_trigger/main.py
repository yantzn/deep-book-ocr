from __future__ import annotations
from ocr_trigger import config, gcp_services

"""
Cloud Functions (Gen2) / Functions Framework エントリポイント。

このファイルを実処理本体として使用する。
（python310 デプロイ要件: source 直下に main.py が必要）
"""

import logging
import os
import sys
import time
from typing import Any

import functions_framework
from cloudevents.http import CloudEvent

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))


logger = logging.getLogger(__name__)


def setup_logging(settings: config.Settings) -> None:
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
            import google.cloud.logging as cloud_logging

            cloud_logging.Client().setup_logging()
            logger.info("Cloud Logging initialized")
        except Exception:
            logger.exception("Failed to initialize Cloud Logging")


settings = config.get_settings()
setup_logging(settings)
services = gcp_services.build_services(settings)
docai_service = services.docai_service


@functions_framework.cloud_event
def start_ocr(cloud_event: CloudEvent) -> tuple[str, int]:
    try:
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

        if not name.lower().endswith(".pdf"):
            logger.info(
                "Skipped non-PDF object: event_id=%s bucket=%s name=%s",
                event_id,
                bucket,
                name,
            )
            return ("PDF以外のためスキップしました。", 200)

        started_at = time.perf_counter()
        op_name = docai_service.start_ocr_batch_job(bucket, name)
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        output_prefix = f"{settings.temp_bucket_uri()}{name}_json/"

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


__all__ = ["start_ocr"]
