from __future__ import annotations

import logging
from dataclasses import dataclass

import vertexai
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
    """実GCS用の Storage アダプタ。"""

    def __init__(self, settings: Settings):
        self.client = storage.Client(project=settings.gcp_project_id)

    def download_bytes(self, bucket: str, name: str) -> bytes:
        blob = self.client.bucket(bucket).blob(name)
        return blob.download_as_bytes()

    def upload_text(self, bucket: str, name: str, text: str, content_type: str = MD_CONTENT_TYPE) -> None:
        blob = self.client.bucket(bucket).blob(name)
        blob.upload_from_string(text, content_type=content_type)


class GeminiClient:
    """Vertex AI Gemini クライアント（ローカルでもADCで実GCPへ）。"""

    def __init__(self, settings: Settings):
        vertexai.init(project=settings.gcp_project_id,
                      location=settings.gcp_location)
        self.model = GenerativeModel(settings.model_name)

    def to_markdown(self, ocr_text: str, sys_instruction: str = SYS_INSTRUCTION) -> str:
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
    return Services(
        storage=StorageClient(settings),
        gemini=GeminiClient(settings),
    )
