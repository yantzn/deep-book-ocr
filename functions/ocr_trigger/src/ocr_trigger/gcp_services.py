import logging
from google.cloud import documentai_v1 as documentai
from google.api_core.client_options import ClientOptions

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

    def submit_batch_process(self, bucket, name, output_prefix):
        # 入力PDFと出力先プレフィックスを DocAI batch 処理用の request に組み立てる。
        # ここでは submit のみを担当し、完了待ちは呼び出し側（Workflow）で行う。

        input_uri = f"gs://{bucket}/{name}"

        request = documentai.BatchProcessRequest(
            name=self.client.processor_path(
                self.settings.gcp_project_id,
                self.settings.processor_location,
                self.settings.processor_id,
            ),
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

        operation = self.client.batch_process_documents(request)

        # 非同期LROの operation name を返して、後続が状態監視できるようにする。
        return operation.operation.name
