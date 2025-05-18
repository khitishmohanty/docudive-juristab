import os
import re
import sys
import json
import base64
import time
from pathlib import Path

# Add project root to PYTHONPATH
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../"))
sys.path.insert(0, project_root)

# Local imports
from utils.pdf_to_image_converter import convert_pdf_to_images
from services.gemini_client import call_gemini_api
from services.openai_client import call_openai_api
from utils.csv_excel_converter import convert_json_to_csv_and_excel
from utils.html_converter import convert_json_to_html
from utils.prompt_loader import load_prompt

# Load prompts from file
gemini_prompt = load_prompt("gemini_layout_prompt.txt")
openai_prompt = load_prompt("openai_layout_prompt.txt")
consolidation_prompt = load_prompt("consolidation_prompt.txt")


def extract_json_string(raw_text: str) -> str:
    """Extracts the first valid JSON array or object from a raw string."""
    json_pattern = r"(\[.*?\]|\{.*?\})"
    matches = re.findall(json_pattern, raw_text, re.DOTALL)
    return matches[0] if matches else ""


def encode_image_to_base64(image_path: str) -> str:
    """Encodes an image file to a base64 string."""
    with open(image_path, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode("utf-8")


def consolidate_responses(image_base64: str, gemini_json, openai_json, prompt: str) -> dict:
    """
    Consolidate Gemini and OpenAI outputs using Gemini API with image and a structured prompt.
    """
    # Embed both JSON responses into the prompt
    merged_prompt = (
        f"{prompt.strip()}\n\n"
        f"GEMINI RESPONSE:\n{json.dumps(gemini_json, indent=2)}\n\n"
        f"OPENAI RESPONSE:\n{json.dumps(openai_json, indent=2)}"
    )

    try:
        result_text = call_gemini_api(image_base64, merged_prompt)
        cleaned_json_str = extract_json_string(result_text)
        return json.loads(cleaned_json_str) if cleaned_json_str else {}
    except Exception as e:
        print(f"❌ Consolidation failed: {e}")
        return {"gemini": gemini_json, "openai": openai_json, "verification-flag": "Fallback"}



def process_pdf(pdf_path: str, output_dir: str, image_dir: str, poppler_path: str = None) -> None:
    """Processes PDF into images, calls Gemini & OpenAI APIs, merges responses, saves outputs."""
    os.makedirs(image_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    print(f"📄 Converting PDF to images from: {pdf_path}")
    image_paths = convert_pdf_to_images(pdf_path, image_dir, poppler_path=poppler_path)

    all_responses = []

    for img_path in image_paths:
        print(f"📤 Processing image: {img_path}")
        print("---------------------")
        try:
            image_base64 = encode_image_to_base64(img_path)

            # Call Gemini
            gemini_raw = call_gemini_api(image_base64, gemini_prompt)
            gemini_json_str = extract_json_string(gemini_raw)
            gemini_json = json.loads(gemini_json_str) if gemini_json_str else {}
            print("Received Gemini response")
            
            # Call OpenAI
            openai_raw = call_openai_api(image_base64, openai_prompt)
            openai_json_str = extract_json_string(openai_raw)
            openai_json = json.loads(openai_json_str) if openai_json_str else {}
            print("Received Chat GPT response")
            
            # Consolidate results
            consolidated = consolidate_responses(
                image_base64=image_base64,
                gemini_json=gemini_json,
                openai_json=openai_json,
                prompt=consolidation_prompt
            )
            print("Received Consolidated response")

            if isinstance(consolidated, list):
                all_responses.extend(consolidated)
            else:
                all_responses.append(consolidated)
            print("Json response appended")

        except json.JSONDecodeError as je:
            print(f"⚠️ JSON decoding error for image {img_path}: {je}")
        except Exception as e:
            print(f"❌ Error processing image {img_path}: {e}")
        time.sleep(10)
        print("---------------------")

    # Save master JSON
    master_json_path = os.path.join(output_dir, "gemini_master_output.json")
    with open(master_json_path, "w", encoding="utf-8") as f:
        json.dump(all_responses, f, indent=2, ensure_ascii=False)
    print(f"✅ Master JSON saved to: {master_json_path}")

    # Export to CSV, Excel, HTML
    convert_json_to_csv_and_excel(all_responses, output_dir, base_filename="gemini_output")
    convert_json_to_html(all_responses, output_dir, output_filename="gemini_output.html")


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent
    project_root = base_dir.parents[2]
    print(project_root)

    pdf_path = project_root / "tests" / "assets" / "sample.pdf"
    output_dir = project_root / "tests" / "assets"
    image_dir = output_dir / "page_images"

    poppler_path = None  # macOS: install with `brew install poppler`

    process_pdf(
        pdf_path=str(pdf_path),
        output_dir=str(output_dir),
        image_dir=str(image_dir),
        poppler_path=poppler_path
    )
