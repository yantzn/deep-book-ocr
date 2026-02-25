from __future__ import annotations

"""
Document AI バッチOCR用のGCPサービスラッパー。

このモジュールのポイント:
- OCRは「同期完了」ではなく「非同期ジョブの投入」
- 返り値の operation name は、後続で状態確認・障害調査に使う識別子
"""

import logging
import time
from dataclasses import dataclass

from google.cloud import documentai_v1 as documentai

from .config import Settings

logger = logging.getLogger(__name__)


class DocumentAIService:
    """Google Cloud Document AI API と連携するサービス。"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = documentai.DocumentProcessorServiceClient()

    def start_ocr_batch_job(self, input_bucket: str, file_name: str) -> str:
        """
        Document AI のバッチ処理ジョブを開始する。

        返り値:
          - operation name（監視・トラブルシュート用）

        注意:
          - ここで返すのは「ジョブ投入成功」時点のID
          - OCR JSONの生成完了は別タイミング（非同期）
        """
        input_uri = f"gs://{input_bucket}/{file_name}"

        # 1) Processor リソース名
        processor_id = self.settings.processor_id_normalized()
        processor_resource = self.client.processor_path(
            self.settings.gcp_project_id,
            self.settings.processor_location,
            processor_id,
        )

        # 2) 入力（GCS PDF）
        gcs_document = documentai.GcsDocument(
            gcs_uri=input_uri,
            mime_type="application/pdf",
        )
        input_config = documentai.BatchDocumentsInputConfig(
            gcs_documents=documentai.GcsDocuments(documents=[gcs_document])
        )

        # 3) 出力先（GCS prefix）
        output_uri = f"{self.settings.temp_bucket_uri()}{file_name}_json/"
        output_config = documentai.DocumentOutputConfig(
            gcs_output_config=documentai.DocumentOutputConfig.GcsOutputConfig(
                gcs_uri=output_uri
            )
        )

        # 4) リクエスト
        request = documentai.BatchProcessRequest(
            name=processor_resource,
            input_documents=input_config,
            document_output_config=output_config,
        )

        logger.info(
            "Submitting Document AI batch: input_uri=%s output_uri=%s processor=%s location=%s timeout_sec=%d",
            input_uri,
            output_uri,
            processor_id,
            self.settings.processor_location,
            self.settings.docai_submit_timeout_sec,
        )

        try:
            started_at = time.perf_counter()

            # 重要: ここでは "受理(accepted)" までしか待たない
            # LRO(Operation) の完了待ちはしない
            operation = self.client.batch_process_documents(
                request=request,
                retry=None,
                timeout=self.settings.docai_submit_timeout_sec,
            )

            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            op_name = operation.operation.name

            logger.info(
                "Document AI batch accepted: operation=%s elapsed_ms=%d output_uri=%s",
                op_name,
                elapsed_ms,
                output_uri,
            )
            return op_name

        except Exception:
            logger.exception(
                "Failed to submit Document AI batch: input_uri=%s output_uri=%s processor=%s location=%s",
                input_uri,
                output_uri,
                processor_id,
                self.settings.processor_location,
            )
            raise


@dataclass(frozen=True)
class Services:
    docai_service: DocumentAIService


def build_services(settings: Settings) -> Services:
    return Services(docai_service=DocumentAIService(settings))
