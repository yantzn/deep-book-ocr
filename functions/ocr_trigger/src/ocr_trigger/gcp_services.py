from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from typing import Any

from google.api_core.client_options import ClientOptions
from google.cloud import documentai_v1 as documentai
from google.cloud import storage

from .config import Settings

logger = logging.getLogger(__name__)


class GCSService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = storage.Client(project=settings.gcp_project_id)

    def blob_exists(self, bucket_name: str, blob_name: str) -> bool:
        bucket = self.client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        exists = blob.exists()
        logger.info("Checked blob existence: gs://%s/%s exists=%s",
                    bucket_name, blob_name, exists)
        return exists


class DocumentAIService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.api_endpoint = self._build_api_endpoint(
            settings.processor_location)
        client_options = (
            ClientOptions(
                api_endpoint=self.api_endpoint) if self.api_endpoint else None
        )
        self.client = documentai.DocumentProcessorServiceClient(
            client_options=client_options
        )

    @staticmethod
    def _build_api_endpoint(location: str) -> str | None:
        """
        Document AI は `us` の場合はデフォルト endpoint でも動くことが多いが、
        `eu` や `asia-northeast1` など regional processor の場合は
        regional endpoint を明示した方が安全。
        """
        normalized = (location or "").strip().lower()

        if not normalized or normalized == "us":
            return None

        if normalized == "eu":
            return "eu-documentai.googleapis.com"

        return f"{normalized}-documentai.googleapis.com"

    def _build_processor_name(self) -> str:
        return self.client.processor_path(
            self.settings.gcp_project_id,
            self.settings.processor_location,
            self.settings.processor_id,
        )

    def _build_input_uri(self, input_bucket: str, file_name: str) -> str:
        return f"gs://{input_bucket}/{file_name}"

    def _build_output_uri(self, file_name: str) -> str:
        base = self.settings.temp_bucket_uri()
        if not base.endswith("/"):
            base += "/"
        return f"{base}{file_name}_json/"

    def start_ocr_batch_job(self, input_bucket: str, file_name: str) -> tuple[str, str]:
        """
        Document AI の batch OCR ジョブを投入する。
        戻り値:
            (operation_name, output_uri)
        """
        processor_name = self._build_processor_name()
        input_uri = self._build_input_uri(input_bucket, file_name)
        output_uri = self._build_output_uri(file_name)

        logger.info(
            "Starting Document AI batch submit: project=%s location=%s endpoint=%s "
            "processor_id=%s processor_name=%s input_uri=%s output_uri=%s submit_timeout_sec=%s",
            self.settings.gcp_project_id,
            self.settings.processor_location,
            self.api_endpoint or "default",
            self.settings.processor_id,
            processor_name,
            input_uri,
            output_uri,
            self.settings.docai_submit_timeout_sec,
        )

        gcs_document = documentai.GcsDocument(
            gcs_uri=input_uri,
            mime_type="application/pdf",
        )

        input_config = documentai.BatchDocumentsInputConfig(
            gcs_documents=documentai.GcsDocuments(documents=[gcs_document])
        )

        output_config = documentai.DocumentOutputConfig(
            gcs_output_config=documentai.DocumentOutputConfig.GcsOutputConfig(
                gcs_uri=output_uri
            )
        )

        request = documentai.BatchProcessRequest(
            name=processor_name,
            input_documents=input_config,
            document_output_config=output_config,
        )

        started_at = time.perf_counter()

        def _submit() -> Any:
            return self.client.batch_process_documents(
                request=request,
                retry=None,
                timeout=self.settings.docai_submit_timeout_sec,
            )

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_submit)

            try:
                operation = future.result(
                    timeout=self.settings.docai_submit_timeout_sec)
            except FuturesTimeoutError as exc:
                elapsed_ms = int((time.perf_counter() - started_at) * 1000)
                future.cancel()
                logger.exception(
                    "Document AI batch submit timed out: elapsed_ms=%s project=%s "
                    "location=%s endpoint=%s processor_name=%s input_uri=%s output_uri=%s",
                    elapsed_ms,
                    self.settings.gcp_project_id,
                    self.settings.processor_location,
                    self.api_endpoint or "default",
                    processor_name,
                    input_uri,
                    output_uri,
                )
                raise TimeoutError(
                    "Document AI batch submission timed out before operation was returned"
                ) from exc
            except Exception:
                elapsed_ms = int((time.perf_counter() - started_at) * 1000)
                logger.exception(
                    "Document AI batch submit failed: elapsed_ms=%s project=%s "
                    "location=%s endpoint=%s processor_name=%s input_uri=%s output_uri=%s",
                    elapsed_ms,
                    self.settings.gcp_project_id,
                    self.settings.processor_location,
                    self.api_endpoint or "default",
                    processor_name,
                    input_uri,
                    output_uri,
                )
                raise

        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        operation_name = getattr(
            getattr(operation, "operation", None), "name", None)

        if not operation_name:
            logger.error(
                "Document AI returned operation without name: project=%s location=%s "
                "endpoint=%s processor_name=%s input_uri=%s output_uri=%s raw_operation=%r",
                self.settings.gcp_project_id,
                self.settings.processor_location,
                self.api_endpoint or "default",
                processor_name,
                input_uri,
                output_uri,
                operation,
            )
            raise RuntimeError(
                "Document AI returned an invalid operation response")

        logger.info(
            "Document AI batch accepted: operation=%s elapsed_ms=%s output_uri=%s",
            operation_name,
            elapsed_ms,
            output_uri,
        )
        return operation_name, output_uri


@dataclass(frozen=True)
class Services:
    gcs_service: GCSService
    docai_service: DocumentAIService


def build_services(settings: Settings) -> Services:
    return Services(
        gcs_service=GCSService(settings),
        docai_service=DocumentAIService(settings),
    )
