import time
import json
import os

from services.openai_client import call_openai_with_pdf 
from utils.json_utils import extract_json_string
from utils.prompt_loader import load_text_prompt

openai_prompt_text = load_text_prompt("openai_layout_prompt.txt")

def _call_openai_for_layout(temp_pdf_page_path: str, page_num_actual: int, genai_output_dir: str, metrics: dict) -> dict:
    """Calls OpenAI API for layout extraction and updates metrics."""
    global openai_prompt_text
    openai_json = {}
    openai_raw_text = ""
    openai_layout_start_time = time.time()
    try:
        openai_api_call_response = call_openai_with_pdf(
            pdf_path=temp_pdf_page_path,
            prompt=openai_prompt_text
        )
        metrics["time_sec_openai_layout"] = time.time() - openai_layout_start_time
        openai_raw_text = openai_api_call_response["text"]
        with open(os.path.join(genai_output_dir, f"page_{page_num_actual}_openai_raw.txt"), "w", encoding="utf-8") as f: f.write(openai_raw_text)

        metrics.update({
            "openai_api_status": 200,
            "openai_input_tokens": openai_api_call_response.get("input_tokens", 0),
            "openai_output_tokens": openai_api_call_response.get("output_tokens", 0),
            "openai_cost_usd": openai_api_call_response.get("cost", 0.0)
        })

        openai_json_str = extract_json_string(openai_raw_text)
        metrics["openai_response_length"] = len(openai_json_str or "")
        openai_json = json.loads(openai_json_str) if openai_json_str else {"error": "Empty JSON string from OpenAI.", "page_number": page_num_actual}
        if not isinstance(openai_json, dict): openai_json = {"data": openai_json, "error": "OpenAI response not a dict", "page_number": page_num_actual}
        elif "page_number" not in openai_json: openai_json["page_number"] = page_num_actual
        print(f"✅ Received and parsed OpenAI response for page {page_num_actual}")

    except json.JSONDecodeError as je:
        metrics["time_sec_openai_layout"] = time.time() - openai_layout_start_time
        print(f"⚠️ JSON DECODING ERROR (OpenAI Call, Page {page_num_actual}): {je}")
        metrics.update({"openai_api_status": 500, "openai_error_message": f"JSONDecodeError: {je}"})
        openai_json = {"error": f"JSONDecodeError from OpenAI: {je}", "raw_output": openai_raw_text, "page_number": page_num_actual}
    except Exception as e:
        metrics["time_sec_openai_layout"] = time.time() - openai_layout_start_time
        print(f"⚠️ OpenAI API error (Page {page_num_actual}): {e}")
        metrics.update({"openai_api_status": 500, "openai_error_message": str(e)})
        openai_json = {"error": f"OpenAI API call failed: {e}", "page_number": page_num_actual}
    return openai_json