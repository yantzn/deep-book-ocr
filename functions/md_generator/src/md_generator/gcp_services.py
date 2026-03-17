from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests
from google.api_core.exceptions import Forbidden, GoogleAPICallError, NotFound
from google.cloud import storage

from .config import Settings
from .observability import log_pipeline_event

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
        self._session = requests.Session()

    @dataclass(frozen=True)
    class _GeminiResponse:
        # Gemini API応答から、後段の観測ログで使う値のみ抽出した中間表現。
        text: str
        latency_ms: int
        prompt_tokens: int | None
        response_tokens: int | None
        total_tokens: int | None

    def _generate_via_gemini_api(self, prompt: str) -> _GeminiResponse:
        """Gemini APIへ1回リクエストし、本文と使用量メタデータを返す。"""
        if not self.settings.gemini_api_key.strip():
            logger.warning("GEMINI_API_KEY is not set; using draft markdown")
            return self._GeminiResponse(
                text="",
                latency_ms=0,
                prompt_tokens=None,
                response_tokens=None,
                total_tokens=None,
            )

        endpoint = (
            f"{self.settings.gemini_api_base_url.rstrip('/')}"
            f"/models/{self.settings.gemini_model_name}:generateContent"
        )
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
            },
        }

        max_attempts = max(1, int(self.settings.gemini_request_max_attempts))
        base_sleep_sec = max(0.0, float(
            self.settings.gemini_retry_base_sleep_sec))
        started = time.perf_counter()
        response: requests.Response | None = None
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                response = self._session.post(
                    endpoint,
                    headers={
                        "Content-Type": "application/json",
                        "x-goog-api-key": self.settings.gemini_api_key,
                    },
                    json=payload,
                    timeout=self.settings.gemini_timeout_sec,
                )
                response.raise_for_status()
                last_error = None
                break
            except requests.HTTPError as e:
                last_error = e
                status_code = getattr(e.response, "status_code", None)
                is_retryable = status_code is not None and status_code >= 500
                if attempt >= max_attempts or not is_retryable:
                    body = ""
                    if e.response is not None:
                        body = e.response.text[:500]
                    latency_ms = int((time.perf_counter() - started) * 1000)
                    raise RuntimeError(
                        f"Gemini API request failed: status={getattr(e.response, 'status_code', 'unknown')} latency_ms={latency_ms} body={body}"
                    ) from e
                sleep_sec = base_sleep_sec * attempt
                logger.warning(
                    "Gemini HTTP error (retrying): attempt=%d/%d status=%s sleep_sec=%.2f",
                    attempt,
                    max_attempts,
                    status_code,
                    sleep_sec,
                )
                time.sleep(sleep_sec)
            except requests.RequestException as e:
                last_error = e
                if attempt >= max_attempts:
                    latency_ms = int((time.perf_counter() - started) * 1000)
                    raise RuntimeError(
                        f"Gemini API request failed: latency_ms={latency_ms} error={e!r}"
                    ) from e
                sleep_sec = base_sleep_sec * attempt
                logger.warning(
                    "Gemini request exception (retrying): attempt=%d/%d sleep_sec=%.2f error=%r",
                    attempt,
                    max_attempts,
                    sleep_sec,
                    e,
                )
                time.sleep(sleep_sec)

        if response is None:
            latency_ms = int((time.perf_counter() - started) * 1000)
            raise RuntimeError(
                f"Gemini API request failed: latency_ms={latency_ms} error={last_error!r}"
            )

        data = response.json()
        candidates = data.get("candidates") or []
        texts: list[str] = []
        for candidate in candidates:
            content = candidate.get("content") or {}
            for part in content.get("parts") or []:
                text = part.get("text")
                if text:
                    texts.append(text)

        usage = data.get("usageMetadata") or {}
        return self._GeminiResponse(
            text="\n".join(texts).strip(),
            latency_ms=int((time.perf_counter() - started) * 1000),
            prompt_tokens=usage.get("promptTokenCount"),
            response_tokens=usage.get("candidatesTokenCount"),
            total_tokens=usage.get("totalTokenCount"),
        )

    def _split_markdown_chunks(self, markdown: str) -> list[str]:
        """Markdownを段落優先で分割し、チャンク上限文字数内へ収める。"""
        max_chars = max(1, int(self.settings.gemini_max_input_chars))
        paragraphs = markdown.split("\n\n")

        chunks: list[str] = []
        current_parts: list[str] = []
        current_chars = 0

        def flush_current() -> None:
            nonlocal current_parts, current_chars
            if current_parts:
                chunks.append("\n\n".join(current_parts).strip())
                current_parts = []
                current_chars = 0

        for paragraph in paragraphs:
            para = paragraph.strip()
            if not para:
                continue

            para_len = len(para)
            separator = 2 if current_parts else 0
            next_len = current_chars + separator + para_len

            if next_len <= max_chars:
                # 現在のチャンクに段落を追加できる場合はそのまま積む。
                current_parts.append(para)
                current_chars = next_len
                continue

            flush_current()

            if para_len <= max_chars:
                # 現在チャンクを確定後、段落を次チャンクの先頭として採用する。
                current_parts.append(para)
                current_chars = para_len
                continue

            # 単一段落が上限超過するケースのみ、段落内で強制スライスする。
            for i in range(0, para_len, max_chars):
                piece = para[i:i + max_chars].strip()
                if piece:
                    chunks.append(piece)

        flush_current()
        return chunks or [markdown[:max_chars]]

    def polish_markdown(self, draft_markdown: str) -> str:
        """下書きMarkdownをチャンク単位でGemini整形し、結合して返す。"""
        # 長文タイムアウト回避のため、まず入力をチャンクへ分割する。
        chunks = self._split_markdown_chunks(draft_markdown)
        chunk_outputs: list[str] = []
        failures = 0

        for chunk_index, chunk in enumerate(chunks, start=1):
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
{chunk}
"""
            chunk_failed = False
            prompt_tokens: int | None = None
            response_tokens: int | None = None
            total_tokens: int | None = None
            latency_ms = 0

            try:
                result = self._generate_via_gemini_api(prompt)
                polished_chunk = result.text.strip()
                latency_ms = result.latency_ms
                prompt_tokens = result.prompt_tokens
                response_tokens = result.response_tokens
                total_tokens = result.total_tokens
                if not polished_chunk:
                    # 空応答は失敗扱いにし、元チャンクを採用して欠落を防ぐ。
                    chunk_failed = True
                    failures += 1
                    polished_chunk = chunk
            except RuntimeError as e:
                # APIエラー時も同様にフォールバックし、パイプラインを継続する。
                chunk_failed = True
                failures += 1
                polished_chunk = chunk
                logger.warning(
                    "Gemini chunk failed; using draft chunk: chunk=%d/%d error=%s",
                    chunk_index,
                    len(chunks),
                    e,
                )

            fail_rate = failures / chunk_index
            # チャンク粒度で遅延・トークン・失敗率を記録し、運用で調整可能にする。
            log_pipeline_event(
                logger,
                level=logging.INFO,
                event="gemini_polish_chunk",
                stage="processed",
                chunk_index=chunk_index,
                chunk_count=len(chunks),
                chunk_input_chars=len(chunk),
                chunk_output_chars=len(polished_chunk),
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                response_tokens=response_tokens,
                total_tokens=total_tokens,
                chunk_failed=chunk_failed,
                fail_rate=round(fail_rate, 4),
            )
            chunk_outputs.append(polished_chunk)

        # チャンク順に再結合し、文書全体の最終Markdownを組み立てる。
        combined = "\n\n".join(part.strip()
                               for part in chunk_outputs if part.strip()).strip()
        # 最終サマリを1件出力し、処理全体の成功率を追跡しやすくする。
        log_pipeline_event(
            logger,
            level=logging.INFO,
            event="gemini_polish_summary",
            stage="completed",
            chunk_count=len(chunks),
            failed_chunks=failures,
            fail_rate=round(failures / len(chunks), 4),
            input_chars=len(draft_markdown),
            output_chars=len(combined) if combined else len(draft_markdown),
        )

        if not combined:
            logger.warning(
                "Gemini returned empty text across all chunks; using draft markdown")
            return draft_markdown
        return combined


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
