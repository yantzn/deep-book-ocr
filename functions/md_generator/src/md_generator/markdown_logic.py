from __future__ import annotations

"""
Markdown関連の補助ロジック。

I/Oや外部APIに依存しない処理を集約し、テスト容易性を高める。
"""

from dataclasses import dataclass
from pathlib import PurePosixPath
import re
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
    parts = p.parts

    for part in parts:
        if part.endswith(".pdf_json"):
            return f"{part[:-9]}.md"
        if part.endswith("_pdf"):
            return f"{part[:-4]}.md"

    stem = p.stem
    stem = re.sub(r"-\d+$", "", stem)
    if not stem:
        stem = "output"
    return f"{stem}.md"


def derive_json_group_prefix(json_object_name: str) -> str:
    """同一OCR結果グループのJSONを列挙するためのprefixを返す。"""
    p = PurePosixPath(json_object_name)
    parent = p.parent.as_posix()
    if parent in ("", "."):
        return ""
    return f"{parent}/"


def _extract_trailing_number(name: str) -> int:
    stem = PurePosixPath(name).stem
    m = re.search(r"(\d+)$", stem)
    return int(m.group(1)) if m else -1


def sort_json_object_names(names: List[str]) -> List[str]:
    """JSONオブジェクト名をページ順に近い形で安定ソートする。"""
    return sorted(
        names,
        key=lambda n: (
            PurePosixPath(n).parent.as_posix(),
            _extract_trailing_number(n),
            PurePosixPath(n).name,
        ),
    )
