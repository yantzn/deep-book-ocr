from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Protocol


logger = logging.getLogger(__name__)


class MarkdownPolisher(Protocol):
    def polish_markdown(self, draft_markdown: str) -> str:
        ...


@dataclass
class TextBlock:
    # Document AI レイアウト情報を、後段で扱いやすい中間表現へ正規化した単位。
    # page と bbox を持たせることで、読み順復元やヘッダ/フッタ除去に利用する。
    page_number: int
    text: str
    y_top: float
    x_left: float
    y_bottom: float
    x_right: float
    block_type: str


def _anchor_text(full_text: str, text_anchor: dict[str, Any]) -> str:
    # textAnchor の start/end インデックス群から、元テキストを連結復元する。
    # Document AI はページ要素ごとの部分範囲だけを返すため、この処理が必要。
    chunks: list[str] = []
    for seg in text_anchor.get("textSegments", []):
        start_index = int(seg.get("startIndex", 0) or 0)
        end_index = int(seg.get("endIndex", 0) or 0)
        chunks.append(full_text[start_index:end_index])
    return "".join(chunks)


def _get_vertices(layout: dict[str, Any]) -> list[dict[str, float]]:
    # normalizedVertices / vertices どちらの形式でも扱えるよう統一。
    poly = layout.get("boundingPoly", {})
    vertices = poly.get("normalizedVertices") or poly.get("vertices") or []

    normalized: list[dict[str, float]] = []
    for v in vertices:
        x = float(v.get("x", 0.0) or 0.0)
        y = float(v.get("y", 0.0) or 0.0)
        normalized.append({"x": x, "y": y})

    if not normalized:
        # bbox 欠損でも後段処理を継続できるよう、原点のダミー4点を補完する。
        normalized = [{"x": 0.0, "y": 0.0}] * 4

    return normalized


def _bbox_from_layout(layout: dict[str, Any]) -> tuple[float, float, float, float]:
    # 頂点列から [top, left, bottom, right] を算出して比較しやすい形にする。
    vs = _get_vertices(layout)
    xs = [v["x"] for v in vs]
    ys = [v["y"] for v in vs]
    return min(ys), min(xs), max(ys), max(xs)


