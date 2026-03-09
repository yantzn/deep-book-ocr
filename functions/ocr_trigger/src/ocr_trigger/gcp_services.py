from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from google.api_core.client_options import ClientOptions
from google.cloud import documentai_v1 as documentai
from google.cloud import storage

from .config import Settings

logger = logging.getLogger(__name__)


class GCSService:
    def __init__(self, settings: Settings):
        self.settings = settings

        started_at = time.perf_counter()
        self.client = storage.Client(project=settings.gcp_project_id)
        logger.info(
            "Initialized GCS client: project=%s elapsed_ms=%s",
            settings.gcp_project_id,
            int((time.perf_counter() - started_at) * 1000),
        )

    def blob_exists(self, bucket_name: str, blob_name: str) -> bool:
        bucket = self.client.bucket(bucket_name)
        blob = bucket.blob(blob_name)

        started_at = time.perf_counter()
        exists = blob.exists()
        logger.info(
            "Checked blob existence: gs://%s/%s exists=%s elapsed_ms=%s",
            bucket_name,
            blob_name,
            exists,
            int((time.perf_counter() - started_at) * 1000),
        )
        return exists

    def get_blob_metadata(self, bucket_name: str, blob_name: str) -> dict[str, object]:
        """
        GCP デプロイ後の切り分け用。
        - blob.exists() だけでなく reload() まで行い、GCS から見える実体をログ可能にする。
        """
        bucket = self.client.bucket(bucket_name)
        blob = bucket.blob(blob_name)

        result: dict[str, object] = {
            "bucket": bucket_name,
            "name": blob_name,
            "exists": False,
        }

        started_at = time.perf_counter()

        try:
            exists = blob.exists()
            result["exists"] = exists

            if exists:
                blob.reload()
                result.update(
                    {
                        "size": blob.size,
                        "content_type": blob.content_type,
                        "generation": blob.generation,
                        "metageneration": blob.metageneration,
                        "crc32c": blob.crc32c,
                        "md5_hash": blob.md5_hash,
                        "time_created": blob.time_created.isoformat() if blob.time_created else None,
                        "updated": blob.updated.isoformat() if blob.updated else None,
                    }
                )

            result["elapsed_ms"] = int(
                (time.perf_counter() - started_at) * 1000)
            return result

        except Exception as e:
            result["error"] = repr(e)
            result["elapsed_ms"] = int(
                (time.perf_counter() - started_at) * 1000)
            logger.exception(
                "Failed to get blob metadata: gs://%s/%s result=%r",
                bucket_name,
                blob_name,
                result,
            )
            raise


class DocumentAIService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.api_endpoint = self._build_api_endpoint(
            settings.processor_location)

        client_options = (
            ClientOptions(api_endpoint=self.api_endpoint)
            if self.api_endpoint
            else None
        )

        started_at = time.perf_counter()
        self.client = documentai.DocumentProcessorServiceClient(
            client_options=client_options
        )
        logger.info(
            "Initialized Document AI client: project=%s location=%s endpoint=%s elapsed_ms=%s",
            settings.gcp_project_id,
            settings.processor_location,
            self.api_endpoint or "default",
            int((time.perf_counter() - started_at) * 1000),
        )

    @staticmethod
    def _build_api_endpoint(location: str) -> str | None:
        """
        Document AI は `us` の場合はデフォルト endpoint でも動くことが多いが、
        `eu` や `asia-northeast1` など regional processor の場合は regional endpoint を
        明示した方が安全。
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
            self.settings.processor_id_normalized(),
        )

    @staticmethod
    def _build_input_uri(input_bucket: str, file_name: str) -> str:
        return f"gs://{input_bucket}/{file_name}"

    def _build_output_uri(self, file_name: str) -> str:
        base = self.settings.temp_bucket_uri()
        if not base.endswith("/"):
            base += "/"
        return f"{base}{file_name}_json/"

    def start_ocr_batch_job(
        self,
        input_bucket: str,
        file_name: str,
        request_id: str | None = None,
    ) -> tuple[str, str]:
        """
        Document AI の batch OCR ジョブを投入する。
        戻り値: (operation_name, output_uri)
        """
        rid = request_id or "-"
        overall_started_at = time.perf_counter()

        processor_name = self._build_processor_name()
        input_uri = self._build_input_uri(input_bucket, file_name)
        output_uri = self._build_output_uri(file_name)

        logger.info(
            "[%s] Starting Document AI batch submit: project=%s location=%s endpoint=%s "
            "processor_id=%s processor_name=%s input_uri=%s output_uri=%s submit_timeout_sec=%s",
            rid,
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

        logger.info("[%s] Prepared BatchProcessRequest for input=%s output=%s",
                    rid, input_uri, output_uri)

        started_at = time.perf_counter()
        try:
            operation = self.client.batch_process_documents(
                request=request,
                retry=None,
                timeout=self.settings.docai_submit_timeout_sec,
            )
        except Exception:
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            logger.exception(
                "[%s] Document AI batch submit failed: elapsed_ms=%s project=%s "
                "location=%s endpoint=%s processor_name=%s input_uri=%s output_uri=%s",
                rid,
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
                "[%s] Document AI returned operation without name: project=%s location=%s "
                "endpoint=%s processor_name=%s input_uri=%s output_uri=%s raw_operation=%r",
                rid,
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
            "[%s] Document AI batch accepted: operation=%s submit_elapsed_ms=%s total_elapsed_ms=%s output_uri=%s",
            rid,
            operation_name,
            elapsed_ms,
            int((time.perf_counter() - overall_started_at) * 1000),
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
