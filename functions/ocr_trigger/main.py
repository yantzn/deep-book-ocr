import os
import functions_framework
from google.cloud import documentai_v1 as documentai

# 環境変数はデプロイ時に設定
PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "deep-book-ocr")
LOCATION = os.environ.get("PROCESSOR_LOCATION", "us")  # プロセッサの場所
PROCESSOR_ID = os.environ.get("PROCESSOR_ID")
TEMP_BUCKET = os.environ.get("TEMP_BUCKET")  # 例: gs://deep-book-ocr-temp

client = documentai.DocumentProcessorServiceClient()


@functions_framework.cloud_event
def start_ocr(cloud_event):
    data = cloud_event.data
    input_bucket = data["bucket"]
    file_name = data["name"]

    # PDFファイル以外は処理しない
    if not file_name.lower().endswith(".pdf"):
        print(f"Skipping non-PDF file: {file_name}")
        return

    # 1. プロセッサのリソース名を設定
    resource_name = client.processor_path(PROJECT_ID, LOCATION, PROCESSOR_ID)

    # 2. 入力ドキュメントの設定
    gcs_document = documentai.GcsDocument(
        gcs_uri=f"gs://{input_bucket}/{file_name}",
        mime_type="application/pdf"
    )
    input_config = documentai.BatchDocumentsInputConfig(
        gcs_documents=documentai.GcsDocuments(documents=[gcs_document])
    )

    # 3. 出力先（JSONが保存される場所）の設定
    # 元のファイル名に基づいたフォルダを作成して保存
    output_config = documentai.DocumentOutputConfig(
        gcs_output_config=documentai.GcsOutputConfig(
            gcs_uri=f"{TEMP_BUCKET}/{file_name}_json/"
        )
    )

    # 4. 非同期リクエストの送信
    request = documentai.BatchProcessRequest(
        name=resource_name,
        input_configs=input_config,
        output_config=output_config
    )

    operation = client.batch_process_documents(request=request)
    print(
        f"OCR Job started for {file_name}. Operation: {operation.operation.name}")
