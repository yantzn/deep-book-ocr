from __future__ import annotations

import base64
import hashlib
import importlib
import json
import logging
import os
import sys
import time
import traceback
import uuid
from functools import lru_cache
from typing import Any

import functions_framework
from cloudevents.http import CloudEvent

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

config_module = importlib.import_module("md_generator.config")
gcp_services_module = importlib.import_module("md_generator.gcp_services")
job_store_module = importlib.import_module("md_generator.job_store")
markdown_logic_module = importlib.import_module("md_generator.markdown_logic")
observability_module = importlib.import_module("md_generator.observability")

get_settings = config_module.get_settings
build_services = gcp_services_module.build_services
FirestoreJobStore = job_store_module.FirestoreJobStore
build_markdown_from_documentai_jsons = markdown_logic_module.build_markdown_from_documentai_jsons
log_pipeline_event = observability_module.log_pipeline_event

logger = logging.getLogger(__name__)


def _short_text(value: Any, *, max_len: int = 500) -> str:
    text = str(value)
    if len(text) <= max_len:
        return text
    return f"{text[:max_len]}..."


def _elapsed_ms(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)


def _log_event(
    *,
    level: int,
    stage: str,
    request_id: str,
    trace_id: str,
    job_id: str = "",
    **fields: Any,
) -> None:
    payload: dict[str, Any] = {
        "request_id": request_id,
        "trace_id": trace_id,
    }
    if job_id:
        payload["job_id"] = job_id
    payload.update(fields)
    log_pipeline_event(
        logger,
        level=level,
        event="generate_markdown",
        stage=stage,
        **payload,
    )


@lru_cache(maxsize=1)
def _get_runtime_dependencies():
    # 設定・外部サービス・ストアを1回だけ構築し、同一インスタンス内で再利用する。
    settings = get_settings()
    services = build_services(settings)
    job_store = FirestoreJobStore(settings)
    return settings, services.storage_service, services.llm_service, job_store


@lru_cache(maxsize=1)
def _setup_logging_once() -> None:
    """実行環境に応じてロギングを初期化する。"""
    # 設定値からログレベルを決定し、ローカル/本番で初期化方法を切り替える。
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(level=level)

    if not settings.is_gcp:
        logger.info("Logging initialized: local mode level=%s",
                    settings.log_level)
        return

    try:
        # GCP 実行時は Cloud Logging へハンドラを接続する。
        from google.cloud import logging as cloud_logging  # type: ignore

        cloud_logging.Client().setup_logging(log_level=level)
        logger.info(
            "Logging initialized: Cloud Logging enabled level=%s", settings.log_level)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "Cloud Logging setup failed; fallback to std logging: %s", e)


def _decode_pubsub_message(event: CloudEvent) -> tuple[dict[str, Any], dict[str, str]]:
    # Pub/Sub CloudEvent から message.data(JSON) と attributes を取り出す。
    data = event.data or {}
    message = data.get("message") or {}
    attributes = message.get("attributes") or {}
    raw_data = message.get("data")

    if not raw_data:
        return {}, attributes

    try:
        decoded = base64.b64decode(raw_data).decode("utf-8")
        payload = json.loads(decoded)
        if not isinstance(payload, dict):
            raise ValueError("Pub/Sub message payload must be a JSON object")
        return payload, attributes
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Invalid Pub/Sub message payload: {e}") from e


