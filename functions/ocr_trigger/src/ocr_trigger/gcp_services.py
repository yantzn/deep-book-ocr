from __future__ import annotations

"""Document AI バッチOCR用のGCPサービスラッパー。

entrypoint から直接API詳細を分離し、責務を明確化する。
"""

import logging
from google.cloud import documentai_v1 as documentai

from .config import Settings

logger = logging.getLogger(__name__)


class DocumentAIService:
    """Google Cloud Document AI API と連携するサービス。"""

    def __init__(self, settings: Settings):
        """型付きの実行時設定を使って API クライアントを初期化する。"""
        self.settings = settings
        self.client = documentai.DocumentProcessorServiceClient()

    def start_ocr_batch_job(self, input_bucket: str, file_name: str) -> str:
        """
        Document AI のバッチ処理ジョブを開始する。
        入出力は gs:// URI のため、実GCSが必要。

        返り値:
        - operation name（監視・トラブルシュート用）
        """
        logger.info("OCRジョブを開始します: gs://%s/%s", input_bucket, file_name)

        resource_name = self.client.processor_path(
            self.settings.gcp_project_id,
            self.settings.processor_location,
            self.settings.processor_id,
        )

        gcs_document = documentai.GcsDocument(
            gcs_uri=f"gs://{input_bucket}/{file_name}",
            mime_type="application/pdf",
        )

        input_config = documentai.BatchDocumentsInputConfig(
            gcs_documents=documentai.GcsDocuments(documents=[gcs_document])
        )

        output_uri = f"{self.settings.temp_bucket_uri()}{file_name}_json/"
        output_config = documentai.DocumentOutputConfig(
            gcs_output_config=documentai.GcsOutputConfig(gcs_uri=output_uri)
        )

        request = documentai.BatchProcessRequest(
            name=resource_name,
            input_configs=[input_config],
            output_config=output_config,
        )

        try:
            operation = self.client.batch_process_documents(request=request)
            logger.info("OCRジョブを開始しました。Operation: %s",
                        operation.operation.name)
            return operation.operation.name
        except Exception:
            logger.exception("OCRジョブの開始に失敗しました")
            raise
