import time
import json
import os

from core.consolidator import consolidate_responses
from utils.json_utils import attach_page_number_tag
from services.openai_client import call_openai_with_json, call_openai_with_pdf 
from utils.prompt_loader import load_text_prompt
from utils.json_utils import extract_json_string

consolidation_prompt_text = load_text_prompt("consolidation_prompt.txt")
sanitize_prompt_text = load_text_prompt("sanitize_prompt.txt")
output_verification_prompt_text = load_text_prompt("output_verification_prompt.txt")

def _consolidate_sanitize_verify(
    pdf_page_base64: str,
    gemini_json: dict,
    openai_json: dict,
    page_num_actual: int,
    genai_output_dir: str,
    temp_pdf_page_path: str,
    metrics: dict
) -> dict:
    """Consolidates, sanitizes, and verifies the AI responses, updating metrics."""
    global consolidation_prompt_text, sanitize_prompt_text, output_verification_prompt_text
    consolidated_response_json = {}
    sanitized_response_json = {}

    try:
        # --- Consolidate ---
        consolidation_start_time = time.time()
        consolidated_response_json = consolidate_responses(
            pdf_page_base64=pdf_page_base64,
            gemini_json_input=gemini_json,
            openai_json_input=openai_json,
            prompt_text=consolidation_prompt_text
        )
        metrics["time_sec_consolidation"] = time.time() - consolidation_start_time
        consolidated_response_json = attach_page_number_tag(consolidated_response_json, page_num_actual)

        metrics.update({
            "genai_response_consolidation_status": 200 if consolidated_response_json and not consolidated_response_json.get("error") else 500,
            "genai_response_consolidation_response_length": len(json.dumps(consolidated_response_json)),
            "json_consolidation_error_message": consolidated_response_json.get("error_details", consolidated_response_json.get("error","")) if consolidated_response_json.get("error") else "",
            "consolidation_input_tokens": consolidated_response_json.get("_consolidation_input_tokens", 0),
            "consolidation_output_tokens": consolidated_response_json.get("_consolidation_output_tokens", 0),
            "consolidation_cost_usd": consolidated_response_json.get("_consolidation_cost_usd", 0.0)
        })
        for key in ["_consolidation_input_tokens", "_consolidation_output_tokens", "_consolidation_cost_usd"]:
            if isinstance(consolidated_response_json, dict) and key in consolidated_response_json: del consolidated_response_json[key]
        consolidated_output_path = os.path.join(genai_output_dir, f"page_{page_num_actual}_consolidated.json")
        with open(consolidated_output_path, "w", encoding="utf-8") as f: json.dump(consolidated_response_json, f, indent=2, ensure_ascii=False)
        print(f"✅ JSON responses consolidated for page {page_num_actual} and saved.")

        # --- Sanitize JSON ---
        sanitize_response = {}
        sanitize_start_time = time.time()
        try:
            sanitize_response = call_openai_with_json(json_file_path=consolidated_output_path, prompt=sanitize_prompt_text)
            metrics["time_sec_sanitize"] = time.time() - sanitize_start_time
            sanitized_output_path = os.path.join(genai_output_dir, f"page_{page_num_actual}_sanitized.json")
            with open(sanitized_output_path, "w", encoding="utf-8") as f: f.write(sanitize_response.get("text", ""))
            print(f"✅ Sanitized JSON saved for page {page_num_actual}")
            metrics.update({
                "sanitize_input_tokens": sanitize_response.get("input_tokens", 0),
                "sanitize_output_tokens": sanitize_response.get("output_tokens", 0),
                "sanitize_cost_usd": sanitize_response.get("cost", 0.0),
                "sanitize_status": "success"
            })
        except Exception as e_sanitize:
            metrics["time_sec_sanitize"] = time.time() - sanitize_start_time
            print(f"⚠️ Sanitization failed for page {page_num_actual}: {e_sanitize}")
            metrics["sanitize_status"] = f"fail - {str(e_sanitize)}"

        # --- Verification Step ---
        current_page_verification_status = "failed - verification condition not met"
        sanitized_text_content = sanitize_response.get("text", "")

        if not sanitized_text_content.strip():
            print(f"⚠️ Empty sanitized response for page {page_num_actual}, using consolidated for verification if available.")
            sanitized_response_json = {"error": "Sanitized response was empty", "page_number": page_num_actual}
            current_page_verification_status = "fail - empty sanitized text"
        else:
            try:
                sanitized_response_json = json.loads(sanitized_text_content)
                if not isinstance(sanitized_response_json, dict):
                    sanitized_response_json = {"parsed_non_dict_content": sanitized_response_json, "page_number": page_num_actual}
                elif "page_number" not in sanitized_response_json:
                    sanitized_response_json["page_number"] = page_num_actual
            except json.JSONDecodeError as e_json_decode_sanitize:
                print(f"⚠️ Failed to parse sanitized JSON for page {page_num_actual}: {e_json_decode_sanitize}")
                sanitized_response_json = {
                    "error": "Failed to parse sanitized JSON", "exception": str(e_json_decode_sanitize),
                    "raw_text": sanitized_text_content, "page_number": page_num_actual
                }
                current_page_verification_status = "fail - sanitized JSON decode error"

        if isinstance(sanitized_response_json, dict) and "error" not in sanitized_response_json :
            verification_start_time = time.time()
            try:
                verification_api_main_prompt = (
                    f"{output_verification_prompt_text}\n\n"
                    f"Sanitized JSON to verify for page {page_num_actual}:\n"
                    f"{json.dumps(sanitized_response_json, indent=2)}"
                )
                print(f"🔍 Content verification for page {page_num_actual} started (using PDF page).")
                verification_response = call_openai_with_pdf(
                    pdf_path=temp_pdf_page_path,
                    prompt=verification_api_main_prompt
                )
                metrics["time_sec_verification"] = time.time() - verification_start_time
                verification_text_result = verification_response["text"]
                metrics.update({
                    "verification_input_tokens": verification_response.get("input_tokens", 0),
                    "verification_output_tokens": verification_response.get("output_tokens", 0),
                    "verification_cost_usd": verification_response.get("cost", 0.0)
                })
                if "pass" in verification_text_result.lower(): current_page_verification_status = "pass"
                elif "fail" in verification_text_result.lower(): current_page_verification_status = "fail"
                else: current_page_verification_status = f"fail - unclear: {verification_text_result[:100].strip()}"
                print(f"✅ Verification status for page {page_num_actual}: {current_page_verification_status}")
            except Exception as e_verify:
                metrics["time_sec_verification"] = time.time() - verification_start_time
                print(f"⚠️ Verification API error for page {page_num_actual}: {e_verify}")
                current_page_verification_status = f"fail - verification API error: {str(e_verify)}"
        elif isinstance(sanitized_response_json, dict) and "error" in sanitized_response_json:
            current_page_verification_status = f"fail - input to verification was error object: {sanitized_response_json.get('error', 'unknown error')}"

        metrics["verification_status"] = current_page_verification_status
        if isinstance(sanitized_response_json, dict):
            sanitized_response_json["page_verification_status"] = current_page_verification_status
        else:
            sanitized_response_json = {
                "error": "Sanitized response was not a dictionary before final status assignment",
                "original_content_type": type(sanitized_response_json).__name__,
                "page_number": page_num_actual,
                "page_verification_status": current_page_verification_status
            }
        return sanitized_response_json

    except Exception as e_block:
        print(f"⚠️ Error in main processing block (consolidate/sanitize/verify) for page {page_num_actual}: {e_block}")
        metrics.update({
            "genai_response_consolidation_status": metrics.get("genai_response_consolidation_status") or 500,
            "json_consolidation_error_message": (metrics.get("json_consolidation_error_message", "") + f"; Block error: {str(e_block)}").strip(),
            "verification_status": "fail - processing block error"
        })
        return {
            "error": f"Main processing block failure for page {page_num_actual}", "details": str(e_block),
            "page_number": page_num_actual, "page_verification_status": metrics["verification_status"],
            "gemini_attempt_available": bool(gemini_json),
            "openai_attempt_available": bool(openai_json),
            "consolidation_attempt_available": bool(consolidated_response_json) and consolidated_response_json != {}
        }
        
        
