from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
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
    # gs://bucket/prefix 形式を bucket と prefix に分解する。
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
        # Storage クライアントは設定済み project_id を使って生成する。
        self.settings = settings
        self.client = storage.Client(project=settings.gcp_project_id)

    def list_object_names(self, bucket_name: str, prefix: str) -> list[str]:
        # prefix 配下のオブジェクト名を列挙し、処理順を安定化するためソートして返す。
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
        # 一時的なAPIエラー/NotFound遅延を想定し、段階的バックオフで再試行する。
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
                # OCR直後は整合遅延で見えないことがあるため、規定回数までは再試行する。
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

    def _download_one_json(
        self,
        bucket_name: str,
        object_name: str,
    ) -> dict[str, Any]:
        # 1ファイル分のダウンロード + JSONパースを担当する最小単位処理。
        raw = self._download_text_with_retry(
            bucket_name=bucket_name,
            object_name=object_name,
            max_attempts=self.settings.gcs_download_max_attempts,
            base_sleep_sec=self.settings.gcs_download_base_sleep_sec,
        )
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"Invalid JSON content in gs://{bucket_name}/{object_name}: {e}"
            ) from e

    def download_json_documents_from_gs_uri_prefix(self, gs_uri_prefix: str) -> list[dict[str, Any]]:
        # prefix 配下の JSON を並列ダウンロードし、Document AI 断片を一括返却する。
        started = time.perf_counter()

        bucket_name, prefix = _parse_gs_uri(gs_uri_prefix)
        object_names = self.list_object_names(bucket_name, prefix)
        json_object_names = [
            name for name in object_names if name.endswith(".json")]

        if not json_object_names:
            return []

        worker_count = max(
            1,
            min(
                # 並列数は設定値と対象件数の小さい方を採用し、過剰並列を防ぐ。
                int(self.settings.gcs_parallel_download_workers),
                len(json_object_names),
            ),
        )

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            docs = list(
                executor.map(
                    lambda object_name: self._download_one_json(
                        bucket_name, object_name),
                    json_object_names,
                )
            )

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "Downloaded OCR JSON documents from GCS: bucket=%s prefix=%s json_count=%d workers=%d elapsed_ms=%d",
            bucket_name,
            prefix,
            len(docs),
            worker_count,
            elapsed_ms,
        )
        return docs

    def write_markdown(self, bucket_name: str, object_name: str, markdown: str) -> str:
        # 生成Markdownを text/markdown で保存し、後続で参照しやすい gs:// URI を返す。
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
        # セッション再利用により接続コストを削減する。
        self.settings = settings
        self._session = requests.Session()

    @dataclass(frozen=True)
    class _GeminiResponse:
        text: str
        latency_ms: int
        prompt_tokens: int | None
        response_tokens: int | None
        total_tokens: int | None

    def _generate_via_gemini_api(self, prompt: str) -> _GeminiResponse:
        # APIキー未設定時は呼び出しをスキップし、上位でドラフトをそのまま使わせる。
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
            # 生成は「ユーザー入力1件」を前提とした最小構成。
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                # 再現性重視のため低温度で出力揺れを抑える。
                "temperature": 0.2,
            },
        }

        max_attempts = max(1, int(self.settings.gemini_request_max_attempts))
        base_sleep_sec = max(0.0, float(
            self.settings.gemini_retry_base_sleep_sec))
        connect_timeout_sec = max(0.1, float(
            self.settings.gemini_connect_timeout_sec))
        read_timeout_sec = max(0.1, float(
            self.settings.gemini_read_timeout_sec))

        started = time.perf_counter()
        response: requests.Response | None = None
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                # connect/read を分離して timeout を明示管理する。
                response = self._session.post(
                    endpoint,
                    headers={
                        "Content-Type": "application/json",
                        "x-goog-api-key": self.settings.gemini_api_key,
                    },
                    json=payload,
                    timeout=(connect_timeout_sec, read_timeout_sec),
                )
                response.raise_for_status()
                last_error = None
                break
            except requests.HTTPError as e:
                last_error = e
                status_code = getattr(e.response, "status_code", None)
                # 5xx は一時障害として再試行、4xx は基本的に即失敗。
                is_retryable = status_code is not None and status_code >= 500

                if attempt >= max_attempts or not is_retryable:
                    body = ""
                    if e.response is not None:
                        body = e.response.text[:500]
                    latency_ms = int((time.perf_counter() - started) * 1000)
                    raise RuntimeError(
                        "Gemini API request failed: "
                        f"status={getattr(e.response, 'status_code', 'unknown')} "
                        f"latency_ms={latency_ms} body={body}"
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
        # Gemini の候補レスポンスから text パーツのみを連結する。
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
        # Gemini 入力上限を守るため、段落優先でチャンク分割する。
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
                current_parts.append(para)
                current_chars = next_len
                continue

            flush_current()

            if para_len <= max_chars:
                current_parts.append(para)
                current_chars = para_len
                continue

            # 単一段落が上限超過する場合は機械的にスライス分割する。
            for i in range(0, para_len, max_chars):
                piece = para[i: i + max_chars].strip()
                if piece:
                    chunks.append(piece)

        flush_current()
        return chunks or [markdown[:max_chars]]

    def polish_markdown(self, draft_markdown: str) -> str:
        # チャンク単位でGemini整形し、失敗チャンクはドラフトを採用して処理継続する。
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
- Preserve code and symbols exactly when possible.
- For tables, use Markdown tables if clearly tabular; otherwise keep as preformatted text.

SELF-DEVELOPMENT / NONFICTION HANDLING
- Preserve quotes and emphasized sentences.
- If the author clearly highlights a key takeaway, keep it prominent using bold or blockquotes.
- Do not add interpretations or commentary.

OUTPUT
- Output valid Markdown only.
- No additional explanations outside the Markdown.
- Do not translate unless the source text itself is translated.

OCR TEXT:
{chunk}
""".strip()

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
                    chunk_failed = True
                    failures += 1
                    polished_chunk = chunk
            except RuntimeError as e:
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

        combined = "\n\n".join(part.strip()
                               for part in chunk_outputs if part.strip()).strip()

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
            # 全チャンク空応答の場合は内容消失を避けるためドラフトを返す。
            logger.warning(
                "Gemini returned empty text across all chunks; using draft markdown")
            return draft_markdown

        return combined


@dataclass(frozen=True)
class Services:
    storage_service: StorageService
    llm_service: LLMService


def build_services(settings: Settings) -> Services:
    # main.py から利用する依存を束ねて返す。
    return Services(
        storage_service=StorageService(settings),
        llm_service=LLMService(settings),
    )
