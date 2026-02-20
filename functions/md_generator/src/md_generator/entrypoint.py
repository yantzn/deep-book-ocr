from __future__ import annotations

"""Markdown生成用のCloud Functionエントリポイント。

責務:
- GCSイベントから OCR JSON を読み込む
- ページチャンク単位で Gemini 変換を実施
- 変換結果を Markdown として保存する
"""

import json
import logging
from typing import Any, Optional

import functions_framework
from cloudevents.http import CloudEvent
from google.cloud import logging as cloud_logging

from .config import get_settings, Settings
from .gcp_services import build_services
from .markdown_logic import (
    build_page_chunks,
    derive_output_markdown_name,
    extract_text_from_page_range,
)

logger = logging.getLogger(__name__)


def setup_logging(settings: Settings) -> None:
    """ローカルログを設定し、GCP時のみ Cloud Logging を有効化する。"""
    # local: 標準logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # gcp: Cloud Logging
    if settings.is_gcp:
        try:
            cloud_logging.Client().setup_logging()
            logger.info("Cloud Logging を初期化しました")
        except Exception:
            logger.exception("Cloud Logging の初期化に失敗しました")


# グローバル初期化（呼び出し間で再利用する）
settings = get_settings()
setup_logging(settings)
services = build_services(settings)


@functions_framework.cloud_event
def generate_markdown(cloud_event: CloudEvent) -> tuple[str, int]:
    """
    トリガー: GCS finalize イベント（Document AI のJSON出力）。

    - GCS から JSON を読み込む（STORAGE_MODE=emulator 時はエミュレータバケット）
    - OCRテキストをページ単位でチャンク抽出
    - Gemini で markdown 形式へ整形
    - 出力バケット（またはエミュレータ出力バケット）へ保存

    実装上の意図:
    - 失敗時は 400/500 を返して再試行判断をしやすくする
    - チャンク単位でエラーを吸収し、可能な限り出力を継続する
    """
    try:
        data: dict[str, Any] = cloud_event.data or {}
        bucket = data["bucket"]
        name = data["name"]

        if not name.endswith(".json"):
            logger.info("JSON以外のためスキップします: %s", name)
            return ("JSON以外のためスキップしました。", 200)

        # Storage接続先のみを切り替える
        in_bucket = settings.emulator_input_bucket if settings.use_emulator else bucket
        out_bucket = settings.emulator_output_bucket if settings.use_emulator else settings.output_bucket

        logger.info("入力: bucket=%s name=%s (解決後bucket=%s)",
                    bucket, name, in_bucket)

        raw = services.storage.download_bytes(in_bucket, name)
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

        services.storage.upload_text(out_bucket, out_name, final_md)
        logger.info("Markdownをアップロードしました: gs://%s/%s", out_bucket, out_name)

        return ("成功", 200)

    except KeyError as e:
        logger.error("CloudEventデータが不正です。欠損キー: %s", e)
        return (f"不正なリクエスト: CloudEventのデータが不足しています: {e}", 400)

    except Exception:
        logger.exception("想定外のエラーが発生しました")
        return ("サーバー内部エラー", 500)
