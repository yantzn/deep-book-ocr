"""
Cloud Function: generate_markdown

処理フロー:
1. GCS finalize イベントで OCR JSON を受信
2. JSON からページ単位テキストを抽出してチャンク化
3. Vertex AI Gemini で Markdown へ整形
4. Markdown を出力バケットへ保存

設計メモ:
- 設定は env/.env に集約
- Storage は STORAGE_MODE で real GCS / emulator を切替
- Vertex AI はローカルでも常に real GCP(ADC) を利用
- APP_ENV=gcp の場合のみ Cloud Logging を有効化
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import functions_framework
import vertexai
from google.auth.credentials import AnonymousCredentials
from google.cloud import logging as cloud_logging
from google.cloud import storage
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from vertexai.generative_models import GenerativeModel, Part

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """md_generator の実行時設定（環境変数ベース）。"""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(default="local", alias="APP_ENV")  # 実行環境: local | gcp
    storage_mode: str = Field(
        default="gcp", alias="STORAGE_MODE")  # Storage接続先: emulator | gcp

    project_id: str = Field(..., alias="GCP_PROJECT_ID")
    location: str = Field(default="us-central1", alias="GCP_LOCATION")

    output_bucket: str = Field(..., alias="OUTPUT_BUCKET")

    # エミュレータ設定
    gcs_emulator_host: str = Field(
        default="http://localhost:4443", alias="GCS_EMULATOR_HOST")
    emulator_input_bucket: str = Field(
        default="temp-local", alias="EMULATOR_INPUT_BUCKET")
    emulator_output_bucket: str = Field(
        default="output-local", alias="EMULATOR_OUTPUT_BUCKET")

    # モデル設定
    model_name: str = Field(default="gemini-1.5-pro", alias="MODEL_NAME")
    chunk_size: int = Field(default=10, alias="CHUNK_SIZE")

    @property
    def is_gcp(self) -> bool:
        return self.app_env.lower() == "gcp"

    @property
    def use_emulator(self) -> bool:
        return self.storage_mode.lower() == "emulator"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def setup_logging(settings: Settings) -> None:
    # local: 標準logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # gcp: Cloud Logging
    if settings.is_gcp:
        try:
            cloud_logging.Client().setup_logging()
            logger.info("Cloud Logging initialized")
        except Exception:
            # ログ初期化に失敗しても関数は停止させない
            logger.exception("Failed to initialize Cloud Logging")


class StorageAdapter:
    """
    接続先を切り替え可能な Storage クライアントアダプタ。
    - 実GCS（デフォルト）
    - fake-gcs-server（STORAGE_MODE=emulator の場合）
    """

    def __init__(self, *, settings: Settings):
        if settings.use_emulator:
            self.client = storage.Client(
                project="local",
                client_options={"api_endpoint": settings.gcs_emulator_host},
                credentials=AnonymousCredentials(),
            )
            self._emulator = True
        else:
            self.client = storage.Client(project=settings.project_id)
            self._emulator = False

    def _ensure_bucket(self, bucket_name: str) -> None:
        b = self.client.bucket(bucket_name)
        if not b.exists():
            b.create()

    def download_bytes(self, bucket: str, name: str) -> bytes:
        """指定オブジェクトの内容を bytes で取得する。"""
        blob = self.client.bucket(bucket).blob(name)
        return blob.download_as_bytes()

    def upload_text(self, bucket: str, name: str, text: str, content_type: str) -> None:
        if self._emulator:
            self._ensure_bucket(bucket)
        blob = self.client.bucket(bucket).blob(name)
        blob.upload_from_string(text, content_type=content_type)


def init_vertex(settings: Settings) -> GenerativeModel:
    """
    Vertex AI はローカル実行時でも常に実GCP（ADC）を利用する。
    """
    vertexai.init(project=settings.project_id, location=settings.location)
    return GenerativeModel(settings.model_name)


SYS_INSTRUCTION = (
    "You are an expert technical editor.\n"
    "Your task is to format the following OCR text into clean, well-structured Markdown.\n"
    "- Identify source code and wrap it in appropriate language-specific (e.g., python, shell) code blocks (```).\n"
    "- Infer and apply headings (#, ##, etc.) and figure captions from the context.\n"
    "- Remove extraneous noise such as page numbers, headers, and footers.\n"
    "- Correct common OCR errors (e.g., 'l' vs '1', 'O' vs '0') based on technical terminology."
)

OUTPUT_CONTENT_TYPE = "text/markdown"


def extract_text_from_page_range(doc_ai_json: Dict[str, Any], start_page: int, end_page: int) -> str:
    """ページ範囲 [start_page, end_page) の連結テキストを抽出する。"""
    full_text = doc_ai_json.get("text", "")
    pages = doc_ai_json.get("pages", [])

    start_page = max(0, start_page)
    end_page = min(len(pages), end_page)

    segments: List[str] = []
    for i in range(start_page, end_page):
        page = pages[i]
        text_anchor = page.get("layout", {}).get("textAnchor", {})
        for seg in text_anchor.get("textSegments", []):
            s = int(seg.get("startIndex", 0) or 0)
            e = int(seg.get("endIndex", 0) or 0)
            if e > s:
                segments.append(full_text[s:e])

    return "".join(segments)


def generate_markdown(model: GenerativeModel, text_chunks: List[str]) -> str:
    """OCRテキストの各チャンクを markdown 化し、結合して返す。"""
    md_results: List[str] = []
    total = len(text_chunks)

    for i, chunk in enumerate(text_chunks):
        if not chunk.strip():
            continue

        logger.info("Processing chunk %d/%d", i + 1, total)
        prompt = [
            Part.from_text(SYS_INSTRUCTION),
            Part.from_text("\n\n--- OCR TEXT ---\n"),
            Part.from_text(chunk),
        ]
        try:
            resp = model.generate_content(prompt, stream=False)
            md_results.append(resp.text or "")
        except Exception as e:
            logger.exception("Model generation failed for chunk %d", i + 1)
            md_results.append(
                f"\n> [Error processing chunk {i + 1} of {total}: {e}]\n")

    return "\n\n".join(md_results)


# ---- グローバル初期化（呼び出し間でクライアントを再利用） ----
_settings = get_settings()
setup_logging(_settings)

_storage = StorageAdapter(settings=_settings)

# 「model=None」で継続するより、初期化失敗時に即時検知できるようにする
_model = init_vertex(_settings)


@functions_framework.cloud_event
def generate_markdown_entrypoint(cloud_event: Any) -> Optional[str]:
    """
    Cloud Function のエントリポイント。

    処理ステップ:
    1. イベントから入力 JSON オブジェクトを特定
    2. OCR JSON を取得してページチャンクへ分割
    3. 各チャンクを Gemini で Markdown 化
    4. 生成 Markdown を出力バケットへ保存
    """
    data = cloud_event.data
    bucket_name = data.get("bucket")
    file_name = data.get("name")

    if not file_name or not file_name.endswith(".json"):
        logger.info("Skipping non-JSON file: %s", file_name)
        return None

    logger.info("Processing file: gs://%s/%s", bucket_name, file_name)

    # local+emulator: イベントのbucketではなくエミュレータの入力バケットを使う
    in_bucket = _settings.emulator_input_bucket if _settings.use_emulator else bucket_name
    out_bucket = _settings.emulator_output_bucket if _settings.use_emulator else _settings.output_bucket

    try:
        raw = _storage.download_bytes(in_bucket, file_name)
        json_data = json.loads(raw)
    except Exception:
        logger.exception(
            "Failed to download or parse JSON: bucket=%s name=%s", in_bucket, file_name)
        return "ERROR: download/parse failed"

    total_pages = len(json_data.get("pages", []))
    if total_pages == 0:
        logger.warning("No pages found in %s. Aborting.", file_name)
        return None

    chunks = [
        extract_text_from_page_range(json_data, i, i + _settings.chunk_size)
        for i in range(0, total_pages, _settings.chunk_size)
    ]

    final_md = generate_markdown(_model, chunks)

    # 入力形式の例: 'processed/my-book_pdf/0.json' -> 'my-book.md'
    p = Path(file_name)
    base_name = p.parent.name.removesuffix("_pdf")
    output_filename = f"{base_name}.md"

    try:
        _storage.upload_text(out_bucket, output_filename,
                             final_md, OUTPUT_CONTENT_TYPE)
        logger.info("Uploaded Markdown: gs://%s/%s",
                    out_bucket, output_filename)
        return "SUCCESS"
    except Exception:
        logger.exception(
            "Failed to upload Markdown: bucket=%s name=%s", out_bucket, output_filename)
        return "ERROR: upload failed"
