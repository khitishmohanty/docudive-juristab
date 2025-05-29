import time
import json
import os
from typing import Optional, Dict # Removed List, Any as they are not directly used in this simplified version's signature

# Import the new consolidated API calling function
from services.gemini_client import call_gemini_api
from utils.prompt_loader import load_text_prompt
from utils.json_utils import _clean_json_string

# Load the text prompt from gemini_layout_prompt.txt
# IMPORTANT: This prompt text MUST be updated to instruct Gemini how to use the two pages
# based on the new calling convention (media_item1 is current, media_item2 is previous).
# See suggestions at the end of this response.
gemini_layout_prompt_text = load_text_prompt("gemini_layout_prompt.txt")

def _call_gemini_for_layout(
    current_pdf_page_base64: str,
    prev_pdf_page_base64: Optional[str], # Previous page's base64
    page_num_actual: int,
    genai_output_dir: str,
    metrics: dict
) -> dict:
    """
    Calls Gemini API using the new call_gemini_api for layout extraction.
    It sends the current page as media_item1 and the previous page (if available) as media_item2.
    Saves cleaned JSON and updates metrics.
    """
    global gemini_layout_prompt_text
    
    gemini_json_result_for_return = {}
    gemini_raw_text = ""
    gemini_layout_start_time = time.time()
    
    # Using a slightly different name to distinguish from single-page or old multi-modal outputs if needed
    output_file_path = os.path.join(genai_output_dir, f"page_{page_num_actual}_gemini_layout.json")

    try:
        if not current_pdf_page_base64: # Basic check
            raise ValueError("Current PDF page base64 string is missing.")
        if not gemini_layout_prompt_text or not gemini_layout_prompt_text.strip():
            raise ValueError("Gemini layout prompt text from gemini_layout_prompt.txt is empty or invalid.")

        # The prompt text itself. Its content should guide the model on how to interpret
        # media_item1 (current) and media_item2 (previous, if present).
        prompt_for_api = gemini_layout_prompt_text
        
        # Prepare arguments for call_gemini_api
        # media_item1 is always the current page
        # media_item2 is the previous page, if it exists
        
        media_item1_mime_type = "application/pdf" # Assuming PDF inputs
        media_item2_mime_type = "application/pdf" if prev_pdf_page_base64 else None

        # Make the API call
        gemini_api_call_response = call_gemini_api(
            prompt_text=prompt_for_api,
            media_item1_base64=current_pdf_page_base64,
            media_item1_mime_type=media_item1_mime_type,
            media_item2_base64=prev_pdf_page_base64, # Will be None if no previous page
            media_item2_mime_type=media_item2_mime_type,
            # generation_config can be passed here if needed, e.g., {"responseMimeType": "application/json"}
        )
        
        metrics["time_sec_gemini_layout"] = time.time() - gemini_layout_start_time
        gemini_raw_text = gemini_api_call_response.get("text", "")
        
        metrics.update({
            "gemini_api_status": 200, # Assuming success if no exception from call_gemini_api
            "gemini_input_tokens": gemini_api_call_response.get("input_tokens", 0),
            "gemini_output_tokens": gemini_api_call_response.get("output_tokens", 0),
            "gemini_cost_usd": gemini_api_call_response.get("cost_usd", 0.0) # Uses 'cost_usd'
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
                    parsed_data_for_file = gemini_json_result_for_return # Save this error structure
            except json.JSONDecodeError as je:
                print(f"⚠️ JSON DECODING ERROR on cleaned string (Gemini Call, Page {page_num_actual}): {je}")
                error_msg = f"JSONDecodeError on cleaned string: {je}"
                gemini_json_result_for_return = {
                    "error": error_msg,
                    "cleaned_string_preview": cleaned_gemini_json_str[:200] if cleaned_gemini_json_str else "None",
                    "raw_output_preview": gemini_raw_text[:200],
                    "page_number": page_num_actual
                }
                # Save the problematic string for debugging
                parsed_data_for_file = {"error": error_msg, "problematic_cleaned_json_string": cleaned_gemini_json_str, "raw_response_preview": gemini_raw_text[:500]}
        else: # cleaned_gemini_json_str is empty
            error_msg = "Could not extract/clean valid JSON string from Gemini response."
            if not gemini_raw_text: error_msg = "Empty raw response from Gemini."
            print(f"⚠️ {error_msg} for page {page_num_actual}.")
            gemini_json_result_for_return = {
                "error": error_msg,
                "raw_output_preview": gemini_raw_text[:200],
                "page_number": page_num_actual
            }
            parsed_data_for_file = gemini_json_result_for_return # Save this error structure

        # Save the processed data or error structure to a file
        try:
            with open(output_file_path, "w", encoding="utf-8") as f:
                if isinstance(parsed_data_for_file, (dict, list)):
                    json.dump(parsed_data_for_file, f, indent=2, ensure_ascii=False)
                # if parsed_data_for_file was a string (e.g. unparseable JSON) it's handled if it was assigned to gemini_json_result_for_return and that got assigned to parsed_data_for_file
                elif isinstance(parsed_data_for_file, str): 
                     # This case should ideally be minimized by ensuring parsed_data_for_file is a dict (even if an error dict)
                    f.write(parsed_data_for_file)
                else: # Catch-all if parsed_data_for_file is None or unexpected type
                    json.dump({"error": "No valid data to save after cleaning/parsing attempts.",
                               "raw_output_preview": gemini_raw_text[:200],
                               "page_number": page_num_actual}, f, indent=2, ensure_ascii=False)
        except Exception as e_save:
            print(f"⚠️ Error saving processed Gemini data to file {output_file_path}: {e_save}")
            # Attempt to add saving error to the in-memory result if it's a dict and doesn't already have an error
            if isinstance(gemini_json_result_for_return, dict) and "error" not in gemini_json_result_for_return:
                gemini_json_result_for_return["error_saving_file"] = str(e_save)

    except ValueError as ve: # Catches errors from prompt loading or initial checks
        if 'gemini_layout_start_time' in locals() and metrics.get("time_sec_gemini_layout", 0) == 0:
            metrics["time_sec_gemini_layout"] = time.time() - gemini_layout_start_time
        print(f"⚠️ Value Error (Gemini Call construction, Page {page_num_actual}): {ve}")
        metrics.update({"gemini_api_status": 500, "gemini_error_message": str(ve)})
        gemini_json_result_for_return = {"error": f"Gemini call setup error: {ve}", "page_number": page_num_actual}
    except RuntimeError as rte: # Catch errors raised by call_gemini_api (e.g. API connection, HTTP errors)
        if 'gemini_layout_start_time' in locals() and metrics.get("time_sec_gemini_layout", 0) == 0:
            metrics["time_sec_gemini_layout"] = time.time() - gemini_layout_start_time
        print(f"⚠️ Gemini API Runtime Error (Page {page_num_actual}): {rte}")
        metrics.update({"gemini_api_status": 500, "gemini_error_message": str(rte)}) # Or a more specific status if available from exception
        gemini_json_result_for_return = {"error": f"Gemini API call failed: {rte}", "page_number": page_num_actual}
    except Exception as e: # Catches other unexpected errors
        if 'gemini_layout_start_time' in locals() and metrics.get("time_sec_gemini_layout", 0) == 0:
            metrics["time_sec_gemini_layout"] = time.time() - gemini_layout_start_time
        print(f"⚠️ Unexpected error in Gemini layout call (Page {page_num_actual}): {e.__class__.__name__} - {e}")
        metrics.update({"gemini_api_status": 500, "gemini_error_message": f"{e.__class__.__name__}: {e}"})
        gemini_json_result_for_return = {"error": f"Unexpected error: {e}", "page_number": page_num_actual}

    # Ensure page number is in the final dictionary, especially for error cases
    if isinstance(gemini_json_result_for_return, dict) and "page_number" not in gemini_json_result_for_return:
        gemini_json_result_for_return["page_number"] = page_num_actual
        
    return gemini_json_result_for_return