@functions_framework.cloud_event
def generate_markdown(event: CloudEvent) -> None:
    """
    Pub/Sub メッセージを受け取り、OCR結果JSONを集約して Markdown を生成する。
    """

    # 監視・トラブルシュート用の実行コンテキストを初期化する。
    started_at = time.perf_counter()
    request_id = str(uuid.uuid4())[:8]
    job_id = ""
    trace_id = ""
    final_status = "UNKNOWN"
    fallback_used = False
    used_gemini: bool | None = None
    error_kind = ""
    error_message = ""
    stacktrace_hash = ""

    # ログ設定と依存サービスは毎回再作成せず、初回のみ初期化する。
    _setup_logging_once()
    settings, storage_service, llm_service, job_store = _get_runtime_dependencies()

    _log_event(
        level=logging.INFO,
        stage="event_received",
        request_id=request_id,
        trace_id=trace_id,
    )

    try:
        # 1) Pub/Subイベントを検証し、処理対象ジョブIDを決定する。
        payload, attributes = _decode_pubsub_message(event)
        trace_id = str(attributes.get("trace_id", "")).strip()
        job_id = str(payload.get("job_id") or "").strip()

        _log_event(
            level=logging.INFO,
            stage="event_validated",
            request_id=request_id,
            trace_id=trace_id,
            job_id=job_id,
        )

        if not job_id:
            final_status = "EVENT_REJECTED"
            _log_event(
                level=logging.WARNING,
                stage="event_rejected",
                request_id=request_id,
                trace_id=trace_id,
                reason="missing_job_id",
            )
            return

        # 2) Firestoreからジョブ情報を取得し、入力/出力に必要な識別子を読み出す。
        job = job_store.get_job(job_id)
        temp_output_prefix = str(job["temp_output_prefix"])
        input_name = str(job["input_name"])
        input_generation = str(job["input_generation"])

        _log_event(
            level=logging.INFO,
            stage="job_loaded",
            request_id=request_id,
            trace_id=trace_id,
            job_id=job_id,
            temp_output_prefix=temp_output_prefix,
        )

        job_store.update_fields(
            job_id,
            {
                "status": "MD_RUNNING",
                "md_started_at": job_store.now_iso(),
                "updated_at": job_store.now_iso(),
            },
        )

        _log_event(
            level=logging.INFO,
            stage="job_status_updated",
            request_id=request_id,
            trace_id=trace_id,
            job_id=job_id,
            status="MD_RUNNING",
        )

        # 3) Document AI が出力した JSON 一覧を取得し、本文をダウンロードする。
        list_started = time.perf_counter()
        object_names = storage_service.list_object_names_from_gs_uri(
            temp_output_prefix)

        _log_event(
            level=logging.INFO,
            stage="ocr_json_listed",
            request_id=request_id,
            trace_id=trace_id,
            job_id=job_id,
            object_count=len(object_names),
            elapsed_ms=_elapsed_ms(list_started),
            prefix=temp_output_prefix,
        )

        if not object_names:
            raise RuntimeError(
                f"No OCR JSON objects found under prefix: {temp_output_prefix}")

        download_started = time.perf_counter()
        json_docs = storage_service.download_json_documents_from_gs_uri_prefix(
            temp_output_prefix)

        _log_event(
            level=logging.INFO,
            stage="ocr_json_downloaded",
            request_id=request_id,
            trace_id=trace_id,
            job_id=job_id,
            doc_count=len(json_docs),
            elapsed_ms=_elapsed_ms(download_started),
        )

        # 4) OCR JSON を Markdown 化する。Gemini失敗時はフォールバックで継続する。
        markdown_started = time.perf_counter()
        try:
            markdown, stats = build_markdown_from_documentai_jsons(
                json_docs=json_docs,
                llm_service=llm_service,
                enable_gemini_polish=settings.enable_gemini_polish,
            )
        except RuntimeError as e:
            if settings.enable_gemini_polish and "Gemini API request failed" in str(e):
                fallback_used = True
                _log_event(
                    level=logging.WARNING,
                    stage="markdown_build_fallback",
                    request_id=request_id,
                    trace_id=trace_id,
                    job_id=job_id,
                    reason="gemini_timeout_or_request_error",
                )
                markdown, stats = build_markdown_from_documentai_jsons(
                    json_docs=json_docs,
                    llm_service=llm_service,
                    enable_gemini_polish=False,
                )
            else:
                raise

        _log_event(
            level=logging.INFO,
            stage="markdown_built",
            request_id=request_id,
            trace_id=trace_id,
            job_id=job_id,
            markdown_chars=len(markdown),
            stats=stats,
            fallback_used=fallback_used,
            elapsed_ms=_elapsed_ms(markdown_started),
        )

        used_gemini = bool(stats.get("used_gemini", False))

        # 5) 生成Markdownを output バケットへ保存し、ジョブ完了状態を反映する。
        object_name = f"{input_name}/{input_generation}.md"

        upload_started = time.perf_counter()
        output_uri = storage_service.write_markdown(
            bucket_name=settings.output_bucket,
            object_name=object_name,
            markdown=markdown,
        )

        _log_event(
            level=logging.INFO,
            stage="markdown_uploaded",
            request_id=request_id,
            trace_id=trace_id,
            job_id=job_id,
            output_uri=output_uri,
            elapsed_ms=_elapsed_ms(upload_started),
        )

        job_store.update_fields(
            job_id,
            {
                "status": "MD_SUCCEEDED",
                "output_markdown_uri": output_uri,
                "md_stats": stats,
                "fallback_used": fallback_used,
                "md_completed_at": job_store.now_iso(),
                "updated_at": job_store.now_iso(),
            },
        )

        _log_event(
            level=logging.INFO,
            stage="job_completed",
            request_id=request_id,
            trace_id=trace_id,
            job_id=job_id,
            status="MD_SUCCEEDED",
        )

        final_status = "MD_SUCCEEDED"

    except Exception as e:  # noqa: BLE001
        # 失敗時は分類情報を残し、ジョブ状態を MD_FAILED に更新して再送出する。
        error_kind = type(e).__name__
        error_message = _short_text(repr(e), max_len=600)
        traceback_text = traceback.format_exc()
        stacktrace_hash = hashlib.sha1(
            traceback_text.encode("utf-8")).hexdigest()[:12]

        is_retryable = "ReadTimeout" in error_message or "Timeout" in error_message

        _log_event(
            level=logging.ERROR,
            stage="failed",
            request_id=request_id,
            trace_id=trace_id,
            job_id=job_id,
            error_kind=error_kind,
            error_message=error_message,
            retryable=is_retryable,
            stacktrace_hash=stacktrace_hash,
        )

        logger.error(
            "[%s] Unexpected error while generating markdown: %s (kind=%s stacktrace_hash=%s)",
            request_id,
            e,
            error_kind,
            stacktrace_hash,
            exc_info=True,
        )

        final_status = "MD_FAILED"

        try:
            if job_id:
                job_store.update_fields(
                    job_id,
                    {
                        "status": "MD_FAILED",
                        "last_error": repr(e),
                        "md_failed_at": job_store.now_iso(),
                        "updated_at": job_store.now_iso(),
                    },
                )
                _log_event(
                    level=logging.ERROR,
                    stage="job_status_updated",
                    request_id=request_id,
                    trace_id=trace_id,
                    job_id=job_id,
                    status="MD_FAILED",
                )
        except Exception:  # noqa: BLE001
            logger.exception(
                "[%s] Failed to update MD_FAILED status", request_id)

        raise

    finally:
        # 成功/失敗に関わらず、実行サマリーを最後に1件出力する。
        _log_event(
            level=logging.INFO,
            stage="finished",
            request_id=request_id,
            trace_id=trace_id,
            job_id=job_id,
            final_status=final_status,
            fallback_used=fallback_used,
            used_gemini=used_gemini,
            error_kind=error_kind,
            error_message=error_message,
            stacktrace_hash=stacktrace_hash,
            total_elapsed_ms=_elapsed_ms(started_at),
        )
