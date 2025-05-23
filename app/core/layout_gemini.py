import time
import json
import os

from services.gemini_client import call_gemini_api
from utils.json_utils import extract_json_string
from utils.prompt_loader import load_json_prompt

gemini_prompt_config = load_json_prompt("gemini_layout_prompt.json") # Expects image

def _call_gemini_for_layout(pdf_page_base64: str, page_num_actual: int, genai_output_dir: str, metrics: dict) -> dict:
    """Calls Gemini API for layout extraction and updates metrics."""
    global gemini_prompt_config
    gemini_json = {}
    gemini_raw_text = ""
    gemini_layout_start_time = time.time()
    try:
        prompt_details = gemini_prompt_config.get("prompt_details", {})
        task_desc = prompt_details.get("task_description", "")
        output_format_obj = prompt_details.get("output_format_instructions", {})
        input_desc = prompt_details.get("input_pdf_page_description", "The input is a single page from a PDF document.")

        gemini_api_parts = [
            {"text": text} for text in [
                task_desc,
                f"Please adhere strictly to the following output format and schema:\n{json.dumps(output_format_obj, indent=2)}" if output_format_obj else None,
                f"Contextual description of the PDF page provided:\n{input_desc}" if input_desc else None
            ] if text and text.strip()
        ]
        if not gemini_api_parts: raise ValueError("Could not construct valid prompt parts for Gemini.")

        gemini_api_call_response = call_gemini_api(
            image_base64=pdf_page_base64,
            prompt_parts=gemini_api_parts,
            mime_type="application/pdf"
        )
        metrics["time_sec_gemini_layout"] = time.time() - gemini_layout_start_time
        gemini_raw_text = gemini_api_call_response["text"]
        with open(os.path.join(genai_output_dir, f"page_{page_num_actual}_gemini_raw.txt"), "w", encoding="utf-8") as f: f.write(gemini_raw_text)

        metrics.update({
            "gemini_api_status": 200,
            "gemini_input_tokens": gemini_api_call_response.get("input_tokens", 0),
            "gemini_output_tokens": gemini_api_call_response.get("output_tokens", 0),
            "gemini_cost_usd": gemini_api_call_response.get("cost", 0.0)
        })

        gemini_json_str = extract_json_string(gemini_raw_text)
        metrics["gemini_response_length"] = len(gemini_json_str or "")
        gemini_json = json.loads(gemini_json_str) if gemini_json_str else {"error": "Empty JSON string from Gemini.", "page_number": page_num_actual}
        if not isinstance(gemini_json, dict): gemini_json = {"data": gemini_json, "error": "Gemini response not a dict", "page_number": page_num_actual}
        elif "page_number" not in gemini_json: gemini_json["page_number"] = page_num_actual
        print(f"✅ Received and parsed Gemini response for page {page_num_actual}")

    except json.JSONDecodeError as je:
        metrics["time_sec_gemini_layout"] = time.time() - gemini_layout_start_time
        print(f"⚠️ JSON DECODING ERROR (Gemini Call, Page {page_num_actual}): {je}")
        metrics.update({"gemini_api_status": 500, "gemini_error_message": f"JSONDecodeError: {je}"})
        gemini_json = {"error": f"JSONDecodeError from Gemini: {je}", "raw_output": gemini_raw_text, "page_number": page_num_actual}
    except Exception as e:
        metrics["time_sec_gemini_layout"] = time.time() - gemini_layout_start_time
        print(f"⚠️ Gemini API error (Page {page_num_actual}): {e}")
        metrics.update({"gemini_api_status": 500, "gemini_error_message": str(e)})
        gemini_json = {"error": f"Gemini API call failed: {e}", "page_number": page_num_actual}
    return gemini_json