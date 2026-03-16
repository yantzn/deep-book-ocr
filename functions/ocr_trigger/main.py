from __future__ import annotations

import importlib
import logging
import os
import sys
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import functions_framework
from cloudevents.http import CloudEvent

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

config_module = importlib.import_module("ocr_trigger.config")
gcp_services_module = importlib.import_module("ocr_trigger.gcp_services")
job_store_module = importlib.import_module("ocr_trigger.job_store")
observability_module = importlib.import_module("ocr_trigger.observability")
workflow_service_module = importlib.import_module(
    "ocr_trigger.workflow_service")

get_settings = config_module.get_settings
DocumentAIService = gcp_services_module.DocumentAIService
FirestoreJobStore = job_store_module.FirestoreJobStore
WorkflowExecutionService = workflow_service_module.WorkflowExecutionService
log_pipeline_event = observability_module.log_pipeline_event

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParsedStorageEvent:
    bucket: str
    name: str
    generation: str
    metageneration: str


def _elapsed_ms(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)


def _log_event(
    *,
    level: int,
    stage: str,
    request_id: str,
    **fields: Any,
) -> None:
    log_pipeline_event(
        logger,
        level=level,
        event="start_ocr",
        stage=stage,
        request_id=request_id,
        **fields,
    )


def _setup_logging() -> None:
    """ローカル実行と Cloud Run 実行の両方でロギングを初期化する。"""
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
            "Logging initialized: Cloud Logging enabled level=%s",
            settings.log_level,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "Cloud Logging setup failed; fallback to std logging: %s",
            e,
        )


def _parse_storage_event(event: CloudEvent) -> ParsedStorageEvent | None:
    """Cloud Storage イベントから必要項目を抽出し、欠損時は None を返す。"""
    data = event.data or {}
    bucket = str(data.get("bucket") or "").strip()
    name = str(data.get("name") or "").strip()
    generation = str(data.get("generation") or "").strip()
    metageneration = str(data.get("metageneration") or "").strip()

    if not bucket or not name:
        return None

    return ParsedStorageEvent(
        bucket=bucket,
        name=name,
        generation=generation,
        metageneration=metageneration,
    )


def _build_job_document(
    *,
    job_id: str,
    request_id: str,
    parsed: ParsedStorageEvent,
    operation_name: str,
    output_uri: str,
    now_iso: str,
) -> dict[str, Any]:
    """Firestore に保存する OCR ジョブ初期ドキュメントを構築する。"""
    return {
        "job_id": job_id,
        "status": "DOC_AI_SUBMITTED",
        "input_bucket": parsed.bucket,
        "input_name": parsed.name,
        "input_generation": parsed.generation,
        "input_metageneration": parsed.metageneration,
        "temp_output_prefix": output_uri,
        "operation_name": operation_name,
        "created_at": now_iso,
        "updated_at": now_iso,
        "request_id": request_id,
    }


@lru_cache(maxsize=1)
def _get_runtime_services() -> tuple[DocumentAIService, FirestoreJobStore, WorkflowExecutionService]:
    """実行時サービスを遅延初期化し、同一プロセス内で再利用する。"""
    settings = get_settings()
    return (
        DocumentAIService(settings),
        FirestoreJobStore(settings),
        WorkflowExecutionService(settings),
    )


@functions_framework.cloud_event
def start_ocr(event: CloudEvent):
    """GCS オブジェクトイベントを受け取り、非同期 OCR と監視 Workflow を開始する。"""
    # リクエスト単位の識別子と、全体処理時間計測用のタイマー。
    started_at = time.perf_counter()
    request_id = str(uuid.uuid4())[:8]

    _log_event(
        level=logging.INFO,
        stage="event_received",
        request_id=request_id,
    )

    try:
        _setup_logging()

        # 初回リクエスト時にのみ依存サービスを初期化し、以降はキャッシュを再利用する。
        docai_service, job_store, workflow_service = _get_runtime_services()

        # Cloud Storage イベントから必要フィールドを取り出して正規化する。
        parsed = _parse_storage_event(event)

        # オブジェクト位置が不足している不正イベントは早期に拒否する。
        if not parsed:
            _log_event(
                level=logging.WARNING,
                stage="event_rejected",
                request_id=request_id,
                reason="missing_bucket_or_name",
            )
            return ("invalid event data", 400)

        _log_event(
            level=logging.INFO,
            stage="event_parsed",
            request_id=request_id,
            bucket=parsed.bucket,
            name=parsed.name,
            generation=parsed.generation,
            metageneration=parsed.metageneration,
        )

        # PDF のみを処理対象とし、それ以外の拡張子は意図的にスキップする。
        if not parsed.name.lower().endswith(".pdf"):
            _log_event(
                level=logging.INFO,
                stage="skipped",
                request_id=request_id,
                reason="non_pdf_object",
                name=parsed.name,
            )
            return ("skipped: non-pdf", 200)

        # 1) Document AI のバッチ OCR ジョブを送信する。
        submit_started = time.perf_counter()
        operation_name, output_uri = docai_service.start_ocr_batch_job(
            parsed.bucket, parsed.name)

        # 2) 後続工程で追跡できるよう、Firestore にジョブ情報を作成/マージする。
        job_id = job_store.build_job_id(
            bucket=parsed.bucket,
            name=parsed.name,
            generation=parsed.generation,
        )

        now_iso = job_store.now_iso()

        job_store.create_job(
            job_id=job_id,
            document=_build_job_document(
                job_id=job_id,
                request_id=request_id,
                parsed=parsed,
                operation_name=operation_name,
                output_uri=output_uri,
                now_iso=now_iso,
            ),
            merge=True,
        )

        _log_event(
            level=logging.INFO,
            stage="job_created",
            request_id=request_id,
            job_id=job_id,
            input_uri=f"gs://{parsed.bucket}/{parsed.name}",
            operation_name=operation_name,
            output_prefix=output_uri,
        )

        # 3) DocAI オペレーション完了まで監視する Workflow を開始する。
        workflow_execution_name = workflow_service.start_docai_monitor(
            job_id=job_id,
            operation_name=operation_name,
        )

        # 4) 後続で実行を関連付けられるよう Workflow 実行情報を保存する。
        job_store.update_fields(
            job_id,
            {
                "workflow_execution_name": workflow_execution_name,
                "workflow_started_at": job_store.now_iso(),
                "updated_at": job_store.now_iso(),
            },
        )

        _log_event(
            level=logging.INFO,
            stage="docai_monitor_started",
            request_id=request_id,
            job_id=job_id,
            workflow_execution_name=workflow_execution_name,
            operation_name=operation_name,
            elapsed_ms=_elapsed_ms(submit_started),
        )

        return ("OK", 200)

    except Exception as e:  # noqa: BLE001
        # 想定外エラーはリクエスト文脈付きで記録し、500 を返す。
        _log_event(
            level=logging.ERROR,
            stage="failed",
            request_id=request_id,
            error=repr(e),
        )
        logger.exception(
            "[%s] Unexpected error while starting OCR: %s", request_id, e)
        return ("Internal Server Error", 500)

    finally:
        # 成否に関わらず、必ず完了メトリクスを出力する。
        _log_event(
            level=logging.INFO,
            stage="finished",
            request_id=request_id,
            total_elapsed_ms=_elapsed_ms(started_at),
        )
