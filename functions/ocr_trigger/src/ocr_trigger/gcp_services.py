from __future__ import annotations

import logging

from google.cloud import documentai_v1 as documentai

from .config import Settings

logger = logging.getLogger(__name__)


class DocumentAIService:
    """A service for interacting with the Google Cloud Document AI API."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = documentai.DocumentProcessorServiceClient()

    def start_ocr_batch_job(self, input_bucket: str, file_name: str) -> str:
        logger.info("Starting OCR job for gs://%s/%s", input_bucket, file_name)

        # ---- processor ----
        processor_id = self.settings.processor_id_normalized()
        name = self.client.processor_path(
            self.settings.gcp_project_id,
            self.settings.processor_location,
            processor_id,
        )

        # ---- input (official field: input_documents) ----
        gcs_document = documentai.GcsDocument(
            gcs_uri=f"gs://{input_bucket}/{file_name}",
            mime_type="application/pdf",
        )
        gcs_documents = documentai.GcsDocuments(documents=[gcs_document])
        input_config = documentai.BatchDocumentsInputConfig(
            gcs_documents=gcs_documents)

        # ---- output (official field: document_output_config) ----
        # gcs_uri は「出力ディレクトリURI」なので末尾 / を付ける
        output_uri = f"{self.settings.temp_bucket_uri()}{file_name}_json/"

        gcs_output_config = documentai.DocumentOutputConfig.GcsOutputConfig(
            gcs_uri=output_uri
        )
        document_output_config = documentai.DocumentOutputConfig(
            gcs_output_config=gcs_output_config
        )

        # input_documents / document_output_config を使う
        request = documentai.BatchProcessRequest(
            name=name,
            input_documents=input_config,
            document_output_config=document_output_config,
        )

        operation = self.client.batch_process_documents(request=request)
        logger.info("OCR Job started. Operation: %s", operation.operation.name)
        return operation.operation.name


class Services:
    def __init__(self, settings: Settings):
        self.docai_service = DocumentAIService(settings)


def build_services(settings: Settings) -> Services:
    return Services(settings)
