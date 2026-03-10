from __future__ import annotations

import importlib
import logging
import os
import sys
import time
import uuid

import functions_framework
from flask import Request

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
parse_trace_id = observability_module.parse_trace_id

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
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


@functions_framework.http
def generate_markdown(request: Request):
    # リクエスト単位の計測とログ相関IDを用意する。
    started_at = time.perf_counter()
    request_id = str(uuid.uuid4())[:8]
    trace_id = parse_trace_id(request.headers.get("X-Cloud-Trace-Context"))
    job_id = ""

    _setup_logging()

    # 設定・外部サービス依存を初期化する。
    settings = get_settings()
    services = build_services(settings)
    storage_service = services.storage_service
    llm_service = services.llm_service
    job_store = FirestoreJobStore(settings)

    log_pipeline_event(
        logger,
        level=logging.INFO,
        event="generate_markdown",
        stage="request_received",
        request_id=request_id,
        trace_id=trace_id,
    )

    try:
        # 1) リクエストから job_id を取り出して入力検証する。
        body = request.get_json(silent=True) or {}
        job_id = str(body.get("job_id") or "").strip()

        log_pipeline_event(
            logger,
            level=logging.INFO,
            event="generate_markdown",
            stage="request_validated",
            request_id=request_id,
            job_id=job_id,
            trace_id=trace_id,
        )

        if not job_id:
            log_pipeline_event(
                logger,
                level=logging.WARNING,
                event="generate_markdown",
                stage="request_rejected",
                request_id=request_id,
                trace_id=trace_id,
                reason="missing_job_id",
            )
            return ("job_id が必要です", 400)

        # 2) Firestore からジョブ定義を取得し、処理対象情報を確定する。
        job = job_store.get_job(job_id)
        log_pipeline_event(
            logger,
            level=logging.INFO,
            event="generate_markdown",
            stage="job_loaded",
            request_id=request_id,
            job_id=job_id,
            trace_id=trace_id,
            temp_output_prefix=job.get("temp_output_prefix"),
        )

        temp_output_prefix = str(job["temp_output_prefix"])
        input_name = str(job["input_name"])
        input_generation = str(job["input_generation"])

        # 3) 処理開始を Firestore に反映する（監視/UI 参照用）。
        job_store.update_fields(
            job_id,
            {
                "status": "MD_RUNNING",
                "md_started_at": job_store.now_iso(),
            },
        )
        log_pipeline_event(
            logger,
            level=logging.INFO,
            event="generate_markdown",
            stage="job_status_updated",
            request_id=request_id,
            job_id=job_id,
            trace_id=trace_id,
            status="MD_RUNNING",
        )

        # 4) DocAI 出力プレフィックス配下の JSON 一覧を取得する。
        list_started = time.perf_counter()
        object_names = storage_service.list_object_names_from_gs_uri(
            temp_output_prefix)
        log_pipeline_event(
            logger,
            level=logging.INFO,
            event="generate_markdown",
            stage="ocr_json_listed",
            request_id=request_id,
            job_id=job_id,
            trace_id=trace_id,
            object_count=len(object_names),
            elapsed_ms=int((time.perf_counter() - list_started) * 1000),
            prefix=temp_output_prefix,
        )

        if not object_names:
            raise RuntimeError(
                f"No OCR JSON objects found under prefix: {temp_output_prefix}")

        # 5) JSON 群を読み込み、Markdown 生成用の入力データを準備する。
        download_started = time.perf_counter()
        json_docs = storage_service.download_json_documents_from_gs_uri_prefix(
            temp_output_prefix)
        log_pipeline_event(
            logger,
            level=logging.INFO,
            event="generate_markdown",
            stage="ocr_json_downloaded",
            request_id=request_id,
            job_id=job_id,
            trace_id=trace_id,
            doc_count=len(json_docs),
            elapsed_ms=int((time.perf_counter() - download_started) * 1000),
        )

        # 6) OCR JSON から下書き生成し、必要に応じて LLM で体裁を整える。
        markdown_started = time.perf_counter()
        markdown, stats = build_markdown_from_documentai_jsons(
            json_docs=json_docs,
            llm_service=llm_service,
            enable_gemini_polish=settings.enable_gemini_polish,
        )
        log_pipeline_event(
            logger,
            level=logging.INFO,
            event="generate_markdown",
            stage="markdown_built",
            request_id=request_id,
            job_id=job_id,
            trace_id=trace_id,
            markdown_chars=len(markdown),
            stats=stats,
            elapsed_ms=int((time.perf_counter() - markdown_started) * 1000),
        )

        # 7) 出力バケットへ Markdown を保存する。
        object_name = f"{input_name}/{input_generation}.md"
        upload_started = time.perf_counter()
        output_uri = storage_service.write_markdown(
            bucket_name=settings.output_bucket,
            object_name=object_name,
            markdown=markdown,
        )
        log_pipeline_event(
            logger,
            level=logging.INFO,
            event="generate_markdown",
            stage="markdown_uploaded",
            request_id=request_id,
            job_id=job_id,
            trace_id=trace_id,
            output_uri=output_uri,
            elapsed_ms=int((time.perf_counter() - upload_started) * 1000),
        )

        # 8) 正常終了ステータスと成果物URI/統計を Firestore へ記録する。
        job_store.update_fields(
            job_id,
            {
                "status": "MD_SUCCEEDED",
                "output_markdown_uri": output_uri,
                "md_stats": stats,
                "md_completed_at": job_store.now_iso(),
            },
        )
        log_pipeline_event(
            logger,
            level=logging.INFO,
            event="generate_markdown",
            stage="job_completed",
            request_id=request_id,
            job_id=job_id,
            trace_id=trace_id,
            status="MD_SUCCEEDED",
        )

        return ("OK", 200)

    except Exception as e:
        # 例外時はログへ詳細を残し、可能な限りジョブ状態を FAILED へ更新する。
        log_pipeline_event(
            logger,
            level=logging.ERROR,
            event="generate_markdown",
            stage="failed",
            request_id=request_id,
            job_id=job_id,
            trace_id=trace_id,
            error=repr(e),
        )
        logger.exception(
            "[%s] Unexpected error while generating markdown: %s", request_id, e)

        try:
            if job_id:
                job_store.update_fields(
                    job_id,
                    {
                        "status": "MD_FAILED",
                        "last_error": repr(e),
                        "md_failed_at": job_store.now_iso(),
                    },
                )
                log_pipeline_event(
                    logger,
                    level=logging.ERROR,
                    event="generate_markdown",
                    stage="job_status_updated",
                    request_id=request_id,
                    job_id=job_id,
                    trace_id=trace_id,
                    status="MD_FAILED",
                )
        except Exception:
            logger.exception(
                "[%s] Failed to update MD_FAILED status", request_id)

        return ("Internal Server Error", 500)

    finally:
        # 成否にかかわらず総処理時間を記録する。
        log_pipeline_event(
            logger,
            level=logging.INFO,
            event="generate_markdown",
            stage="finished",
            request_id=request_id,
            job_id=job_id,
            trace_id=trace_id,
            total_elapsed_ms=int((time.perf_counter() - started_at) * 1000),
        )
