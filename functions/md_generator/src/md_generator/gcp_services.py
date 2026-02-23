from __future__ import annotations

import logging
from dataclasses import dataclass

import vertexai
from google.cloud import storage
from vertexai.generative_models import GenerativeModel, Part

from .config import Settings

logger = logging.getLogger(__name__)

SYS_INSTRUCTION = """
You are an expert editor converting OCR text from books into clean, faithful Markdown.

GOAL
- Reconstruct the original content as accurately as possible.
- Improve readability with Markdown structure without changing meaning.

STRICT RULES
- Do NOT summarize.
- Do NOT invent missing content.
- Keep the original language (Japanese stays Japanese).
- Fix OCR errors only when the correction is obvious and certain.
- If uncertain, keep the original text as-is.

CLEANUP
- Remove repeated noise such as page numbers, running headers, footers, and watermarks.
- If the same line repeats across pages, keep it only once.

STRUCTURE
- Use headings (#, ##, ###) only when the section structure is clear from the text.
- Preserve paragraph breaks; do not merge unrelated paragraphs.
- Preserve lists (bullets/numbering) and indentation.

TECHNICAL BOOK HANDLING
- Detect code, CLI commands, config files, and logs; wrap them in fenced code blocks.
- Infer the most likely language for the fence (e.g., python, bash, json, yaml, sql, text).
- Preserve code and symbols exactly when possible (punctuation, brackets, quotes, backticks).
- For tables, use Markdown tables if clearly tabular; otherwise keep as preformatted text.

SELF-DEVELOPMENT / NONFICTION HANDLING
- Preserve quotes and emphasized sentences.
- If the author clearly highlights a “key takeaway”, keep it prominent using bold or blockquotes.
- Do not add interpretations or commentary.

OUTPUT
- Output valid Markdown only.
- No additional explanations outside the Markdown.
"""

# ✅ charset を明示（ビューア/環境依存での文字化けを防ぐ）
MD_CONTENT_TYPE = "text/markdown; charset=utf-8"


class StorageClient:
    """実GCS用の Storage アダプタ。"""

    def __init__(self, settings: Settings):
        self.client = storage.Client(project=settings.gcp_project_id)

    def download_bytes(self, bucket: str, name: str) -> bytes:
        blob = self.client.bucket(bucket).blob(name)
        return blob.download_as_bytes()

    def upload_text(
        self,
        bucket: str,
        name: str,
        text: str,
        content_type: str = MD_CONTENT_TYPE,
    ) -> None:
        blob = self.client.bucket(bucket).blob(name)

        # ✅ 明示的にUTF-8でアップロード（content-typeと合わせて事故を防ぐ）
        blob.upload_from_string(text.encode(
            "utf-8"), content_type=content_type)


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
