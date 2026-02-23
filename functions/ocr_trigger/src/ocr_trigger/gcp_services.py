from __future__ import annotations

"""
Document AI バッチOCR用のGCPサービスラッパー。

entrypoint から直接API詳細を分離し、責務を明確化する。

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
        """型付きの実行時設定を使って API クライアントを初期化する。"""
        # エントリーポイントから受け取った設定を保持する。
        self.settings = settings
        # Document AI API クライアントを生成する。
        self.client = documentai.DocumentProcessorServiceClient()

    def start_ocr_batch_job(self, input_bucket: str, file_name: str) -> str:
        """
        Document AI のバッチ処理ジョブを開始する。

        入出力は gs:// URI のため、実GCSが必要。
        返り値:
                    - operation name（監視・トラブルシュート用）

                注意:
                - ここで返すのは「ジョブ投入成功」時点のID
                - OCR JSONの生成完了は別タイミング（非同期）
        """
        # 0) 入力対象をログに記録し、ジョブ投入開始を明示する。
        logger.info("Submitting OCR batch request: input_uri=gs://%s/%s",
                    input_bucket, file_name)

        # 1) Processor リソース名を組み立てる。
        resource_name = self.client.processor_path(
            self.settings.gcp_project_id,
            self.settings.processor_location,
            self.settings.processor_id,
        )

        # 2) 入力PDF（GCS）を指定する。
        #    file_name は「バケット内オブジェクト名」を想定（gs:// は付けない）。
        gcs_document = documentai.GcsDocument(
            gcs_uri=f"gs://{input_bucket}/{file_name}",
            mime_type="application/pdf",
        )

        input_config = documentai.BatchDocumentsInputConfig(
            gcs_documents=documentai.GcsDocuments(documents=[gcs_document])
        )

        # 3) 出力先プレフィックス（Document AI JSON）を組み立てる。
        #    末尾スラッシュ配下に Document AI が JSON 群を作成する。
        output_uri = f"{self.settings.temp_bucket_uri()}{file_name}_json/"
        output_config = documentai.DocumentOutputConfig(
            gcs_output_config=documentai.DocumentOutputConfig.GcsOutputConfig(
                gcs_uri=output_uri)
        )

        # 4) バッチリクエストを組み立てる。
        #    name: Processorリソース
        #    input_documents: OCR対象PDF
        #    document_output_config: JSON出力先
        request = documentai.BatchProcessRequest(
            name=resource_name,
            input_documents=input_config,
            document_output_config=output_config,
        )

        logger.debug(
            "Document AI request prepared: processor=%s location=%s output_uri=%s",
            self.settings.processor_id,
            self.settings.processor_location,
            output_uri,
        )

        try:
            # 5) バッチ処理を投入する。
            #    呼び出し時間は「API受理まで」の時間であり、OCR完了時間ではない。
            started_at = time.perf_counter()
            operation = self.client.batch_process_documents(request=request)
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            logger.info(
                "Document AI batch accepted: operation=%s elapsed_ms=%d output_uri=%s",
                operation.operation.name,
                elapsed_ms,
                output_uri,
            )
            return operation.operation.name
        except Exception:
            # 失敗時は processor/input/output をまとめて記録し、上位へ再送出する。
            logger.exception(
                "Failed to submit Document AI batch: processor=%s location=%s input_uri=gs://%s/%s output_uri=%s",
                self.settings.processor_id,
                self.settings.processor_location,
                input_bucket,
                file_name,
                output_uri,
            )
            raise


@dataclass(frozen=True)
class Services:
    docai_service: DocumentAIService


def build_services(settings: Settings) -> Services:
    """entrypoint で使用するサービス群を構築して返す。"""
    # entrypoint から外部サービスを一括参照できるように束ねて返す。
    return Services(docai_service=DocumentAIService(settings))
