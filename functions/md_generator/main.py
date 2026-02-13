import os
import json
import functions_framework
from google.cloud import storage
import vertexai
from vertexai.generative_models import GenerativeModel

# 環境設定
PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "deep-book-ocr")
OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET") # 例: deep-book-ocr-output
CHUNK_SIZE = 5 # Geminiに一度に投げるページ数

vertexai.init(project=PROJECT_ID, location="us-central1")
model = GenerativeModel("gemini-1.5-pro")
storage_client = storage.Client()

def extract_page_text(json_content, start, end):
    """Document AIのJSONから指定範囲のページのテキストを抽出"""
    full_text = json_content.get("text", "")
    pages = json_content.get("pages", [])
    chunk_text = ""
    for i in range(start, min(end, len(pages))):
        for segment in pages[i].get("layout", {}).get("textAnchor", {}).get("textSegments", []):
            s = int(segment.get("startIndex", 0))
            e = int(segment.get("endIndex", 0))
            chunk_text += full_text[s:e]
    return chunk_text

@functions_framework.cloud_event
def generate_markdown(cloud_event):
    data = cloud_event.data
    # JSONファイルのみを対象にする
    if not data["name"].endswith(".json"):
        return

    # 1. JSONファイルをダウンロード
    bucket = storage_client.bucket(data["bucket"])
    blob = bucket.blob(data["name"])
    json_data = json.loads(blob.download_as_string())

    total_pages = len(json_data.get("pages", []))
    if total_pages == 0:
        return

    md_results = []

    # システム指示文
    sys_instruction = (
        "あなたは技術書の専門編集者です。以下のOCRテキストをMarkdownに整形してください。\n"
        "- ソースコードは適切な言語指定(python, shell等)でコードブロック(```)にする。\n"
        "- 図のキャプションや見出し(#, ##)を文脈から判断して付与する。\n"
        "- ページ番号やヘッダー等の不要なノイズは削除する。\n"
        "- OCR特有の誤字（lと1、0とOなど）を技術用語として修正する。"
    )

    # 2. ページ分割してGeminiを呼び出し
    for i in range(0, total_pages, CHUNK_SIZE):
        target_text = extract_page_text(json_data, i, i + CHUNK_SIZE)
        if not target_text.strip():
            continue

        print(f"Processing chunk: pages {i+1} to {min(i+CHUNK_SIZE, total_pages)}")
        prompt = f"{sys_instruction}\n\n--- OCR TEXT ---\n{target_text}"

        try:
            response = model.generate_content(prompt)
            md_results.append(response.text)
        except Exception as e:
            print(f"Error at page {i}: {e}")
            md_results.append(f"\n> [Error processing pages {i+1}-{i+CHUNK_SIZE}]\n")

    # 3. 結合してMarkdownファイルとして保存
    final_markdown = "\n\n".join(md_results)
    out_bucket = storage_client.bucket(OUTPUT_BUCKET)

    # ファイル名の整形 (input/test.pdf_json/input_test.json -> test.md)
    base_name = data["name"].split("/")[0].replace("_json", "")
    output_blob = out_bucket.blob(f"{base_name}.md")

    output_blob.upload_from_string(final_markdown, content_type="text/markdown")
    print(f"Successfully generated Markdown: {base_name}.md")
