from __future__ import annotations

import logging

from google.api_core.exceptions import DeadlineExceeded
from google.api_core.exceptions import GoogleAPICallError
from google.api_core.exceptions import RetryError
from google.cloud import documentai_v1 as documentai

from .config import Settings

logger = logging.getLogger(__name__)


class DocumentAIService:
    """Google Cloud Document AI を呼び出すサービス層。"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = documentai.DocumentProcessorServiceClient()

    def build_output_prefix(self, input_object_name: str) -> str:
        """
        Document AI の GCS 出力先は「ディレクトリURI」。
        例: gs://temp-bucket/uploads/a.pdf_json/
        """
        # object 名そのまま使うと / を含むので prefix 側も階層化される（意図通りならOK）
        return f"{self.settings.temp_bucket_uri()}{input_object_name}_json/"

    def start_ocr_batch_job(self, input_bucket: str, file_name: str) -> tuple[str, str]:
        """
        BatchProcess を起動して operation name を返す。
        NOTE:
        - ここで operation の完了待ちはしない（timeout/ブロック回避）
        - 完了や失敗は Document AI 側が実行し、結果は GCS（TEMP_BUCKET）に出る
        """
        logger.info("Starting OCR batch job. input=gs://%s/%s",
                    input_bucket, file_name)

        # PROCESSOR_ID は短縮ID/フルリソースどちらでも受けられるため、ここで短縮IDへ正規化する。
        processor_id = self.settings.processor_id_normalized()
        # Document AI API が要求する Processor の完全リソース名を組み立てる。
        processor_name = self.client.processor_path(
            self.settings.gcp_project_id,
            self.settings.processor_location,
            processor_id,
        )

        # ---- input ----
        gcs_document = documentai.GcsDocument(
            gcs_uri=f"gs://{input_bucket}/{file_name}",
            mime_type="application/pdf",
        )
        input_config = documentai.BatchDocumentsInputConfig(
            gcs_documents=documentai.GcsDocuments(documents=[gcs_document])
        )

        # ---- output ----
        # 出力先は「ファイル」ではなく prefix（ディレクトリ）指定。
        # Document AI 側で page/json など複数オブジェクトがこの配下に出力される。
        output_prefix = self.build_output_prefix(file_name)
        gcs_output_config = documentai.DocumentOutputConfig.GcsOutputConfig(
            gcs_uri=output_prefix
        )
        document_output_config = documentai.DocumentOutputConfig(
            gcs_output_config=gcs_output_config
        )

        request = documentai.BatchProcessRequest(
            name=processor_name,
            input_documents=input_config,
            document_output_config=document_output_config,
        )

        # Cloud Functions のリクエストを長時間占有しないため、
        # submit RPC 自体にも短い timeout をかける（処理完了待ちは別物）。
        submit_timeout_sec = max(
            1, int(self.settings.docai_submit_timeout_sec))
        logger.info(
            "Submitting Document AI batch request with timeout=%ss", submit_timeout_sec
        )

        try:
            operation = self.client.batch_process_documents(
                request=request,
                timeout=submit_timeout_sec,
            )
        except (DeadlineExceeded, RetryError) as exc:
            # ここは「submit 受付」段階のタイムアウト。
            # OCR本体の実行タイムアウトではない点に注意。
            logger.exception(
                "Document AI submit timed out after %ss. processor=%s input=gs://%s/%s output_prefix=%s",
                submit_timeout_sec,
                processor_name,
                input_bucket,
                file_name,
                output_prefix,
            )
            raise TimeoutError("Document AI submit timed out") from exc
        except GoogleAPICallError as exc:
            # 権限不足・無効な processor・API 側エラーなどをここで捕捉する。
            logger.exception(
                "Document AI API call failed. processor=%s input=gs://%s/%s output_prefix=%s error=%s",
                processor_name,
                input_bucket,
                file_name,
                output_prefix,
                exc,
            )
            raise

        # 返る operation 名を保持しておくと、後から運用ログで追跡しやすい。
        op_name = operation.operation.name
        logger.info("Submitted Document AI batch operation: %s", op_name)
        logger.info("Expected output prefix: %s", output_prefix)

        return op_name, output_prefix


class Services:
    def __init__(self, settings: Settings):
        self.docai_service = DocumentAIService(settings)


def build_services(settings: Settings) -> Services:
    return Services(settings)
