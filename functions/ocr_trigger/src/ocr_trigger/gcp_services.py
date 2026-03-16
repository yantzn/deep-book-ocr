from __future__ import annotations

import importlib
import logging

from google.api_core.client_options import ClientOptions
from google.cloud import documentai_v1 as documentai

observability_module = importlib.import_module("ocr_trigger.observability")
log_pipeline_event = observability_module.log_pipeline_event

logger = logging.getLogger(__name__)


class DocumentAIService:
    def __init__(self, settings):
        # Processor location ごとの専用エンドポイントを使う。
        # 例: us-documentai.googleapis.com
        endpoint = f"{settings.processor_location}-documentai.googleapis.com"
        self.client = documentai.DocumentProcessorServiceClient(
            client_options=ClientOptions(api_endpoint=endpoint)
        )
        self.settings = settings

        log_pipeline_event(
            logger,
            level=logging.INFO,
            event="start_ocr",
            stage="docai_service_initialized",
            endpoint=endpoint,
            project=settings.gcp_project_id,
            location=settings.processor_location,
        )

    def submit_batch_process(self, bucket: str, name: str, output_prefix: str) -> str:
        # 入力PDFと出力先プレフィックスを DocAI batch 処理用の request に組み立てる。
        # ここでは submit のみを担当し、完了待ちは呼び出し側（Workflow）で行う。
        input_uri = f"gs://{bucket}/{name}"

        log_pipeline_event(
            logger,
            level=logging.INFO,
            event="start_ocr",
            stage="docai_submit_started",
            input_uri=input_uri,
            output_prefix=output_prefix,
        )

        processor_name = self.client.processor_path(
            self.settings.gcp_project_id,
            self.settings.processor_location,
            self.settings.processor_id_normalized(),
        )

        request = documentai.BatchProcessRequest(
            name=processor_name,
            input_documents=documentai.BatchDocumentsInputConfig(
                gcs_documents=documentai.GcsDocuments(
                    documents=[
                        documentai.GcsDocument(
                            gcs_uri=input_uri,
                            mime_type="application/pdf",
                        )
                    ]
                )
            ),
            document_output_config=documentai.DocumentOutputConfig(
                gcs_output_config=documentai.DocumentOutputConfig.GcsOutputConfig(
                    gcs_uri=output_prefix
                )
            ),
        )

        operation = self.client.batch_process_documents(request=request)

        log_pipeline_event(
            logger,
            level=logging.INFO,
            event="start_ocr",
            stage="docai_submit_succeeded",
            input_uri=input_uri,
            operation_name=operation.operation.name,
            processor_name=processor_name,
        )

        # 非同期LROの operation name を返して、後続が状態監視できるようにする。
        return operation.operation.name

    def start_ocr_batch_job(self, bucket: str, name: str) -> tuple[str, str]:
        # trigger 側のユースケース向けに、output_prefix 算出と submit をまとめる。
        output_prefix = f"{self.settings.temp_bucket_uri()}{name}_json/"
        operation_name = self.submit_batch_process(
            bucket=bucket,
            name=name,
            output_prefix=output_prefix,
        )
        return operation_name, output_prefix
