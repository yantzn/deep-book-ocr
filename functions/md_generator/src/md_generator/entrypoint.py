from __future__ import annotations

import json
import logging
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
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if settings.is_gcp:
        try:
            import google.cloud.logging as cloud_logging  # ✅ 遅延import

            cloud_logging.Client().setup_logging()
            logger.info("Cloud Logging を初期化しました")
        except Exception:
            logger.exception("Cloud Logging の初期化に失敗しました")


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
    - OUTPUT_BUCKET に Markdown を保存
    """
    try:
        data: dict[str, Any] = cloud_event.data or {}
        bucket = data["bucket"]
        name = data["name"]

        if not name.endswith(".json"):
            logger.info("JSON以外のためスキップします: %s", name)
            return ("JSON以外のためスキップしました。", 200)

        raw = services.storage.download_bytes(bucket, name)
        doc = json.loads(raw)

        total_pages = len((doc.get("pages", []) or []))
        if total_pages <= 0:
            logger.warning("JSONにページが見つかりません: %s", name)
            return ("ページが存在しません。", 200)

        chunks = build_page_chunks(total_pages, settings.chunk_size)
        md_parts: list[str] = []

        for idx, ch in enumerate(chunks, start=1):
            text = extract_text_from_page_range(
                doc, ch.start_page, ch.end_page)
            if not text.strip():
                continue

            logger.info(
                "Gemini チャンク %d/%d (ページ %d-%d)",
                idx,
                len(chunks),
                ch.start_page + 1,
                ch.end_page,
            )
            try:
                md = services.gemini.to_markdown(text)
                md_parts.append(md)
            except Exception as e:
                logger.exception("Gemini 変換に失敗しました (チャンク %d)", idx)
                md_parts.append(f"\n> [Error processing chunk {idx}: {e}]\n")

        final_md = "\n\n".join(md_parts)
        out_name = derive_output_markdown_name(name)
        services.storage.upload_text(
            settings.output_bucket, out_name, final_md)

        logger.info("Markdownをアップロードしました: gs://%s/%s",
                    settings.output_bucket, out_name)
        return ("成功", 200)

    except KeyError as e:
        logger.error("CloudEventデータが不正です。欠損キー: %s", e)
        return (f"不正なリクエスト: CloudEventのデータが不足しています: {e}", 400)
    except Exception:
        logger.exception("想定外のエラーが発生しました")
        return ("サーバー内部エラー", 500)
