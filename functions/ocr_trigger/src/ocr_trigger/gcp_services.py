# src/ocr_trigger/gcp_services.py
import logging
from google.cloud import documentai_v1 as documentai
from .config import Settings


class DocumentAIService:
    """A service for interacting with the Google Cloud Document AI API."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = documentai.DocumentProcessorServiceClient()

    def start_ocr_batch_job(self, input_bucket: str, file_name: str) -> str:
        """
        Starts a new Document AI batch processing job.

        Args:
            input_bucket: The GCS bucket of the input file.
            file_name: The name of the file in the GCS bucket.

        Returns:
            The name of the long-running operation.
        """
        logging.info(f"Starting OCR job for gs://{input_bucket}/{file_name}")

        # The full resource name of the processor
        resource_name = self.client.processor_path(
            self.settings.gcp_project_id,
            self.settings.processor_location,
            self.settings.processor_id,
        )

        # Input document
        gcs_document = documentai.GcsDocument(
            gcs_uri=f"gs://{input_bucket}/{file_name}",
            mime_type="application/pdf",
        )
        input_config = documentai.BatchDocumentsInputConfig(
            gcs_documents=documentai.GcsDocuments(documents=[gcs_document])
        )

        # Output configuration
        output_uri = f"{self.settings.temp_bucket}/{file_name}_json/"
        output_config = documentai.DocumentOutputConfig(
            gcs_output_config=documentai.GcsOutputConfig(gcs_uri=output_uri)
        )

        # Create the request
        request = documentai.BatchProcessRequest(
            name=resource_name,
            input_configs=[input_config],
            output_config=output_config,
        )

        # Start the batch process
        try:
            operation = self.client.batch_process_documents(request=request)
            logging.info(
                f"OCR Job started. Operation: {operation.operation.name}"
            )
            return operation.operation.name
        except Exception as e:
            logging.error(f"Failed to start OCR job: {e}")
            raise

