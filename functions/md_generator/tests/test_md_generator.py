"""md_generator のエントリポイントに対する単体テスト。

確認ポイント:
- 正常系で Markdown がアップロードされる
- 非JSON入力はスキップされる
- CloudEvent欠損データ時に 400 を返す
"""

import json
from cloudevents.http import CloudEvent

import md_generator.entrypoint as entrypoint
from md_generator.entrypoint import generate_markdown


def _sample_docai_json() -> dict:
    """テスト用の最小限な Document AI 互換JSONを返す。"""
    # text: "hello world"
    # 0ページ目で "hello" を抽出
    # 1ページ目で " world" を抽出
    return {
        "text": "hello world",
        "pages": [
            {"layout": {"textAnchor": {"textSegments": [
                {"startIndex": 0, "endIndex": 5}]}}},
            {"layout": {"textAnchor": {"textSegments": [
                {"startIndex": 5, "endIndex": 11}]}}},
        ],
    }


def test_generate_markdown_success(mock_storage, mock_gemini):
    """正常系: JSONを処理して生成した markdown をアップロードする。"""
    mock_storage.download_bytes.return_value = json.dumps(
        _sample_docai_json()).encode("utf-8")
    mock_gemini.to_markdown.side_effect = ["# MD1", "# MD2"]

    event = CloudEvent(
        attributes={"type": "t", "source": "s",
                    "id": "i", "specversion": "1.0"},
        data={"bucket": "ignored", "name": "processed/sample_pdf/0.json"},
    )

    msg, code = generate_markdown(event)
    assert code == 200
    assert msg == "成功"

    # upload が1回呼ばれる
    assert mock_storage.upload_text.call_count == 1
    args, kwargs = mock_storage.upload_text.call_args
    assert args[0] == entrypoint.settings.output_bucket
    assert args[1] == "sample.md"     # "sample_pdf" から導出
    assert "# MD1" in args[2]


def test_generate_markdown_skip_non_json(mock_storage, mock_gemini):
    """非JSONオブジェクトは副作用なくスキップされること。"""
    event = CloudEvent(
        attributes={"type": "t", "source": "s",
                    "id": "i", "specversion": "1.0"},
        data={"bucket": "b", "name": "file.txt"},
    )
    msg, code = generate_markdown(event)
    assert code == 200
    assert "スキップ" in msg
    mock_storage.download_bytes.assert_not_called()
    mock_storage.upload_text.assert_not_called()


def test_generate_markdown_bad_event_data(mock_storage, mock_gemini):
    """CloudEventの必須フィールド欠損時は 400 を返すこと。"""
    # "name" が欠損
    event = CloudEvent(
        attributes={"type": "t", "source": "s",
                    "id": "i", "specversion": "1.0"},
        data={"bucket": "b"},
    )
    msg, code = generate_markdown(event)
    assert code == 400
