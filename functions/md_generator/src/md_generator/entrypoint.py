from __future__ import annotations

import json
import logging
import time
from typing import Any

import functions_framework
from cloudevents.http import CloudEvent

from .config import Settings, get_settings
from .gcp_services import build_services
from .markdown_logic import (
    build_page_chunks,
    derive_output_markdown_name,
    extract_text_from_page_range,
)

logger = logging.getLogger(__name__)


def setup_logging(settings: Settings) -> None:
    """
    logging 初期化。
    - ローカル: 標準logging
    - GCP: Cloud Logging を有効化（遅延importでローカル破損を回避）
    """
    level_name = settings.log_level.upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
    else:
        root.setLevel(level)

    logger.info("Logging configured: level=%s app_env=%s",
                level_name, settings.app_env)

    if settings.is_gcp:
        try:
            import google.cloud.logging as cloud_logging  # ✅ 遅延import

            cloud_logging.Client().setup_logging()
            logger.info("Cloud Logging を初期化しました")
        except Exception:
            logger.exception("Cloud Logging の初期化に失敗しました")


def load_json_utf8(raw: bytes) -> dict[str, Any]:
    """
    GCSから取得したJSON(bytes)をUTF-8固定で読み込む。

    - 文字化けの根を断つため、decodeを明示
    - 失敗したら例外で落として原因を明確化
    """
    text = raw.decode("utf-8")  # ✅ 明示
    return json.loads(text)


# グローバル初期化（呼び出し間で再利用）
settings = get_settings()
setup_logging(settings)
services = build_services(settings)


@functions_framework.cloud_event
def generate_markdown(cloud_event: CloudEvent) -> tuple[str, int]:
    """
    トリガー: GCS finalize イベント（Document AI のJSON出力）
    - JSON以外はスキップ
    - OCR JSON を読み取り、ページチャンクでGemini整形
    - OUTPUT_BUCKET に Markdown をUTF-8で保存（charset付き）
    """
    try:
        started_at = time.perf_counter()
        event_id = cloud_event.get("id")
        event_type = cloud_event.get("type")

        data: dict[str, Any] = cloud_event.data or {}
        bucket = data["bucket"]
        name = data["name"]
        generation = data.get("generation")

        logger.info(
            "Markdown trigger received: event_id=%s type=%s bucket=%s name=%s generation=%s",
            event_id,
            event_type,
            bucket,
            name,
            generation,
        )

        if not name.endswith(".json"):
            logger.info("Skipped non-JSON object: event_id=%s bucket=%s name=%s",
                        event_id, bucket, name)
            return ("JSON以外のためスキップしました。", 200)

        raw = services.storage.download_bytes(bucket, name)
        logger.info("Downloaded OCR JSON: bucket=%s name=%s bytes=%d",
                    bucket, name, len(raw))

        # ✅ UTF-8固定でJSONロード（ここが重要）
        doc = load_json_utf8(raw)

        total_pages = len((doc.get("pages", []) or []))
        if total_pages <= 0:
            logger.warning("JSONにページが見つかりません: %s", name)
            return ("ページが存在しません。", 200)

        chunks = build_page_chunks(total_pages, settings.chunk_size)
        logger.info("Chunk plan created: total_pages=%d chunk_size=%d chunk_count=%d",
                    total_pages, settings.chunk_size, len(chunks))

        md_parts: list[str] = []

        for idx, ch in enumerate(chunks, start=1):
            text = extract_text_from_page_range(
                doc, ch.start_page, ch.end_page)
            if not text.strip():
                logger.debug("Chunk empty, skipped: chunk=%d pages=%d-%d",
                             idx, ch.start_page + 1, ch.end_page)
                continue

            logger.info(
                "Gemini chunk start: chunk=%d/%d pages=%d-%d chars=%d",
                idx,
                len(chunks),
                ch.start_page + 1,
                ch.end_page,
                len(text),
            )

            try:
                chunk_started_at = time.perf_counter()
                md = services.gemini.to_markdown(text)
                md_parts.append(md)
                logger.info("Gemini chunk done: chunk=%d output_chars=%d elapsed_ms=%d",
                            idx, len(md), int((time.perf_counter() - chunk_started_at) * 1000))
            except Exception as e:
                logger.exception(
                    "Gemini chunk failed: chunk=%d pages=%d-%d chars=%d",
                    idx,
                    ch.start_page + 1,
                    ch.end_page,
                    len(text),
                )
                md_parts.append(f"\n> [Error processing chunk {idx}: {e}]\n")

        final_md = "\n\n".join(md_parts).strip()
        if not final_md:
            logger.warning("Markdownが空でした: %s", name)
            return ("Markdownが空でした。", 200)

        out_name = derive_output_markdown_name(name)

        # ✅ UTF-8 + charset でアップロード（gcp_services側でencodeしている）
        services.storage.upload_text(
            settings.output_bucket, out_name, final_md)

        logger.info(
            "Markdown uploaded: output=gs://%s/%s markdown_chars=%d elapsed_ms=%d",
            settings.output_bucket,
            out_name,
            len(final_md),
            int((time.perf_counter() - started_at) * 1000),
        )
        return ("成功", 200)

    except KeyError as e:
        logger.error(
            "Invalid CloudEvent payload: missing_key=%s payload_keys=%s",
            e,
            sorted((cloud_event.data or {}).keys()),
        )
        return (f"不正なリクエスト: CloudEventのデータが不足しています: {e}", 400)

    except Exception:
        logger.exception("Unexpected error while generating markdown")
        return ("サーバー内部エラー", 500)
