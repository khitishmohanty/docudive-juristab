import os
import re
import sys
import json
import base64
from pathlib import Path
import time

# Dynamically add project root to PYTHONPATH
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../"))
sys.path.insert(0, project_root)

# Local imports
from utils.pdf_to_image_converter import convert_pdf_to_images
from services.gemini_client import call_gemini_api
from utils.csv_excel_converter import convert_json_to_csv_and_excel
from utils.html_converter import convert_json_to_html

# Prompt sent to Gemini
GEMINI_LAYOUT_PROMPT = """
This is a document layout detection task. Identify the following items in the page sequentially and give me an output with the text with the following tags. Enum, Figure, Footnote, Header, Heading, List, Paragraph, Table, Table of Contents (ToC), Title, Subtitle, Footer, Page number, Endnotes, Glossary. Preserve the text styling information(Bold, italic and underline) in the output. Also, identify any act names or citations mentioned, issuance date, compliance date, legislative body, and publication date under a particular tag. Once you assigned a tag to one set of text dont reassign the same content or sub-content to any other tag. if any information is not present, leave that blank. give me the output in json format. in the first column put the numbers by which it can be identified as the correlation between the parent and child items and the associations. Make the node names as correlation-id, tag, content, act-name-citations, issuance-date, compliance-date, legislative-body, publication-date, verification-flag="Not Verified"
"""

def extract_json_string(raw_text: str) -> str:
    """
    Extracts the first valid JSON array or object from a raw string.
    Handles cases where Gemini wraps JSON in code blocks or adds prefix text.
    """
    json_pattern = r"(\[.*?\]|\{.*?\})"
    matches = re.findall(json_pattern, raw_text, re.DOTALL)
    return matches[0] if matches else ""

def encode_image_to_base64(image_path: str) -> str:
    """Encodes an image file to a base64 string."""
    with open(image_path, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode("utf-8")


def process_pdf(pdf_path: str, output_dir: str, image_dir: str, poppler_path: str = None) -> None:
    """Processes a PDF file: converts to images, calls Gemini API, saves JSON/CSV/Excel/HTML."""
    os.makedirs(image_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    print(f"📄 Converting PDF to images from: {pdf_path}")
    image_paths = convert_pdf_to_images(pdf_path, image_dir, poppler_path=poppler_path)

    all_responses = []

    for img_path in image_paths:
        print(f"📤 Processing image: {img_path}")
        try:
            image_base64 = encode_image_to_base64(img_path)
            response_text = call_gemini_api(image_base64, GEMINI_LAYOUT_PROMPT)

            cleaned_json_str = extract_json_string(response_text)
            if not cleaned_json_str:
                print(cleaned_json_str)
                print(f"⚠️ No valid JSON found in Gemini response for {img_path}")
                continue
            response_json = json.loads(cleaned_json_str)

            if isinstance(response_json, list):
                all_responses.extend(response_json)
            else:
                all_responses.append(response_json)

        except json.JSONDecodeError:
            print(f"⚠️ Failed to decode Gemini JSON response for image: {img_path}")
        except Exception as e:
            print(f"❌ Error processing image {img_path}: {e}")
        time.sleep(10)  # Wait for 10 seconds

    # Save master JSON
    master_json_path = os.path.join(output_dir, "gemini_master_output.json")
    with open(master_json_path, "w", encoding="utf-8") as f:
        json.dump(all_responses, f, indent=2, ensure_ascii=False)
    print(f"✅ Master JSON saved to: {master_json_path}")

    # Generate CSV, Excel, HTML
    convert_json_to_csv_and_excel(all_responses, output_dir, base_filename="gemini_output")
    convert_json_to_html(all_responses, output_dir, output_filename="gemini_output.html")


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent
    project_root = base_dir.parents[2]
    print(project_root)

    pdf_path = project_root / "tests" / "assets" / "sample.pdf"
    output_dir = project_root / "tests" / "assets"
    image_dir = output_dir / "page_images"

    # Provide poppler_path if needed
    poppler_path = None

    process_pdf(
        pdf_path=str(pdf_path),
        output_dir=str(output_dir),
        image_dir=str(image_dir),
        poppler_path=poppler_path
    )

