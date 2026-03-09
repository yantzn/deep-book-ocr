"""
責務:
- GCS finalize イベントから入力PDFを特定
- PDF以外を除外
- Document AI バッチOCRを起動（submit だけ行い、完了待ちはしない）
- Cloud Logging（GCP時）を初期化
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import sys
import time
import uuid
from typing import Any

import functions_framework
from cloudevents.http import CloudEvent

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

config_module = importlib.import_module("ocr_trigger.config")
gcp_services_module = importlib.import_module("ocr_trigger.gcp_services")

get_settings = config_module.get_settings
build_services = gcp_services_module.build_services

logger = logging.getLogger(__name__)

# cold start 判定
_COLD_START = True


def _setup_logging() -> None:
    """
    ローカル:
      - 標準loggingのみ
    GCP:
      - google-cloud-logging が入っていれば Cloud Logging に統合
    """
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(level=level)

    if not settings.is_gcp:
        logger.info("Logging initialized: local mode level=%s",
                    settings.log_level)
        return

    try:
        from google.cloud import logging as cloud_logging  # type: ignore

        cloud_logging.Client().setup_logging(log_level=level)
        logger.info(
            "Logging initialized: Cloud Logging enabled level=%s", settings.log_level)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "Cloud Logging setup failed; fallback to std logging: %s", e)


def _is_pdf_object(name: str, content_type: str | None) -> bool:
    if name.lower().endswith(".pdf"):
        return True
    if content_type and content_type.lower() == "application/pdf":
        return True
    return False


def _safe_event_context(event: CloudEvent) -> dict[str, Any]:
    data = event.data or {}
    return {
        "id": getattr(event, "get", lambda *_: None)("id"),
        "source": getattr(event, "get", lambda *_: None)("source"),
        "type": getattr(event, "get", lambda *_: None)("type"),
        "subject": getattr(event, "get", lambda *_: None)("subject"),
        "bucket": data.get("bucket"),
        "name": data.get("name"),
        "contentType": data.get("contentType"),
        "metageneration": data.get("metageneration"),
        "generation": data.get("generation"),
        "timeCreated": data.get("timeCreated"),
        "updated": data.get("updated"),
    }


@functions_framework.cloud_event
def start_ocr(event: CloudEvent) -> tuple[str, int]:
    global _COLD_START

    started_at = time.perf_counter()
    request_id = str(uuid.uuid4())[:8]
    cold_start = _COLD_START
    _COLD_START = False

    _setup_logging()

    # ロギング初期化後に設定とサービスを構築する
    settings = get_settings()
    services = build_services(settings)
    docai_service = services.docai_service
    gcs_service = services.gcs_service

    logger.info(
        "[%s] start_ocr entered cold_start=%s pid=%s service=%s revision=%s",
        request_id,
        cold_start,
        os.getpid(),
        os.getenv("K_SERVICE", ""),
        os.getenv("K_REVISION", ""),
    )

    try:
        data = event.data or {}
        bucket = (data.get("bucket") or "").strip()
        name = (data.get("name") or "").strip()
        content_type = data.get("contentType")

        logger.info(
            "[%s] event_summary=%s",
            request_id,
            json.dumps(_safe_event_context(event),
                       ensure_ascii=False, default=str),
        )

        logger.info(
            "[%s] settings_summary project=%s processor_location=%s processor_id=%s "
            "temp_bucket=%s submit_timeout_sec=%s is_gcp=%s",
            request_id,
            settings.gcp_project_id,
            settings.processor_location,
            settings.processor_id,
            settings.temp_bucket,
            settings.docai_submit_timeout_sec,
            settings.is_gcp,
        )

        if not bucket or not name:
            logger.warning(
                "[%s] missing bucket/name in event payload=%s", request_id, data)
            return ("不正なリクエスト: CloudEventのデータが不足しています", 400)

        if not _is_pdf_object(name, content_type):
            logger.info(
                "[%s] ignored non-pdf object bucket=%s name=%s contentType=%s",
                request_id,
                bucket,
                name,
                content_type,
            )
            return ("PDF以外のためスキップしました。", 200)

        probe_started = time.perf_counter()
        blob_meta = gcs_service.get_blob_metadata(bucket, name)
        logger.info(
            "[%s] gcs_probe result=%s elapsed_ms=%s",
            request_id,
            json.dumps(blob_meta, ensure_ascii=False, default=str),
            int((time.perf_counter() - probe_started) * 1000),
        )

        if not blob_meta.get("exists", False):
            logger.warning(
                "[%s] input blob not found bucket=%s name=%s", request_id, bucket, name)
            return ("入力PDFが見つかりませんでした", 404)

        submit_started = time.perf_counter()
        logger.info("[%s] about_to_submit_docai input=gs://%s/%s",
                    request_id, bucket, name)

        operation_name, output_uri = docai_service.start_ocr_batch_job(
            bucket,
            name,
            request_id=request_id,
        )

        logger.info(
            "[%s] docai_submit_succeeded operation=%s output_uri=%s elapsed_ms=%s",
            request_id,
            operation_name,
            output_uri,
            int((time.perf_counter() - submit_started) * 1000),
        )
        return ("OCR処理を開始しました。", 200)

    except TimeoutError as e:
        logger.exception(
            "[%s] document_ai_submit_timed_out: %s", request_id, e)
        return ("Document AI へのリクエストがタイムアウトしました", 504)

    except Exception as e:
        logger.exception(
            "[%s] unexpected_error_while_submitting_ocr_batch: %s", request_id, e)
        return ("サーバー内部エラー", 500)

    finally:
        logger.info(
            "[%s] start_ocr finished total_elapsed_ms=%s",
            request_id,
            int((time.perf_counter() - started_at) * 1000),
        )
