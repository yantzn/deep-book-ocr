from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any


@dataclass
class TextBlock:
    page_number: int
    text: str
    y_top: float
    x_left: float
    y_bottom: float
    x_right: float
    block_type: str


def _anchor_text(full_text: str, text_anchor: dict[str, Any]) -> str:
    chunks: list[str] = []
    for seg in text_anchor.get("textSegments", []):
        start_index = int(seg.get("startIndex", 0) or 0)
        end_index = int(seg.get("endIndex", 0) or 0)
        chunks.append(full_text[start_index:end_index])
    return "".join(chunks)


def _get_vertices(layout: dict[str, Any]) -> list[dict[str, float]]:
    poly = layout.get("boundingPoly", {})
    vertices = poly.get("normalizedVertices") or poly.get("vertices") or []
    normalized: list[dict[str, float]] = []

    for v in vertices:
        x = float(v.get("x", 0.0) or 0.0)
        y = float(v.get("y", 0.0) or 0.0)
        normalized.append({"x": x, "y": y})

    if not normalized:
        normalized = [{"x": 0.0, "y": 0.0}] * 4

    return normalized


def _bbox_from_layout(layout: dict[str, Any]) -> tuple[float, float, float, float]:
    vs = _get_vertices(layout)
    xs = [v["x"] for v in vs]
    ys = [v["y"] for v in vs]
    return min(ys), min(xs), max(ys), max(xs)


def _clean_inline_text(text: str) -> str:
    text = text.replace("\u00ad", "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _looks_like_page_number(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if re.fullmatch(r"-?\s*\d+\s*-?", t):
        return True
    if re.fullmatch(r"[Pp]\.?\s*\d+", t):
        return True
    return False


def _is_probable_header_footer(text: str, y_top: float, y_bottom: float) -> bool:
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
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return text


def _merge_wrapped_lines(text: str) -> str:
    """
    OCR由来の不自然な改行をある程度つなぐ。
    """
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

    return "\n".join(out).strip()


def _extract_blocks_from_page(doc: dict[str, Any], page: dict[str, Any]) -> list[TextBlock]:
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
    """
    複数ページで繰り返すヘッダ/フッタ候補を落とす。
    """
    freq: dict[str, int] = {}
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
    parts: list[str] = []
    last_page = None

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
    chunks: list[str] = []
    for doc in json_docs:
        txt = str(doc.get("text", "") or "").strip()
        if txt:
            chunks.append(txt)
    return _merge_wrapped_lines("\n\n".join(chunks))


def _collect_blocks(json_docs: list[dict[str, Any]]) -> list[TextBlock]:
    blocks: list[TextBlock] = []
    for doc in json_docs:
        for page in doc.get("pages", []):
            blocks.extend(_extract_blocks_from_page(doc, page))
    return blocks


def build_markdown_from_documentai_jsons(
    json_docs: list[dict[str, Any]],
    llm_service: Any,
    enable_gemini_polish: bool = True,
) -> tuple[str, dict[str, Any]]:
    blocks = _collect_blocks(json_docs)
    sorted_blocks = _sort_blocks_reading_order(blocks)
    filtered_blocks = _dedupe_repeated_header_footer(sorted_blocks)

    if filtered_blocks:
        draft = _blocks_to_markdown(filtered_blocks)
    else:
        draft = _fallback_plain_text(json_docs)

    draft = draft.strip()
    if not draft:
        raise RuntimeError("Draft markdown is empty after parsing OCR JSON")

    polished = draft
    used_gemini = False

    if enable_gemini_polish:
        polished_candidate = llm_service.polish_markdown(draft)
        if polished_candidate.strip():
            polished = polished_candidate.strip()
            used_gemini = True

    if not polished.endswith("\n"):
        polished += "\n"

    stats = {
        "json_docs": len(json_docs),
        "raw_blocks": len(blocks),
        "filtered_blocks": len(filtered_blocks),
        "used_gemini": used_gemini,
        "draft_chars": len(draft),
        "final_chars": len(polished),
    }
    return polished, stats
