"""
Google Cloud Function to generate Markdown from Document AI's JSON output.

This function is triggered by a CloudEvent when a new JSON file is uploaded to
a GCS bucket. It reads the JSON file, extracts the text content, uses the
Vertex AI Gemini model to convert the text to Markdown format, and then saves
the result to another GCS bucket.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import functions_framework
import vertexai
from google.cloud import storage
from vertexai.generative_models import GenerativeModel, Part

# --- Constants ---
# Environment variables
PROJECT_ID = os.environ.get("GCP_PROJECT_ID")
OUTPUT_BUCKET_NAME = os.environ.get("OUTPUT_BUCKET")
LOCATION = os.environ.get("GCP_LOCATION", "us-central1")

# Application settings
CHUNK_SIZE = 10  # Number of pages to process in a single API call
MODEL_NAME = "gemini-1.5-pro"
OUTPUT_CONTENT_TYPE = "text/markdown"

# System instruction for the generative model
SYS_INSTRUCTION = (
    "You are an expert technical editor. Your task is to format the following "
    "OCR text into clean, well-structured Markdown.\n"
    "- Identify source code and wrap it in appropriate language-specific (e.g., python, shell) code blocks (```).\n"
    "- Infer and apply headings (#, ##, etc.) and figure captions from the context.\n"
    "- Remove extraneous noise such as page numbers, headers, and footers.\n"
    "- Correct common OCR errors (e.g., 'l' vs '1', 'O' vs '0') based on technical terminology."
)


# --- Initialization ---
# For performance, initialize clients in the global scope.
# This allows them to be reused across function invocations.
# See: https://cloud.google.com/functions/docs/bestpractices/networking
try:
    if not PROJECT_ID:
        raise ValueError("GCP_PROJECT_ID environment variable not set.")
    if not OUTPUT_BUCKET_NAME:
        raise ValueError("OUTPUT_BUCKET environment variable not set.")

    vertexai.init(project=PROJECT_ID, location=LOCATION)
    model = GenerativeModel(MODEL_NAME)
    storage_client = storage.Client()
except (ValueError, Exception) as e:
    logging.critical(f"Initialization failed: {e}")
    # If initialization fails, the function will not be able to execute.
    model = None
    storage_client = None

logging.basicConfig(level=logging.INFO)


def _extract_text_from_page_range(
    doc_ai_json: Dict[str, Any], start_page: int, end_page: int
) -> str:
    """
    Extracts and concatenates text from a specified range of pages in a
    Document AI JSON structure.

    Args:
        doc_ai_json: The parsed Document AI JSON object.
        start_page: The starting page number (inclusive).
        end_page: The ending page number (exclusive).

    Returns:
        The combined text from the specified pages.
    """
    full_text = doc_ai_json.get("text", "")
    pages = doc_ai_json.get("pages", [])
    text_segments = []

    # Ensure the page range is within the document's bounds
    start_page = max(0, start_page)
    end_page = min(len(pages), end_page)

    for i in range(start_page, end_page):
        page = pages[i]
        layout = page.get("layout", {})
        text_anchor = layout.get("textAnchor", {})
        for segment in text_anchor.get("textSegments", []):
            start_index = int(segment.get("startIndex", 0))
            end_index = int(segment.get("endIndex", 0))
            text_segments.append(full_text[start_index:end_index])

    return "".join(text_segments)


def _upload_to_gcs(
    bucket_name: str, blob_name: str, data: str, content_type: str
) -> None:
    """
    Uploads data to a specified GCS bucket.

    Args:
        bucket_name: The name of the GCS bucket.
        blob_name: The desired name of the object in the bucket.
        data: The string data to upload.
        content_type: The MIME type of the content.
    """
    try:
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        blob.upload_from_string(data, content_type=content_type)
        logging.info(f"Successfully uploaded to gs://{bucket_name}/{blob_name}")
    except Exception as e:
        logging.error(f"Failed to upload to GCS: {e}", exc_info=True)
        raise


def _generate_markdown_from_text_chunks(
    text_chunks: List[str],
) -> str:
    """
    Generates Markdown content by sending text chunks to the generative model.

    Args:
        text_chunks: A list of text strings to be processed.

    Returns:
        A single string containing the combined Markdown output.
    """
    md_results = []
    total_chunks = len(text_chunks)

    for i, chunk in enumerate(text_chunks):
        if not chunk.strip():
            continue

        logging.info(f"Processing chunk {i + 1} of {total_chunks}...")
        prompt = [
            Part.from_text(SYS_INSTRUCTION),
            Part.from_text("\n\n--- OCR TEXT ---\n"),
            Part.from_text(chunk),
        ]

        try:
            response = model.generate_content(prompt, stream=False)
            md_results.append(response.text)
        except Exception as e:
            error_msg = f"\n> [Error processing chunk {i + 1} of {total_chunks}: {e}]\n"
            logging.error(f"Model generation failed for chunk {i+1}: {e}", exc_info=True)
            md_results.append(error_msg)

    return "\n\n".join(md_results)


@functions_framework.cloud_event
def generate_markdown(cloud_event: Any) -> Optional[str]:
    """
    Cloud Function entry point. Triggered by a GCS object creation event.

    Args:
        cloud_event: The CloudEvent object containing event data.

    Returns:
        An optional error message string for Cloud Functions logging.
    """
    if not model or not storage_client:
        # If clients failed to initialize, log a critical error and exit.
        logging.critical("Clients not initialized. Aborting execution.")
        return "CRITICAL: Clients not initialized."

    data = cloud_event.data
    bucket_name = data.get("bucket")
    file_name = data.get("name")

    if not file_name or not file_name.endswith(".json"):
        logging.info(f"Skipping non-JSON file: {file_name}")
        return

    logging.info(f"Processing file: gs://{bucket_name}/{file_name}")

    try:
        # 1. Download and parse the source JSON file
        blob = storage_client.bucket(bucket_name).blob(file_name)
        json_data = json.loads(blob.download_as_string())
    except Exception as e:
        logging.error(f"Failed to download or parse JSON file: {e}", exc_info=True)
        return f"ERROR: Could not process file {file_name}."

    total_pages = len(json_data.get("pages", []))
    if total_pages == 0:
        logging.warning(f"No pages found in {file_name}. Aborting.")
        return

    # 2. Extract text from the JSON in chunks
    text_chunks = [
        _extract_text_from_page_range(json_data, i, i + CHUNK_SIZE)
        for i in range(0, total_pages, CHUNK_SIZE)
    ]

    # 3. Generate Markdown from the text chunks using the model
    final_markdown = _generate_markdown_from_text_chunks(text_chunks)

    # 4. Determine output filename and upload the result
    # Assumes input format like: 'processed/my-book_pdf/0.json' -> 'my-book.md'
    # It takes the parent directory name and removes the '_pdf' suffix.
    p = Path(file_name)
    base_name = p.parent.name.removesuffix("_pdf")
    output_filename = f"{base_name}.md"

    try:
        _upload_to_gcs(
            OUTPUT_BUCKET_NAME, output_filename, final_markdown, OUTPUT_CONTENT_TYPE
        )
        logging.info(f"Successfully generated Markdown: {output_filename}")
    except Exception as e:
        # Error is already logged in the helper function.
        return f"ERROR: Failed to upload {output_filename}."

    return "SUCCESS"