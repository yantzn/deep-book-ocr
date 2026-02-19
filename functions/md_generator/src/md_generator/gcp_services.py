from __future__ import annotations

"""md_generator の外部サービスアダプタ。

- StorageClient: OCR JSON と Markdown の入出力
- GeminiClient: OCRテキストを Markdown へ整形
"""

import logging
from dataclasses import dataclass
from typing import Optional

import vertexai
from google.auth.credentials import AnonymousCredentials
from google.cloud import storage
from vertexai.generative_models import GenerativeModel, Part

from .config import Settings

logger = logging.getLogger(__name__)


SYS_INSTRUCTION = (
    "You are an expert technical editor.\n"
    "Format the OCR text into clean, well-structured Markdown.\n"
    "- Detect source code and wrap in language-specific fenced code blocks.\n"
    "- Add headings and captions when context suggests.\n"
    "- Remove noise such as page numbers/headers/footers.\n"
    "- Correct common OCR errors based on technical terminology.\n"
)

MD_CONTENT_TYPE = "text/markdown"


class StorageClient:
    """
    接続先を切り替え可能な Storage アダプタ。
    - 実GCS（デフォルト）
    - fake-gcs-server（STORAGE_MODE=emulator の場合）
    """

    def __init__(self, settings: Settings):
        self._emulator = settings.use_emulator
        if settings.use_emulator:
            self.client = storage.Client(
                project="local",
                client_options={"api_endpoint": settings.gcs_emulator_host},
                credentials=AnonymousCredentials(),
            )
        else:
            self.client = storage.Client(project=settings.gcp_project_id)

    def _ensure_bucket(self, bucket_name: str) -> None:
        """エミュレータ利用時にバケットを必要に応じて作成する。"""
        b = self.client.bucket(bucket_name)
        if not b.exists():
            b.create()

    def download_bytes(self, bucket: str, name: str) -> bytes:
        """選択中のStorage接続先からオブジェクトを bytes で取得する。"""
        blob = self.client.bucket(bucket).blob(name)
        return blob.download_as_bytes()

    def upload_text(self, bucket: str, name: str, text: str, content_type: str = MD_CONTENT_TYPE) -> None:
        if self._emulator:
            self._ensure_bucket(bucket)
        blob = self.client.bucket(bucket).blob(name)
        blob.upload_from_string(text, content_type=content_type)


class GeminiClient:
    """
    Vertex AI Gemini クライアント。
    ローカル実行時でも常に実GCP（ADC）を利用する。
    """

    def __init__(self, settings: Settings):
        vertexai.init(project=settings.gcp_project_id,
                      location=settings.gcp_location)
        self.model = GenerativeModel(settings.model_name)

    def to_markdown(self, ocr_text: str, sys_instruction: str = SYS_INSTRUCTION) -> str:
        """OCRテキストを設定済みGeminiモデルで markdown に変換する。"""
        prompt = [
            Part.from_text(sys_instruction),
            Part.from_text("\n\n--- OCR TEXT ---\n"),
            Part.from_text(ocr_text),
        ]
        resp = self.model.generate_content(prompt, stream=False)
        return resp.text or ""


@dataclass(frozen=True)
class Services:
    storage: StorageClient
    gemini: GeminiClient


def build_services(settings: Settings) -> Services:
    """エントリポイントで使用する外部クライアント群を構築して返す。"""
    return Services(
        storage=StorageClient(settings),
        gemini=GeminiClient(settings),
    )