def _clean_inline_text(text: str) -> str:
    # OCR 由来の不可視文字・余分空白を正規化して比較や分類の精度を上げる。
    text = text.replace("\u00ad", "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _looks_like_page_number(text: str) -> bool:
    # 単独数字や "P.12" など、ページ番号らしい短文を判定する。
    t = text.strip()
    if not t:
        return False
    if re.fullmatch(r"-?\s*\d+\s*-?", t):
        return True
    if re.fullmatch(r"[Pp]\.?\s*\d+", t):
        return True
    return False


def _is_probable_header_footer(text: str, y_top: float, y_bottom: float) -> bool:
    # 上端/下端にある短文やページ番号をヘッダ/フッタ候補として扱う。
    t = text.strip()
    if not t:
        return True
    if len(t) <= 3 and _looks_like_page_number(t):
        return True
    if y_top < 0.05:
        return True
    if y_bottom > 0.95:
        return True
    return False


def _is_heading_candidate(text: str) -> bool:
    # 見出し化の候補判定（短文・章節番号・節番号形式など）。
    # 誤検出を避けるため長文や文末句点付きは除外する。
    t = text.strip()
    if not t:
        return False
    if len(t) > 80:
        return False
    if t.endswith("。"):
        return False
    if re.fullmatch(r"[第].{1,12}[章節部]", t):
        return True
    if re.fullmatch(r"\d+(\.\d+)*\s+.+", t):
        return True
    if len(t) <= 30:
        return True
    return False


def _normalize_line_breaks(text: str) -> str:
    # 改行コード揺れと行頭/行末の空白を統一。
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return text


def _merge_wrapped_lines(text: str) -> str:
    """OCR由来の不自然な改行をある程度つなぐ。"""
    lines = [ln.strip() for ln in _normalize_line_breaks(text).split("\n")]
    merged: list[str] = []

    for line in lines:
        if not line:
            merged.append("")
            continue

        if not merged:
            merged.append(line)
            continue

        prev = merged[-1]
        if not prev:
            merged.append(line)
            continue

        should_join = (
            # 文が未完了で、次行がリスト/見出し開始でない場合は連結する。
            not prev.endswith(("。", "！", "？", ".", "!", "?", ":", "："))
            and not line.startswith(("-", "*", "・", "■", "□", "◯", "○"))
            and not re.match(r"^\d+(\.\d+)*\s+", line)
        )

        if should_join:
            merged[-1] = f"{prev}{line}"
        else:
            merged.append(line)

    out: list[str] = []
    for line in merged:
        if line == "":
            if not out or out[-1] == "":
                continue
            out.append(line)
            continue
        out.append(line)

    return "\n".join(out).strip()


def _extract_blocks_from_page(doc: dict[str, Any], page: dict[str, Any]) -> list[TextBlock]:
    # 1ページ分の block/paragraph を TextBlock へ変換する。
    # blocks がある場合はそちらを優先（より大きい意味単位を優先）。
    full_text = doc.get("text", "")
    page_number = int(page.get("pageNumber", 0) or 0)

    blocks: list[TextBlock] = []
    page_blocks = page.get("blocks", [])
    page_paragraphs = page.get("paragraphs", [])

    if page_blocks:
        for blk in page_blocks:
            layout = blk.get("layout", {})
            text = _clean_inline_text(_anchor_text(
                full_text, layout.get("textAnchor", {})))
            if not text:
                continue

            y_top, x_left, y_bottom, x_right = _bbox_from_layout(layout)
            blocks.append(
                TextBlock(
                    page_number=page_number,
                    text=text,
                    y_top=y_top,
                    x_left=x_left,
                    y_bottom=y_bottom,
                    x_right=x_right,
                    block_type="block",
                )
            )
        return blocks

    for para in page_paragraphs:
        layout = para.get("layout", {})
        text = _clean_inline_text(_anchor_text(
            full_text, layout.get("textAnchor", {})))
        if not text:
            continue

        y_top, x_left, y_bottom, x_right = _bbox_from_layout(layout)
        blocks.append(
            TextBlock(
                page_number=page_number,
                text=text,
                y_top=y_top,
                x_left=x_left,
                y_bottom=y_bottom,
                x_right=x_right,
                block_type="paragraph",
            )
        )

    return blocks


def _sort_blocks_reading_order(blocks: list[TextBlock]) -> list[TextBlock]:
    """
    簡易な読み順:
    - 上から下
    - 近い行では左から右
    """
    return sorted(
        blocks,
        key=lambda b: (
            b.page_number,
            round(b.y_top, 3),
            round(b.x_left, 3),
        ),
    )


def _dedupe_repeated_header_footer(blocks: list[TextBlock]) -> list[TextBlock]:
    """複数ページで繰り返すヘッダ/フッタ候補を落とす。"""
    freq: dict[str, int] = {}

    # 短文の出現回数を数え、複数ページで反復する要素を候補化する。
    for b in blocks:
        t = b.text.strip()
        if len(t) <= 80:
            freq[t] = freq.get(t, 0) + 1

    filtered: list[TextBlock] = []
    for b in blocks:
        t = b.text.strip()
        repeated = freq.get(t, 0) >= 3
        if repeated and _is_probable_header_footer(t, b.y_top, b.y_bottom):
            continue
        if _is_probable_header_footer(t, b.y_top, b.y_bottom):
            continue
        filtered.append(b)

    return filtered


def _blocks_to_markdown(blocks: list[TextBlock]) -> str:
    # TextBlock を行単位テキストへ落とし込み、簡易ルールで見出し化する。
    parts: list[str] = []
    last_page: int | None = None

    for b in blocks:
        text = b.text.strip()
        if not text:
            continue

        if last_page is not None and b.page_number != last_page:
            parts.append("")
        last_page = b.page_number

        if _looks_like_page_number(text):
            continue

        if _is_heading_candidate(text):
            # 章節表記や番号付き見出しはレベルを推定して Markdown 見出しへ。
            if re.fullmatch(r"[第].{1,12}[章節部]", text):
                parts.append(f"# {text}")
            elif re.fullmatch(r"\d+(\.\d+)*\s+.+", text):
                level = min(text.split(" ")[0].count(".") + 1, 3)
                parts.append(f'{"#" * level} {text}')
            elif len(text) <= 18:
                parts.append(f"## {text}")
            else:
                parts.append(text)
        else:
            parts.append(text)

    raw = "\n\n".join(p.strip() for p in parts if p and p.strip())
    return _merge_wrapped_lines(raw)


def _fallback_plain_text(json_docs: list[dict[str, Any]]) -> str:
    # レイアウト抽出がうまくいかない場合の退避経路。
    # document.text を連結して最低限の本文を確保する。
    chunks: list[str] = []
    for doc in json_docs:
        txt = str(doc.get("text", "") or "").strip()
        if txt:
            chunks.append(txt)
    return _merge_wrapped_lines("\n\n".join(chunks))


def _collect_blocks(json_docs: list[dict[str, Any]]) -> list[TextBlock]:
    # 複数JSON（複数ページ/複数分割）を横断して TextBlock を収集する。
    blocks: list[TextBlock] = []
    for doc in json_docs:
        for page in doc.get("pages", []):
            blocks.extend(_extract_blocks_from_page(doc, page))
    return blocks


def build_markdown_from_documentai_jsons(
    json_docs: list[dict[str, Any]],
    llm_service: MarkdownPolisher,
    enable_gemini_polish: bool = True,
) -> tuple[str, dict[str, Any]]:
    # 1) JSON -> block 収集
    blocks = _collect_blocks(json_docs)

    # 2) 読み順整列 + ヘッダ/フッタ除去
    sorted_blocks = _sort_blocks_reading_order(blocks)
    filtered_blocks = _dedupe_repeated_header_footer(sorted_blocks)

    # 3) Markdown 下書き生成（失敗時は plain text フォールバック）
    if filtered_blocks:
        draft = _blocks_to_markdown(filtered_blocks)
    else:
        draft = _fallback_plain_text(json_docs)

    draft = draft.strip()
    if not draft:
        raise RuntimeError("Draft markdown is empty after parsing OCR JSON")

    polished = draft
    used_gemini = False
    fallback_used = False
    polish_error_kind: str | None = None
    polish_error_message: str | None = None

    # 4) 任意で Gemini による体裁調整を実施
    #    ここで失敗しても本線は落とさず、draft をそのまま採用する。
    if enable_gemini_polish:
        try:
            polished_candidate = llm_service.polish_markdown(draft)
            if polished_candidate.strip():
                polished = polished_candidate.strip()
                used_gemini = True
            else:
                logger.warning(
                    "Gemini polish returned empty content. Falling back to draft markdown."
                )
                fallback_used = True
        except Exception as exc:
            polish_error_kind = exc.__class__.__name__
            polish_error_message = str(exc)
            fallback_used = True
            logger.exception(
                "Gemini polish failed. Falling back to draft markdown. "
                "error_kind=%s error_message=%s",
                polish_error_kind,
                polish_error_message,
            )

    if not polished.endswith("\n"):
        # 出力末尾を改行で統一し、後段処理や表示差分を安定化する。
        polished += "\n"

    # 5) 観測用メトリクスを返す（ログ/監視向け）
    stats = {
        "json_docs": len(json_docs),
        "raw_blocks": len(blocks),
        "filtered_blocks": len(filtered_blocks),
        "used_gemini": used_gemini,
        "fallback_used": fallback_used,
        "draft_chars": len(draft),
        "final_chars": len(polished),
    }

    if polish_error_kind:
        stats["polish_error_kind"] = polish_error_kind
    if polish_error_message:
        stats["polish_error_message"] = polish_error_message

    return polished, stats
