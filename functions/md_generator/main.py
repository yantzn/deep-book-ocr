from __future__ import annotations

import importlib
import json
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

get_settings = config_module.get_settings
build_services = gcp_services_module.build_services
FirestoreJobStore = job_store_module.FirestoreJobStore
build_markdown_from_documentai_jsons = markdown_logic_module.build_markdown_from_documentai_jsons

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
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


@functions_framework.http
def generate_markdown(request: Request):
    started_at = time.perf_counter()
    request_id = str(uuid.uuid4())[:8]

    _setup_logging()

    settings = get_settings()
    services = build_services(settings)
    storage_service = services.storage_service
    llm_service = services.llm_service
    job_store = FirestoreJobStore(settings)

    logger.info(
        "[%s] generate_markdown entered service=%s revision=%s",
        request_id,
        os.getenv("K_SERVICE", ""),
        os.getenv("K_REVISION", ""),
    )

    try:
        body = request.get_json(silent=True) or {}
        job_id = str(body.get("job_id") or "").strip()

        logger.info("[%s] request_body=%s", request_id,
                    json.dumps(body, ensure_ascii=False, default=str))

        if not job_id:
            logger.warning("[%s] missing job_id", request_id)
            return ("job_id が必要です", 400)

        job = job_store.get_job(job_id)
        logger.info("[%s] loaded_job=%s", request_id, json.dumps(
            job, ensure_ascii=False, default=str))

        temp_output_prefix = str(job["temp_output_prefix"])
        input_name = str(job["input_name"])
        input_generation = str(job["input_generation"])

        job_store.update_fields(
            job_id,
            {
                "status": "MD_RUNNING",
                "md_started_at": job_store.now_iso(),
            },
        )

        list_started = time.perf_counter()
        object_names = storage_service.list_object_names_from_gs_uri(
            temp_output_prefix)
        logger.info(
            "[%s] listed_objects count=%s elapsed_ms=%s prefix=%s",
            request_id,
            len(object_names),
            int((time.perf_counter() - list_started) * 1000),
            temp_output_prefix,
        )

        if not object_names:
            raise RuntimeError(
                f"No OCR JSON objects found under prefix: {temp_output_prefix}")

        download_started = time.perf_counter()
        json_docs = storage_service.download_json_documents_from_gs_uri_prefix(
            temp_output_prefix)
        logger.info(
            "[%s] downloaded_json_docs count=%s elapsed_ms=%s",
            request_id,
            len(json_docs),
            int((time.perf_counter() - download_started) * 1000),
        )

        markdown_started = time.perf_counter()
        markdown, stats = build_markdown_from_documentai_jsons(
            json_docs=json_docs,
            llm_service=llm_service,
            enable_gemini_polish=settings.enable_gemini_polish,
        )
        logger.info(
            "[%s] markdown_built chars=%s stats=%s elapsed_ms=%s",
            request_id,
            len(markdown),
            json.dumps(stats, ensure_ascii=False, default=str),
            int((time.perf_counter() - markdown_started) * 1000),
        )

        object_name = f"{input_name}/{input_generation}.md"
        upload_started = time.perf_counter()
        output_uri = storage_service.write_markdown(
            bucket_name=settings.output_bucket,
            object_name=object_name,
            markdown=markdown,
        )
        logger.info(
            "[%s] markdown_uploaded output_uri=%s elapsed_ms=%s",
            request_id,
            output_uri,
            int((time.perf_counter() - upload_started) * 1000),
        )

        job_store.update_fields(
            job_id,
            {
                "status": "MD_SUCCEEDED",
                "output_markdown_uri": output_uri,
                "md_stats": stats,
                "md_completed_at": job_store.now_iso(),
            },
        )

        return ("OK", 200)

    except Exception as e:
        logger.exception(
            "[%s] Unexpected error while generating markdown: %s", request_id, e)

        try:
            body = request.get_json(silent=True) or {}
            job_id = str(body.get("job_id") or "").strip()
            if job_id:
                job_store.update_fields(
                    job_id,
                    {
                        "status": "MD_FAILED",
                        "last_error": repr(e),
                        "md_failed_at": job_store.now_iso(),
                    },
                )
        except Exception:
            logger.exception(
                "[%s] Failed to update MD_FAILED status", request_id)

        return ("Internal Server Error", 500)

    finally:
        logger.info(
            "[%s] generate_markdown finished total_elapsed_ms=%s",
            request_id,
            int((time.perf_counter() - started_at) * 1000),
        )
