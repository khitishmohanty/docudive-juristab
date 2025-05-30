import time
import json
import os
import re # Good to have if _clean_json_string or similar logic uses it

from services.gemini_client import call_gemini_api
# We are changing the prompt loading mechanism
from utils.prompt_loader import load_text_prompt # Changed from load_json_prompt
from utils.json_utils import _clean_json_string # Assuming this is your cleaning function

# Load the text prompt from gemini_layout_prompt.txt
gemini_layout_prompt_text = load_text_prompt("gemini_layout_prompt.txt")

def _call_gemini_for_layout(pdf_page_base64: str, page_num_actual: int, genai_output_dir: str, metrics: dict) -> dict:
    """Calls Gemini API for layout extraction using a text prompt, saves cleaned JSON, and updates metrics."""
    # Use the globally loaded text prompt
    global gemini_layout_prompt_text
    
    gemini_json_result_for_return = {} # This will be the dictionary returned by the function
    gemini_raw_text = ""
    gemini_layout_start_time = time.time()
    
    output_file_path = os.path.join(genai_output_dir, f"page_{page_num_actual}_gemini.json")

    try:
        # Construct gemini_api_parts directly from the loaded text prompt
        if not gemini_layout_prompt_text or not gemini_layout_prompt_text.strip():
            raise ValueError("Gemini layout prompt text from gemini_layout_prompt.txt is empty or invalid.")
        
        gemini_api_parts = [
            {"text": gemini_layout_prompt_text} # The entire text prompt is used here
        ]

        # Using call_gemini_api as defined in your gemini_client.py
        gemini_api_call_response = call_gemini_api(
            image_base64=pdf_page_base64,
            prompt_parts=gemini_api_parts, # Pass the new prompt parts
            mime_type="application/pdf"
        )
        metrics["time_sec_gemini_layout"] = time.time() - gemini_layout_start_time
        gemini_raw_text = gemini_api_call_response.get("text", "")
        
        metrics.update({
            "gemini_api_status": 200,
            "gemini_input_tokens": gemini_api_call_response.get("input_tokens", 0),
            "gemini_output_tokens": gemini_api_call_response.get("output_tokens", 0),
            "gemini_cost_usd": gemini_api_call_response.get("cost", 0.0)
        })

        cleaned_gemini_json_str = _clean_json_string(gemini_raw_text)
        metrics["gemini_response_length"] = len(cleaned_gemini_json_str or "")
        
        parsed_data_for_file = None

        if cleaned_gemini_json_str:
            try:
                parsed_data = json.loads(cleaned_gemini_json_str)
                parsed_data_for_file = parsed_data

                if isinstance(parsed_data, list):
                    gemini_json_result_for_return = {
                        "items": parsed_data,
                        "page_number": page_num_actual,
                        "_root_type": "list"
                    }
                    print(f"✅ Received and parsed Gemini response for page {page_num_actual}")
                elif isinstance(parsed_data, dict):
                    gemini_json_result_for_return = parsed_data
                    if "page_number" not in gemini_json_result_for_return:
                        gemini_json_result_for_return["page_number"] = page_num_actual
                    if "error" not in gemini_json_result_for_return:
                        print(f"✅ Received and parsed Gemini response for page {page_num_actual}")
                    else:
                        print(f"⚠️ Parsed Gemini response for page {page_num_actual} is a dictionary containing an error: {gemini_json_result_for_return.get('error')}")
                else:
                    error_msg = "Gemini response parsed to an unexpected data type (not list or dict)"
                    print(f"⚠️ {error_msg} for page {page_num_actual}. Type: {type(parsed_data).__name__}")
                    gemini_json_result_for_return = {
                        "error": error_msg,
                        "parsed_data_type": type(parsed_data).__name__,
                        "page_number": page_num_actual,
                        "raw_output_preview": gemini_raw_text[:200]
                    }
                    parsed_data_for_file = gemini_json_result_for_return
            except json.JSONDecodeError as je:
                print(f"⚠️ JSON DECODING ERROR on cleaned string (Gemini Call, Page {page_num_actual}): {je}")
                error_msg = f"JSONDecodeError on cleaned string: {je}"
                gemini_json_result_for_return = {
                    "error": error_msg,
                    "cleaned_string_preview": cleaned_gemini_json_str[:200] if cleaned_gemini_json_str else "None",
                    "raw_output_preview": gemini_raw_text[:200],
                    "page_number": page_num_actual
                }
                parsed_data_for_file = cleaned_gemini_json_str if cleaned_gemini_json_str else gemini_json_result_for_return
        else:
            error_msg = "Could not extract/clean valid JSON string from Gemini response."
            if not gemini_raw_text: error_msg = "Empty raw response from Gemini."
            print(f"⚠️ {error_msg} for page {page_num_actual}.")
            gemini_json_result_for_return = {
                "error": error_msg,
                "raw_output_preview": gemini_raw_text[:200],
                "page_number": page_num_actual
            }
            parsed_data_for_file = gemini_json_result_for_return

        try:
            with open(output_file_path, "w", encoding="utf-8") as f:
                if isinstance(parsed_data_for_file, (dict, list)):
                    json.dump(parsed_data_for_file, f, indent=2, ensure_ascii=False)
                elif isinstance(parsed_data_for_file, str):
                    f.write(parsed_data_for_file)
                else:
                    json.dump({"error": "No valid data to save after cleaning/parsing attempts.",
                            "raw_output_preview": gemini_raw_text[:200]}, f, indent=2, ensure_ascii=False)
        except Exception as e_save:
            print(f"⚠️ Error saving processed Gemini data to file {output_file_path}: {e_save}")
            if isinstance(gemini_json_result_for_return, dict) and "error" not in gemini_json_result_for_return:
                gemini_json_result_for_return["error_saving_file"] = str(e_save)


    except json.JSONDecodeError as je: # Catches errors primarily from json.dumps if input data to it is bad
        if 'gemini_layout_start_time' in locals() and metrics.get("time_sec_gemini_layout", 0) == 0:
            metrics["time_sec_gemini_layout"] = time.time() - gemini_layout_start_time
        print(f"⚠️ Outer JSON DECODING ERROR (Gemini Call, Page {page_num_actual}): {je}")
        metrics.update({"gemini_api_status": 500, "gemini_error_message": f"JSONDecodeError: {je}"})
        gemini_json_result_for_return = {"error": f"Outer JSONDecodeError from Gemini: {je}", "raw_output": gemini_raw_text, "page_number": page_num_actual}
    except ValueError as ve: # Catches errors from prompt construction (e.g., empty prompt text)
        if 'gemini_layout_start_time' in locals() and metrics.get("time_sec_gemini_layout", 0) == 0:
            metrics["time_sec_gemini_layout"] = time.time() - gemini_layout_start_time
        print(f"⚠️ Value Error (Gemini Call construction, Page {page_num_actual}): {ve}")
        metrics.update({"gemini_api_status": 500, "gemini_error_message": str(ve)})
        gemini_json_result_for_return = {"error": f"Gemini prompt construction error: {ve}", "page_number": page_num_actual}
    except Exception as e: # Catches other errors like API call failures
        if 'gemini_layout_start_time' in locals() and metrics.get("time_sec_gemini_layout", 0) == 0:
            metrics["time_sec_gemini_layout"] = time.time() - gemini_layout_start_time
        print(f"⚠️ Gemini API error (Page {page_num_actual}): {e.__class__.__name__} - {e}")
        metrics.update({"gemini_api_status": 500, "gemini_error_message": f"{e.__class__.__name__}: {e}"})
        gemini_json_result_for_return = {"error": f"Gemini API call failed: {e}", "page_number": page_num_actual}

    if isinstance(gemini_json_result_for_return, dict) and "page_number" not in gemini_json_result_for_return:
        gemini_json_result_for_return["page_number"] = page_num_actual
        
    return gemini_json_result_for_return