def _extract_and_save_hyperlinks_for_page(
    temp_pdf_page_path: str,
    page_num_actual: int,
    genai_output_dir: str,
    metrics: dict,
    prompt_text: str 
) -> dict:
    """
    Extracts hyperlinks from a single PDF page, updates metrics,
    and saves the raw and structured results.
    """
    extracted_data = {"hyperlinks": [], "status": "not_attempted", "error_message": ""}
    start_time = time.time()
    raw_text_for_error = "N/A"

    try:
        # Ensure call_openai_with_pdf is accessible
        response = call_openai_with_pdf(
            pdf_path=temp_pdf_page_path,
            prompt=prompt_text
        )
        metrics["time_sec_hyperlink_extraction"] = time.time() - start_time
        raw_text_for_error = response["text"]

        # Save raw hyperlink output text
        #with open(os.path.join(genai_output_dir, f"page_{page_num_actual}_hyperlinks_raw.txt"), "w", encoding="utf-8") as f:
        #    f.write(raw_text_for_error)

        metrics.update({
            "hyperlink_input_tokens": response.get("input_tokens", 0),
            "hyperlink_output_tokens": response.get("output_tokens", 0),
            "hyperlink_cost_usd": response.get("cost", 0.0),
        })

        # Ensure extract_json_string is accessible
        json_str = extract_json_string(raw_text_for_error)
        if json_str:
            parsed_hyperlinks = json.loads(json_str)
            if not isinstance(parsed_hyperlinks, list):
                metrics["hyperlink_extraction_status"] = "fail_output_not_list"
                metrics["hyperlink_error_message"] = "Hyperlink response from AI was not a list."
                extracted_data["hyperlinks"] = [{"error": "Hyperlink response not a list", "raw_output": parsed_hyperlinks}]
                extracted_data["error_message"] = metrics["hyperlink_error_message"]
            else:  # Success
                metrics["hyperlink_extraction_status"] = "success"
                extracted_data["hyperlinks"] = parsed_hyperlinks
            metrics["hyperlinks_found_count"] = len(parsed_hyperlinks) if isinstance(parsed_hyperlinks, list) else 0
        else:  # No JSON found or empty response
            metrics["hyperlink_extraction_status"] = "success_empty_json"
            metrics["hyperlinks_found_count"] = 0
            extracted_data["hyperlinks"] = []

        extracted_data["status"] = metrics["hyperlink_extraction_status"]
        print(f"🔗 Hyperlink extraction for page {page_num_actual} status: {metrics['hyperlink_extraction_status']}. Found: {metrics['hyperlinks_found_count']}")

    except json.JSONDecodeError as je:
        if metrics.get("time_sec_hyperlink_extraction", 0.0) == 0.0:
            metrics["time_sec_hyperlink_extraction"] = time.time() - start_time
        print(f"⚠️ JSON DECODING ERROR (Hyperlink Extraction, Page {page_num_actual}): {je}")
        metrics.update({"hyperlink_extraction_status": "fail_json_decode", "hyperlink_error_message": f"JSONDecodeError: {je}"})
        extracted_data = {"hyperlinks": [{"error": f"JSONDecodeError: {je}", "raw_output": raw_text_for_error}],
                        "status": "fail_json_decode", "error_message": str(je)}
    except Exception as e_hyper:
        if metrics.get("time_sec_hyperlink_extraction", 0.0) == 0.0:
            metrics["time_sec_hyperlink_extraction"] = time.time() - start_time
        print(f"⚠️ Hyperlink extraction error (Page {page_num_actual}): {e_hyper}")
        metrics.update({"hyperlink_extraction_status": "fail_api_error", "hyperlink_error_message": str(e_hyper)})
        extracted_data = {"hyperlinks": [{"error": f"API call failed: {e_hyper}"}],
                        "status": "fail_api_error", "error_message": str(e_hyper)}

    # Save the structured hyperlink data (or error info) to its own JSON file
    hyperlinks_json_output_path = os.path.join(genai_output_dir, f"page_{page_num_actual}_hyperlinks.json")
    try:
        with open(hyperlinks_json_output_path, "w", encoding="utf-8") as f_json:
            json.dump(extracted_data, f_json, indent=2, ensure_ascii=False)
        print(f"💾 Saved extracted hyperlinks for page {page_num_actual}")
    except Exception as e_save_hyper_json:
        print(f"⚠️ Failed to save hyperlinks JSON for page {page_num_actual} to {hyperlinks_json_output_path}: {e_save_hyper_json}")

    return extracted_data