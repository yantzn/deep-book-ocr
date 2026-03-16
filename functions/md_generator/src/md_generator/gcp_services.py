from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from google.api_core.exceptions import Forbidden, GoogleAPICallError, NotFound
from google.cloud import storage
from vertexai import init as vertexai_init
from vertexai.generative_models import GenerativeModel

from .config import Settings

logger = logging.getLogger(__name__)


def _parse_gs_uri(gs_uri: str) -> tuple[str, str]:
    """`gs://...` 形式のURIを (bucket, prefix) に分解する。"""
    # `gs://bucket/prefix...` を (bucket, prefix) へ分解する共通ヘルパ。
    # Storage API 呼び出し前に形式不正を早期検知する。
    if not gs_uri.startswith("gs://"):
        raise ValueError(f"Invalid gs:// URI: {gs_uri}")

    parsed = urlparse(gs_uri)
    bucket = parsed.netloc
    prefix = parsed.path.lstrip("/")
    return bucket, prefix


class StorageService:
    def __init__(self, settings: Settings):
        """GCS 読み書き機能を提供するサービス。"""
        self.settings = settings
        # すべての GCS 操作を同一 project コンテキストで実行する。
        self.client = storage.Client(project=settings.gcp_project_id)

    def list_object_names(self, bucket_name: str, prefix: str) -> list[str]:
        """指定プレフィックス配下のオブジェクト名一覧をソートして返す。"""
        # OCR 出力 JSON はページ順の処理が重要なため、呼び出し側で
        # 安定して扱えるよう名前順ソートで返す。
        logger.info(
            "Listing objects from GCS: bucket=%s prefix=%s",
            bucket_name,
            prefix,
        )
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
        """`gs://bucket/prefix` を受け取り、オブジェクト名一覧を返す。"""
        bucket, prefix = _parse_gs_uri(gs_uri_prefix)
        return self.list_object_names(bucket_name=bucket, prefix=prefix)

    def _download_text_with_retry(
        self,
        bucket_name: str,
        object_name: str,
        *,
        max_attempts: int = 3,
        base_sleep_sec: float = 1.0,
    ) -> str:
        """GCSテキストをリトライ付きで取得し、文字列として返す。"""
        bucket = self.client.bucket(bucket_name)
        blob = bucket.blob(object_name)

        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(
                    "Downloading object from GCS: bucket=%s object=%s attempt=%d/%d",
                    bucket_name,
                    object_name,
                    attempt,
                    max_attempts,
                )
                started = time.perf_counter()
                raw = blob.download_as_text(encoding="utf-8")
                logger.info(
                    "Downloaded object from GCS: bucket=%s object=%s chars=%d elapsed_ms=%d",
                    bucket_name,
                    object_name,
                    len(raw),
                    int((time.perf_counter() - started) * 1000),
                )
                return raw

            except Forbidden as e:
                # IAM 不足は再試行しても改善しない可能性が高いので即失敗
                raise RuntimeError(
                    f"GCS object download forbidden: gs://{bucket_name}/{object_name}. "
                    "Check storage.objects.get permission for the runtime service account."
                ) from e

            except NotFound as e:
                # 一時的な一覧反映遅延の可能性があるため数回だけ retry
                if attempt >= max_attempts:
                    raise RuntimeError(
                        f"GCS object not found after retries: gs://{bucket_name}/{object_name}"
                    ) from e

                sleep_sec = base_sleep_sec * attempt
                logger.warning(
                    "GCS object not found; retrying: bucket=%s object=%s attempt=%d/%d sleep_sec=%.1f",
                    bucket_name,
                    object_name,
                    attempt,
                    max_attempts,
                    sleep_sec,
                )
                time.sleep(sleep_sec)

            except GoogleAPICallError as e:
                if attempt >= max_attempts:
                    raise RuntimeError(
                        f"GCS API error while downloading gs://{bucket_name}/{object_name}: {e!r}"
                    ) from e

                sleep_sec = base_sleep_sec * attempt
                logger.warning(
                    "Transient GCS API error; retrying: bucket=%s object=%s attempt=%d/%d sleep_sec=%.1f error=%r",
                    bucket_name,
                    object_name,
                    attempt,
                    max_attempts,
                    sleep_sec,
                    e,
                )
                time.sleep(sleep_sec)

    def download_json_documents_from_gs_uri_prefix(self, gs_uri_prefix: str) -> list[dict]:
        """DocAI 出力プレフィックス配下の JSON ドキュメント群を読み込む。"""
        # DocAI の出力プレフィックス配下から JSON のみを読み込む。
        # メタファイル等が混在しても `.json` 以外は無視する。
        bucket_name, prefix = _parse_gs_uri(gs_uri_prefix)
        object_names = self.list_object_names(bucket_name, prefix)

        json_object_names = [
            name for name in object_names if name.endswith(".json")]
        logger.info(
            "Preparing JSON downloads from GCS prefix: bucket=%s prefix=%s json_count=%d",
            bucket_name,
            prefix,
            len(json_object_names),
        )

        docs: list[dict] = []
        for object_name in json_object_names:
            # 1ファイルずつ取得して JSON としてパースし、順序を保って積み上げる。
            raw = self._download_text_with_retry(
                bucket_name=bucket_name,
                object_name=object_name,
            )
            try:
                docs.append(json.loads(raw))
            except json.JSONDecodeError as e:
                raise RuntimeError(
                    f"Invalid JSON content in gs://{bucket_name}/{object_name}: {e}"
                ) from e

        logger.info(
            "Completed JSON downloads from GCS prefix: bucket=%s prefix=%s loaded_docs=%d",
            bucket_name,
            prefix,
            len(docs),
        )
        return docs

    def write_markdown(self, bucket_name: str, object_name: str, markdown: str) -> str:
        """Markdown を GCS へ保存し、保存先 `gs://` URI を返す。"""
        # 最終成果物を UTF-8 Markdown として保存し、追跡用に gs:// URI を返す。
        logger.info(
            "Uploading markdown to GCS: bucket=%s object=%s chars=%d",
            bucket_name,
            object_name,
            len(markdown),
        )
        started = time.perf_counter()
        bucket = self.client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        blob.upload_from_string(
            markdown,
            content_type="text/markdown; charset=utf-8",
        )
        logger.info(
            "Uploaded markdown to GCS: bucket=%s object=%s elapsed_ms=%d",
            bucket_name,
            object_name,
            int((time.perf_counter() - started) * 1000),
        )
        return f"gs://{bucket_name}/{object_name}"

    def object_exists(self, bucket_name: str, object_name: str) -> bool:
        """指定オブジェクトの存在有無を返す。"""
        blob = self.client.bucket(bucket_name).blob(object_name)
        return blob.exists()


class LLMService:
    def __init__(self, settings: Settings):
        """Vertex AI Gemini を使った Markdown 整形サービス。"""
        self.settings = settings
        # Vertex AI 初期化はプロセス単位で一度行い、以後同モデルを再利用する。
        vertexai_init(project=settings.gcp_project_id,
                      location=settings.gcp_location)
        self.model = GenerativeModel(settings.gemini_model_name)

    def polish_markdown(self, draft_markdown: str) -> str:
        """OCR下書きMarkdownを、意味を変えずに読みやすく整形する。"""
        # OCR 生テキストの体裁のみを整える用途。
        # 事実追加や要約を抑止するため、プロンプトで明示的に制約する。
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
        response = self.model.generate_content(prompt)
        text = getattr(response, "text", "") or ""
        return text.strip()


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
