from __future__ import annotations

"""
Markdown関連の補助ロジック。

I/Oや外部APIに依存しない処理を集約し、テスト容易性を高める。
"""

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Dict, List


@dataclass(frozen=True)
class PageChunk:
    """半開区間 [start_page, end_page) のページ範囲を表す。"""

    start_page: int  # 0始まり
    end_page: int  # 終端は含まない


def build_page_chunks(total_pages: int, chunk_size: int) -> List[PageChunk]:
    """総ページ数を、段階的なモデル処理用のチャンク範囲に分割する。"""
    if total_pages <= 0:
        return []
    if chunk_size <= 0:
        chunk_size = 10

    chunks: List[PageChunk] = []
    for i in range(0, total_pages, chunk_size):
        chunks.append(
            PageChunk(start_page=i, end_page=min(i + chunk_size, total_pages)))
    return chunks


def extract_text_from_page_range(doc_ai_json: Dict[str, Any], start_page: int, end_page: int) -> str:
    """
    Document AI のJSON構造を使って、ページ範囲 [start_page, end_page) のテキストを抽出する。

    前提となるキー:
    - doc_ai_json["text"]
    - doc_ai_json["pages"][i]["layout"]["textAnchor"]["textSegments"]
    """
    full_text = doc_ai_json.get("text", "") or ""
    pages = doc_ai_json.get("pages", []) or []

    start_page = max(0, start_page)
    end_page = min(len(pages), end_page)

    parts: List[str] = []
    for i in range(start_page, end_page):
        page = pages[i] or {}
        segments = (
            page.get("layout", {})
            .get("textAnchor", {})
            .get("textSegments", [])
        ) or []

        for seg in segments:
            s = int(seg.get("startIndex", 0) or 0)
            e = int(seg.get("endIndex", 0) or 0)
            if e > s:
                parts.append(full_text[s:e])

    return "".join(parts)


def derive_output_markdown_name(json_object_name: str) -> str:
    """
    JSONオブジェクトのパスから、出力Markdownファイル名を導出する。

    例:
    - processed/sample_pdf/0.json -> sample.md
    """
    p = PurePosixPath(json_object_name)
    parent = p.parent.name if p.parent.name else "output"
    base = parent[:-4] if parent.endswith("_pdf") else parent
    return f"{base}.md"
