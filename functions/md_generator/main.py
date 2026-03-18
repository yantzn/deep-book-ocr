from __future__ import annotations

import importlib
import hashlib
import logging
import os
import sys
import time
import traceback
import uuid
from typing import Any

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


def _build_runtime_dependencies():
    settings = get_settings()
    services = build_services(settings)
    return settings, services.storage_service, services.llm_service, FirestoreJobStore(settings)


def _setup_logging() -> None:
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


@functions_framework.http
def generate_markdown(request: Request):
    """OCR結果JSONを集約し、Markdownを生成して保存する HTTP エントリポイント。"""
    # リクエスト単位の計測とログ相関IDを用意する。
    started_at = time.perf_counter()
    request_id = str(uuid.uuid4())[:8]
    trace_id = parse_trace_id(request.headers.get("X-Cloud-Trace-Context"))
    job_id = ""
    final_status = "UNKNOWN"
    fallback_used = False
    used_gemini: bool | None = None
    error_kind = ""
    error_message = ""
    stacktrace_hash = ""

    _setup_logging()

    # 設定・外部サービス依存を初期化する。
    # NOTE: リクエストごとに依存を生成して、テスト差し替えや設定反映を容易にする。
    settings, storage_service, llm_service, job_store = _build_runtime_dependencies()

    _log_event(
        level=logging.INFO,
        stage="request_received",
        request_id=request_id,
        trace_id=trace_id,
    )

    try:
        # 1) リクエストから job_id を取り出して入力検証する。
        # Workflow からの呼び出しは JSON body: {"job_id": "..."} を想定。
        body = request.get_json(silent=True) or {}
        job_id = str(body.get("job_id") or "").strip()

        _log_event(
            level=logging.INFO,
            stage="request_validated",
            request_id=request_id,
            job_id=job_id,
            trace_id=trace_id,
        )

        if not job_id:
            _log_event(
                level=logging.WARNING,
                stage="request_rejected",
                request_id=request_id,
                trace_id=trace_id,
                reason="missing_job_id",
            )
            final_status = "REQUEST_REJECTED"
            return ("job_id が必要です", 400)

        # 2) Firestore からジョブ定義を取得し、処理対象情報を確定する。
        # temp_output_prefix: DocAI JSON 出力先
        # input_name/input_generation: Markdown 出力オブジェクト名の構築に利用
        job = job_store.get_job(job_id)
        _log_event(
            level=logging.INFO,
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
        _log_event(
            level=logging.INFO,
            stage="job_status_updated",
            request_id=request_id,
            job_id=job_id,
            trace_id=trace_id,
            status="MD_RUNNING",
        )

        # 4) DocAI 出力プレフィックス配下の JSON 一覧を取得する。
        # 先に件数だけ確認し、0件なら即失敗にして原因追跡を容易にする。
        list_started = time.perf_counter()
        object_names = storage_service.list_object_names_from_gs_uri(
            temp_output_prefix)
        _log_event(
            level=logging.INFO,
            stage="ocr_json_listed",
            request_id=request_id,
            job_id=job_id,
            trace_id=trace_id,
            object_count=len(object_names),
            elapsed_ms=_elapsed_ms(list_started),
            prefix=temp_output_prefix,
        )

        if not object_names:
            raise RuntimeError(
                f"No OCR JSON objects found under prefix: {temp_output_prefix}")

        # 5) JSON 群を読み込み、Markdown 生成用の入力データを準備する。
        # DocAI のページ分割出力をまとめて取り込み、後段へ渡す。
        download_started = time.perf_counter()
        json_docs = storage_service.download_json_documents_from_gs_uri_prefix(
            temp_output_prefix)
        _log_event(
            level=logging.INFO,
            stage="ocr_json_downloaded",
            request_id=request_id,
            job_id=job_id,
            trace_id=trace_id,
            doc_count=len(json_docs),
            elapsed_ms=_elapsed_ms(download_started),
        )

        # 6) OCR JSON から下書き生成し、必要に応じて LLM で体裁を整える。
        # enable_gemini_polish が true の場合のみ、整形処理を有効化する。
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
                    job_id=job_id,
                    trace_id=trace_id,
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
            job_id=job_id,
            trace_id=trace_id,
            markdown_chars=len(markdown),
            stats=stats,
            fallback_used=fallback_used,
            elapsed_ms=_elapsed_ms(markdown_started),
        )
        used_gemini = bool(stats.get("used_gemini", False))

        # 7) 出力バケットへ Markdown を保存する。
        # 入力オブジェクト単位で追跡しやすいよう `<input_name>/<generation>.md` を採用。
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
            job_id=job_id,
            trace_id=trace_id,
            output_uri=output_uri,
            elapsed_ms=_elapsed_ms(upload_started),
        )

        # 8) 正常終了ステータスと成果物URI/統計を Firestore へ記録する。
        # 以降の可視化・再実行判断で参照されるため、統計情報も保存する。
        job_store.update_fields(
            job_id,
            {
                "status": "MD_SUCCEEDED",
                "output_markdown_uri": output_uri,
                "md_stats": stats,
                "fallback_used": fallback_used,
                "md_completed_at": job_store.now_iso(),
            },
        )
        _log_event(
            level=logging.INFO,
            stage="job_completed",
            request_id=request_id,
            job_id=job_id,
            trace_id=trace_id,
            status="MD_SUCCEEDED",
        )
        final_status = "MD_SUCCEEDED"

        return ("OK", 200)

    except Exception as e:
        error_kind = type(e).__name__
        error_message = _short_text(repr(e), max_len=600)
        traceback_text = traceback.format_exc()
        stacktrace_hash = hashlib.sha1(
            traceback_text.encode("utf-8")).hexdigest()[:12]
        is_retryable = "ReadTimeout" in error_message or "Timeout" in error_message
        # 例外時はログへ詳細を残し、可能な限りジョブ状態を FAILED へ更新する。
        _log_event(
            level=logging.ERROR,
            stage="failed",
            request_id=request_id,
            job_id=job_id,
            trace_id=trace_id,
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
                # job_id が確定済みなら失敗情報を Firestore に反映する。
                job_store.update_fields(
                    job_id,
                    {
                        "status": "MD_FAILED",
                        "last_error": repr(e),
                        "md_failed_at": job_store.now_iso(),
                    },
                )
                _log_event(
                    level=logging.ERROR,
                    stage="job_status_updated",
                    request_id=request_id,
                    job_id=job_id,
                    trace_id=trace_id,
                    status="MD_FAILED",
                )
        except Exception:
            # 失敗時の状態更新自体に失敗しても、元の 500 応答は維持する。
            logger.exception(
                "[%s] Failed to update MD_FAILED status", request_id)

        return ("Internal Server Error", 500)

    finally:
        # 成否にかかわらず総処理時間を記録する。
        _log_event(
            level=logging.INFO,
            stage="finished",
            request_id=request_id,
            job_id=job_id,
            trace_id=trace_id,
            final_status=final_status,
            fallback_used=fallback_used,
            used_gemini=used_gemini,
            error_kind=error_kind,
            error_message=error_message,
            stacktrace_hash=stacktrace_hash,
            total_elapsed_ms=_elapsed_ms(started_at),
        )
