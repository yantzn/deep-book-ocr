from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from google.api_core.exceptions import Forbidden, GoogleAPICallError, NotFound
from google.cloud import storage
from vertexai import init as vertexai_init
from vertexai.generative_models import GenerativeModel

from .config import Settings

logger = logging.getLogger(__name__)


def _parse_gs_uri(gs_uri: str) -> tuple[str, str]:
    if not gs_uri.startswith("gs://"):
        raise ValueError(f"Invalid gs:// URI: {gs_uri}")

    parsed = urlparse(gs_uri)
    bucket = parsed.netloc
    prefix = parsed.path.lstrip("/")
    if not bucket:
        raise ValueError(f"Invalid gs:// URI (missing bucket): {gs_uri}")
    return bucket, prefix


class StorageService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = storage.Client(project=settings.gcp_project_id)

    def list_object_names(self, bucket_name: str, prefix: str) -> list[str]:
        started = time.perf_counter()
        blobs = self.client.list_blobs(
            bucket_or_name=bucket_name, prefix=prefix)
        names = sorted(blob.name for blob in blobs)
        logger.info(
            "Listed objects from GCS: bucket=%s prefix=%s object_count=%d elapsed_ms=%d",
            bucket_name,
            prefix,
            len(names),
            int((time.perf_counter() - started) * 1000),
        )
        return names

    def list_object_names_from_gs_uri(self, gs_uri_prefix: str) -> list[str]:
        bucket, prefix = _parse_gs_uri(gs_uri_prefix)
        return self.list_object_names(bucket_name=bucket, prefix=prefix)

    def _download_text_with_retry(
        self,
        bucket_name: str,
        object_name: str,
        *,
        max_attempts: int,
        base_sleep_sec: float,
    ) -> str:
        bucket = self.client.bucket(bucket_name)
        blob = bucket.blob(object_name)

        for attempt in range(1, max_attempts + 1):
            try:
                return blob.download_as_text(
                    encoding="utf-8",
                    timeout=self.settings.gcs_download_timeout_sec,
                )
            except Forbidden as e:
                raise RuntimeError(
                    f"GCS object download forbidden: gs://{bucket_name}/{object_name}"
                ) from e
            except NotFound as e:
                if attempt >= max_attempts:
                    raise RuntimeError(
                        f"GCS object not found after retries: gs://{bucket_name}/{object_name}"
                    ) from e
                time.sleep(base_sleep_sec * attempt)
            except GoogleAPICallError as e:
                if attempt >= max_attempts:
                    raise RuntimeError(
                        f"GCS API error while downloading gs://{bucket_name}/{object_name}: {e!r}"
                    ) from e
                time.sleep(base_sleep_sec * attempt)

        raise RuntimeError(
            f"GCS object download failed after retries: gs://{bucket_name}/{object_name}"
        )

    def download_json_documents_from_gs_uri_prefix(self, gs_uri_prefix: str) -> list[dict[str, Any]]:
        bucket_name, prefix = _parse_gs_uri(gs_uri_prefix)
        object_names = self.list_object_names(bucket_name, prefix)
        json_object_names = [
            name for name in object_names if name.endswith(".json")]

        docs: list[dict[str, Any]] = []
        for object_name in json_object_names:
            raw = self._download_text_with_retry(
                bucket_name=bucket_name,
                object_name=object_name,
                max_attempts=self.settings.gcs_download_max_attempts,
                base_sleep_sec=self.settings.gcs_download_base_sleep_sec,
            )
            try:
                docs.append(json.loads(raw))
            except json.JSONDecodeError as e:
                raise RuntimeError(
                    f"Invalid JSON content in gs://{bucket_name}/{object_name}: {e}"
                ) from e

        return docs

    def write_markdown(self, bucket_name: str, object_name: str, markdown: str) -> str:
        bucket = self.client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        blob.upload_from_string(
            markdown,
            content_type="text/markdown; charset=utf-8",
            timeout=self.settings.gcs_upload_timeout_sec,
        )
        return f"gs://{bucket_name}/{object_name}"

    def object_exists(self, bucket_name: str, object_name: str) -> bool:
        blob = self.client.bucket(bucket_name).blob(object_name)
        return blob.exists(timeout=self.settings.gcs_exists_timeout_sec)


class LLMService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._model: GenerativeModel | None = None

    def _get_model(self) -> GenerativeModel:
        if self._model is None:
            vertexai_init(
                project=self.settings.gcp_project_id,
                location=self.settings.gcp_location,
            )
            self._model = GenerativeModel(self.settings.gemini_model_name)
        return self._model

    def polish_markdown(self, draft_markdown: str) -> str:
        prompt = f"""
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

OCR TEXT:
{draft_markdown[: self.settings.gemini_max_input_chars]}
"""
        response = self._get_model().generate_content(
            prompt,
            request_options={"timeout": self.settings.gemini_timeout_sec},
        )
        text = getattr(response, "text", "") or ""
        polished = text.strip()
        if not polished:
            logger.warning("Gemini returned empty text; using draft markdown")
            return draft_markdown
        return polished


@dataclass(frozen=True)
class Services:
    # エントリーポイント側が依存を1つの束として受け取れるようにする。
    storage_service: StorageService
    llm_service: LLMService


def build_services(settings: Settings) -> Services:
    """利用する外部サービス依存を組み立てて返す。"""
    # 外部サービス依存の生成を1箇所に集約し、テスト時の差し替えを容易にする。
    return Services(
        storage_service=StorageService(settings),
        llm_service=LLMService(settings),
    )
