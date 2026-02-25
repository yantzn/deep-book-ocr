"""
責務:
- GCS finalize イベントから入力PDFを特定
- PDF以外を除外
- Document AI バッチOCRを起動（submit だけ行い、完了待ちはしない）
- Cloud Logging（GCP時）を初期化
"""

from __future__ import annotations

import logging
import os
from typing import Any

import functions_framework
from cloudevents.http import CloudEvent

from ocr_trigger.config import get_settings
from ocr_trigger.gcp_services import build_services

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    """
    ローカル:
      - 標準loggingのみ
    GCP:
      - google-cloud-logging が入っていれば Cloud Logging に統合
    """
    settings = get_settings()

    # まず標準logging
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(level=level)

    if not settings.is_gcp:
        logger.info("Logging: local mode (standard logging)")
        return

    # GCP のときだけ Cloud Logging
    try:
        from google.cloud import logging as cloud_logging  # type: ignore

        cloud_logging.Client().setup_logging(log_level=level)
        logger.info("Logging: Cloud Logging enabled")
    except Exception as e:  # noqa: BLE001
        # Cloud Logging 初期化失敗でも処理は継続
        logger.warning(
            "Cloud Logging setup failed (fallback to std logging): %s", e)


def _is_pdf_object(name: str, content_type: str | None) -> bool:
    # contentType が来る場合もあるが、来ないこともある
    if name.lower().endswith(".pdf"):
        return True
    if content_type and content_type.lower() == "application/pdf":
        return True
    return False


@functions_framework.cloud_event
def start_ocr(event: CloudEvent) -> dict[str, Any]:
    _setup_logging()

    settings = get_settings()
    services = build_services(settings)

    data = event.data or {}
    bucket = (data.get("bucket") or "").strip()
    name = (data.get("name") or "").strip()
    content_type = data.get("contentType")

    logger.info(
        "Received GCS finalize event. bucket=%s name=%s contentType=%s",
        bucket,
        name,
        content_type,
    )

    # 必須チェック
    if not bucket or not name:
        logger.warning("Missing bucket/name in event: %s", data)
        return {"status": "ignored", "reason": "missing bucket/name"}

    # PDF以外は除外
    if not _is_pdf_object(name, content_type):
        logger.info("Ignored non-PDF object: %s (contentType=%s)",
                    name, content_type)
        return {"status": "ignored", "reason": "not pdf", "bucket": bucket, "name": name}

    # Document AI submit
    try:
        op_name, output_prefix = services.docai_service.start_ocr_batch_job(
            bucket, name)
        return {
            "status": "submitted",
            "operation": op_name,
            "output_prefix": output_prefix,
        }
    except Exception as e:
        logger.exception("Unexpected error while submitting OCR batch: %s", e)
        return {
            "status": "error",
            "error": str(e),
        }
