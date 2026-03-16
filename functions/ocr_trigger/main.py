from __future__ import annotations

import importlib
import logging
import os
import sys
import time
import uuid

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
            "Logging initialized: Cloud Logging enabled level=%s",
            settings.log_level,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "Cloud Logging setup failed; fallback to std logging: %s",
            e,
        )


settings = get_settings()
docai_service = DocumentAIService(settings)
job_store = FirestoreJobStore(settings)
workflow_service = WorkflowExecutionService(settings)


@functions_framework.cloud_event
def start_ocr(event: CloudEvent):
    started_at = time.perf_counter()
    request_id = str(uuid.uuid4())[:8]

    _setup_logging()

    log_pipeline_event(
        logger,
        level=logging.INFO,
        event="start_ocr",
        stage="event_received",
        request_id=request_id,
    )

    try:
        data = event.data or {}
        bucket = str(data.get("bucket") or "").strip()
        name = str(data.get("name") or "").strip()
        generation = str(data.get("generation") or "").strip()
        metageneration = str(data.get("metageneration") or "").strip()

        if not bucket or not name:
            log_pipeline_event(
                logger,
                level=logging.WARNING,
                event="start_ocr",
                stage="event_rejected",
                request_id=request_id,
                reason="missing_bucket_or_name",
            )
            return ("invalid event data", 400)

        log_pipeline_event(
            logger,
            level=logging.INFO,
            event="start_ocr",
            stage="event_parsed",
            request_id=request_id,
            bucket=bucket,
            name=name,
            generation=generation,
            metageneration=metageneration,
        )

        if not name.lower().endswith(".pdf"):
            log_pipeline_event(
                logger,
                level=logging.INFO,
                event="start_ocr",
                stage="skipped",
                request_id=request_id,
                reason="non_pdf_object",
                name=name,
            )
            return ("skipped: non-pdf", 200)

        submit_started = time.perf_counter()
        operation_name, output_uri = docai_service.start_ocr_batch_job(
            bucket, name)

        job_id = job_store.build_job_id(
            bucket=bucket, name=name, generation=generation)

        job_store.create_job(
            job_id=job_id,
            document={
                "job_id": job_id,
                "status": "DOC_AI_SUBMITTED",
                "input_bucket": bucket,
                "input_name": name,
                "input_generation": generation,
                "input_metageneration": metageneration,
                "temp_output_prefix": output_uri,
                "operation_name": operation_name,
                "created_at": job_store.now_iso(),
                "updated_at": job_store.now_iso(),
                "request_id": request_id,
            },
            merge=True,
        )

        log_pipeline_event(
            logger,
            level=logging.INFO,
            event="start_ocr",
            stage="job_created",
            request_id=request_id,
            job_id=job_id,
            input_uri=f"gs://{bucket}/{name}",
            operation_name=operation_name,
            output_prefix=output_uri,
        )

        workflow_execution_name = workflow_service.start_docai_monitor(
            job_id=job_id,
            operation_name=operation_name,
        )

        job_store.update_fields(
            job_id,
            {
                "workflow_execution_name": workflow_execution_name,
                "workflow_started_at": job_store.now_iso(),
                "updated_at": job_store.now_iso(),
            },
        )

        log_pipeline_event(
            logger,
            level=logging.INFO,
            event="start_ocr",
            stage="docai_monitor_started",
            request_id=request_id,
            job_id=job_id,
            workflow_execution_name=workflow_execution_name,
            operation_name=operation_name,
            elapsed_ms=int((time.perf_counter() - submit_started) * 1000),
        )

        return ("OK", 200)

    except Exception as e:  # noqa: BLE001
        log_pipeline_event(
            logger,
            level=logging.ERROR,
            event="start_ocr",
            stage="failed",
            request_id=request_id,
            error=repr(e),
        )
        logger.exception(
            "[%s] Unexpected error while starting OCR: %s", request_id, e)
        return ("Internal Server Error", 500)

    finally:
        log_pipeline_event(
            logger,
            level=logging.INFO,
            event="start_ocr",
            stage="finished",
            request_id=request_id,
            total_elapsed_ms=int((time.perf_counter() - started_at) * 1000),
        )
