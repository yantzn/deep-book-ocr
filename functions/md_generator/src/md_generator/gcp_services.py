from __future__ import annotations

"""
md_generator の GCP 連携層。

このモジュールの責務:
- GCS から OCR JSON を読み込む（StorageClient）
- Gemini へテキストを渡して Markdown 化する（GeminiClient）
- entrypoint へ両者をまとめて提供する（Services / build_services）

ビジネスロジック（ページ分割やJSON解析）は entrypoint / markdown_logic 側で扱い、
ここでは外部サービス呼び出しに集中する。
"""

import logging
import time
from dataclasses import dataclass

import vertexai
from google.cloud import storage
from vertexai.generative_models import GenerativeModel, Part

from .config import Settings

logger = logging.getLogger(__name__)

# md_generator の整形方針はこの命令文を単一ソースとして固定する。
# 運用上の再現性確保のため、実行時に外部入力で差し替えない。
SYS_INSTRUCTION = """
You are an expert editor converting OCR text from books into clean, faithful Markdown.

GOAL
- Reconstruct the original content as accurately as possible.
- Improve readability with Markdown structure without changing meaning.

STRICT RULES
- Do NOT summarize.
- Do NOT invent missing content.
- Preserve the original language of the source text.
- If the source text is Japanese, output must be Japanese.
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
- Do not translate unless the source text itself is translated.
"""

# charset を明示（ビューア/環境依存での文字化けを防ぐ）
MD_CONTENT_TYPE = "text/markdown; charset=utf-8"


class StorageClient:
    """実GCS用の Storage アダプタ。"""

    def __init__(self, settings: Settings):
        # project を明示しておくと、ADC複数設定時の誤接続を防ぎやすい
        self.client = storage.Client(project=settings.gcp_project_id)

    def download_bytes(self, bucket: str, name: str) -> bytes:
        """GCSオブジェクトを bytes として取得する。"""
        # 1) 対象オブジェクトを特定してダウンロードする。
        logger.debug("Downloading object: gs://%s/%s", bucket, name)
        blob = self.client.bucket(bucket).blob(name)
        data = blob.download_as_bytes()
        logger.debug("Downloaded bytes: gs://%s/%s size=%d",
                     bucket, name, len(data))
        return data

    def upload_text(
        self,
        bucket: str,
        name: str,
        text: str,
        content_type: str = MD_CONTENT_TYPE,
    ) -> None:
        """Markdown文字列を UTF-8 で GCS へ保存する。"""
        # 1) 出力先オブジェクトを特定する。
        logger.debug("Uploading markdown: gs://%s/%s content_type=%s chars=%d",
                     bucket, name, content_type, len(text))
        blob = self.client.bucket(bucket).blob(name)

        # 2) content_type を付与して UTF-8 バイト列として保存する。
        blob.upload_from_string(text.encode(
            "utf-8"), content_type=content_type)
        logger.debug("Upload completed: gs://%s/%s", bucket, name)

    def list_object_names(self, bucket: str, prefix: str) -> list[str]:
        """prefix 配下のオブジェクト名一覧を返す。"""
        logger.debug("Listing objects: gs://%s/%s", bucket, prefix)
        blobs = self.client.list_blobs(bucket_or_name=bucket, prefix=prefix)
        return [blob.name for blob in blobs]


class GeminiClient:
    """Vertex AI Gemini クライアント（ローカルでもADCで実GCPへ）。"""

    def __init__(self, settings: Settings):
        # 1) 実行先の project/location を初期化する。
        vertexai.init(project=settings.gcp_project_id,
                      location=settings.gcp_location)
        # 2) モデル名から Gemini クライアントを生成する。
        self.model = GenerativeModel(settings.model_name)
        logger.info("Gemini initialized: project=%s location=%s model=%s",
                    settings.gcp_project_id, settings.gcp_location, settings.model_name)

    def to_markdown(self, ocr_text: str) -> str:
        """
        OCRテキストを Gemini に渡して Markdown を生成する。

        入力:
        - ocr_text: Document AI から抽出した生テキスト

        出力:
        - 生成された Markdown 文字列（空の場合は ""）
        """
        # 1) 指示文 + OCR本文でプロンプトを構成する。
        logger.debug("Gemini request start: input_chars=%d", len(ocr_text))
        prompt = [
            Part.from_text(SYS_INSTRUCTION),
            Part.from_text("\n\n--- OCR TEXT ---\n"),
            Part.from_text(ocr_text),
        ]
        # 2) 同期呼び出しで Markdown を取得する。
        started_at = time.perf_counter()
        resp = self.model.generate_content(prompt, stream=False)
        # 3) 取得した本文を返す（空は空文字へ正規化）。
        output = resp.text or ""
        logger.debug("Gemini request done: output_chars=%d elapsed_ms=%d",
                     len(output), int((time.perf_counter() - started_at) * 1000))
        return output


@dataclass(frozen=True)
class Services:
    """entrypoint が利用する外部サービスの束。"""

    storage: StorageClient
    gemini: GeminiClient


def build_services(settings: Settings) -> Services:
    """設定をもとにサービス群を組み立てるファクトリ。"""
    # entrypoint から外部サービスを一括参照できるように束ねて返す。
    return Services(
        storage=StorageClient(settings),
        gemini=GeminiClient(settings),
    )
