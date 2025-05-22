import os
import re
import sys
import json
import base64
import time
from pathlib import Path
import pandas as pd

# Add project root to PYTHONPATH
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../"))
sys.path.insert(0, project_root)

# Local imports
from utils.pdf_to_image_converter import convert_pdf_to_images
from services.gemini_client import call_gemini_api
from services.openai_client import call_openai_api # Assuming this client is correctly set up
from utils.csv_excel_converter import convert_json_to_csv_and_excel
from utils.html_converter import convert_json_to_html
from utils.prompt_loader import load_text_prompt, load_json_prompt
from utils.pdf_text_extractor import (
    extract_text_from_pdf_page,
    extract_text_from_ocr,
    is_fidelity_preserved,
)
from services.gemini_client import call_gemini_with_pdf
from services.openai_client import call_openai_api, call_openai_with_json



# Load prompts from file
gemini_prompt = load_json_prompt("gemini_layout_prompt.json")
openai_prompt = load_text_prompt("openai_layout_prompt.txt")
consolidation_prompt = load_text_prompt("consolidation_prompt.txt")
enrichment_prompt = load_json_prompt("enrichment_prompt.json")
output_verification_prompt_text = load_text_prompt("output_verification_prompt.txt")
sanitize_prompt_text = load_text_prompt("sanitize_prompt.txt")



def extract_json_string(raw_text: str) -> str:
    """Extracts the first valid JSON array or object from a raw string."""
    json_markdown_match = re.search(r"```json\s*([\s\S]*?)\s*```", raw_text, re.DOTALL)
    if json_markdown_match:
        return json_markdown_match.group(1).strip()
    json_pattern = r"(\[.*?\]|\{.*?\})"
    matches = re.findall(json_pattern, raw_text, re.DOTALL)
    if matches:
        for match in matches:
            try:
                json.loads(match)
                return match
            except json.JSONDecodeError:
                continue
    return ""


def encode_image_to_base64(image_path: str) -> str:
    """Encodes an image file to a base64 string."""
    with open(image_path, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode("utf-8")

def encode_pdf_to_base64(pdf_path: str) -> str:
    with open(pdf_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def consolidate_responses(image_base64: str, gemini_json_input, openai_json_input, prompt_text: str) -> dict:
    global gemini_prompt

    try:
        # Extract details from the gemini_prompt
        prompt_details = gemini_prompt.get("prompt_details", {})
        task = prompt_details.get("task_description", "Consolidate the provided JSON outputs based on the task.")
        schema_obj = prompt_details.get("output_format_instructions", {})
        schema_str = json.dumps(schema_obj, indent=2)
        image_desc = prompt_details.get("input_image_description", "")

        # Compose the full consolidation prompt
        prompt_parts = [
            {"text": prompt_text},
            {"text": f"Original Task Description: {task}"},
            {"text": f"Image context (if relevant for consolidation): {image_desc}"},
            {"text": f"Strictly adhere to this Output JSON Schema:\n{schema_str}"},
            {"text": f"GEMINI RESPONSE TO CONSOLIDATE:\n{json.dumps(gemini_json_input, indent=2)}"},
            {"text": f"OPENAI RESPONSE TO CONSOLIDATE:\n{json.dumps(openai_json_input, indent=2)}"}
        ]

        # Call Gemini for consolidation
        gemini_response = call_gemini_api(image_base64, prompt_parts)
        result_text = gemini_response["text"]
        cleaned_json_str = extract_json_string(result_text)

        if cleaned_json_str:
            parsed_result = json.loads(cleaned_json_str)
            parsed_result["_consolidation_input_tokens"] = gemini_response.get("input_tokens", 0)
            parsed_result["_consolidation_output_tokens"] = gemini_response.get("output_tokens", 0)
            parsed_result["_consolidation_cost_usd"] = gemini_response.get("cost", 0.0)
            return parsed_result

        return {
            "error": "Consolidation failed to produce valid JSON",
            "gemini_original": gemini_json_input,
            "openai_original": openai_json_input,
            "verification_status_internal": "Fallback_NoValidJson"
        }

    except json.JSONDecodeError as je:
        print(f"❌ Consolidation JSON DECODING ERROR: {je}")
        print(f"Problematic JSON string during consolidation was: >>>\n{cleaned_json_str}\n<<<")
        return {
            "gemini_original": gemini_json_input,
            "openai_original": openai_json_input,
            "verification_status_internal": "Fallback_JsonDecodeError",
            "error_details": str(je)
        }

    except Exception as e:
        print(f"❌ Consolidation failed with unexpected error: {e}")
        return {
            "gemini_original": gemini_json_input,
            "openai_original": openai_json_input,
            "verification_status_internal": "Fallback_Exception",
            "error_details": str(e)
        }

def attach_page_number_tag(consolidated, page_number: int):
    """Adds 'page_number' to each node if it's not already present."""
    if isinstance(consolidated, list):
        for node in consolidated:
            if isinstance(node, dict) and "page_number" not in node:
                node["page_number"] = page_number
    elif isinstance(consolidated, dict):
        if "document_elements" in consolidated and isinstance(consolidated["document_elements"], list):
            for node in consolidated["document_elements"]:
                if isinstance(node, dict) and "page_number" not in node:
                    node["page_number"] = page_number
        elif "page_number" not in consolidated:
            consolidated["page_number"] = page_number
    return consolidated



def process_pdf(pdf_path: str, output_dir: str, image_dir: str, poppler_path: str = None) -> list:
    os.makedirs(image_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)
    genai_output_dir = os.path.join(output_dir, "genai_outputs")
    os.makedirs(genai_output_dir, exist_ok=True)

    #print(f"📄 Converting PDF to images from: {pdf_path}")
    print(f"📄 Converting PDF to images")
    image_paths = convert_pdf_to_images(pdf_path, image_dir, poppler_path=poppler_path)

    all_responses = []
    page_metrics = []

    global gemini_prompt
    global openai_prompt
    global consolidation_prompt # This is the text of consolidation_prompt.txt
    global output_verification_prompt_text # Ensure this global is used or passed

    for page_num, img_path in enumerate(image_paths, start=1):
        print("---------------------")
        print(f"📤 Processing page: {page_num}")
        metrics = {
            "page": page_num,
            "gemini_api_status": None, "gemini_response_length": 0, "gemini_error_message": "",
            "gemini_input_tokens": 0,
            "gemini_output_tokens": 0,
            "gemini_cost_usd": 0.0,
            "openai_api_status": None, "openai_response_length": 0, "openai_error_message": "",
            "openai_input_tokens": 0,
            "openai_output_tokens": 0,
            "openai_cost_usd": 0.0,
            "genai_response_consolidation_status": None, "genai_response_consolidation_response_length": 0,
            "json_consolidation_error_message": "",
            "consolidation_input_tokens": 0,
            "consolidation_output_tokens": 0,
            "consolidation_cost_usd": 0.0,
            "sanitize_input_tokens": 0,
            "sanitize_output_tokens": 0,
            "sanitize_cost_usd": 0.0,
            "sanitize_status": "not attempted",
            "verification_status": "failed - verification not performed", # Default status for the new verification
            "verification_input_tokens": 0,
            "verification_output_tokens": 0,
            "verification_cost_usd": 0.0
        }
        gemini_json_str = ""
        openai_json_str = ""
        consolidated_response_json = {}
        sanitize_response = {} 
        sanitized_response_json = {}
        image_base64 = None
        
        try: # Outermost try for the entire page processing
            image_base64 = encode_image_to_base64(img_path)

            # --- Call Gemini ---
            gemini_raw = "" # Initialize for error reporting
            try:
                prompt_details = gemini_prompt.get("prompt_details", {})
                task_description = prompt_details.get("task_description", "")
                output_format_instructions_obj = prompt_details.get("output_format_instructions", {})
                input_image_desc_from_prompt = prompt_details.get("input_image_description", "")

                gemini_api_parts = [
                    {"text": text} for text in [
                        task_description,
                        f"Please adhere strictly to the following output format and schema:\n{json.dumps(output_format_instructions_obj, indent=2)}" if output_format_instructions_obj else None,
                        f"Contextual description of the image provided:\n{input_image_desc_from_prompt}" if input_image_desc_from_prompt else None
                    ] if text and text.strip()
                ]
                if not gemini_api_parts: raise ValueError("Could not construct any valid text prompt parts for Gemini.")

                gemini_api_call_response = call_gemini_api(image_base64, gemini_api_parts)
                gemini_raw = gemini_api_call_response["text"]
                with open(os.path.join(genai_output_dir, f"page_{page_num}_gemini_raw.txt"), "w", encoding="utf-8") as f: f.write(gemini_raw)
                
                metrics["gemini_api_status"] = 200
                metrics["gemini_input_tokens"] = gemini_api_call_response.get("input_tokens", 0)
                metrics["gemini_output_tokens"] = gemini_api_call_response.get("output_tokens", 0)
                metrics["gemini_cost_usd"] = gemini_api_call_response.get("cost", 0.0)
                
                gemini_json_str = extract_json_string(gemini_raw)
                metrics["gemini_response_length"] = len(gemini_json_str or "")
                gemini_json = json.loads(gemini_json_str) if gemini_json_str else {"error": "Empty JSON string from Gemini.", "page_number": page_num}
                if not isinstance(gemini_json, dict): gemini_json = {"data": gemini_json, "error": "Gemini response not a dict", "page_number": page_num}
                elif "page_number" not in gemini_json: gemini_json["page_number"] = page_num
                print("✅ Received and parsed Gemini response")
            except json.JSONDecodeError as je:
                print(f"⚠️ JSON DECODING ERROR (Primary Gemini Call): {je}")
                metrics["gemini_api_status"] = 500; metrics["gemini_error_message"] = f"JSONDecodeError: {je}"
                gemini_json = {"error": f"JSONDecodeError from Gemini: {je}", "raw_output": gemini_raw, "page_number": page_num}
            except Exception as e:
                print(f"⚠️ Gemini API error: {e}")
                metrics["gemini_api_status"] = 500; metrics["gemini_error_message"] = str(e)
                gemini_json = {"error": f"Gemini API call failed: {e}", "page_number": page_num}

            # --- Call OpenAI ---
            openai_raw = "" # Initialize for error reporting
            try:
                openai_api_call_response = call_openai_api(openai_prompt, image_base64=image_base64)
                openai_raw = openai_api_call_response["text"]
                with open(os.path.join(genai_output_dir, f"page_{page_num}_openai_raw.txt"), "w", encoding="utf-8") as f: f.write(openai_raw)

                metrics["openai_api_status"] = 200
                metrics["openai_input_tokens"] = openai_api_call_response.get("input_tokens", 0)
                metrics["openai_output_tokens"] = openai_api_call_response.get("output_tokens", 0)
                metrics["openai_cost_usd"] = openai_api_call_response.get("cost", 0.0)

                openai_json_str = extract_json_string(openai_raw)
                metrics["openai_response_length"] = len(openai_json_str or "")
                openai_json = json.loads(openai_json_str) if openai_json_str else {"error": "Empty JSON string from OpenAI.", "page_number": page_num}
                if not isinstance(openai_json, dict): openai_json = {"data": openai_json, "error": "OpenAI response not a dict", "page_number": page_num}
                elif "page_number" not in openai_json: openai_json["page_number"] = page_num
                print("✅ Received and parsed OpenAI response")
            except json.JSONDecodeError as je:
                print(f"⚠️ JSON DECODING ERROR (OpenAI Call): {je}")
                metrics["openai_api_status"] = 500; metrics["openai_error_message"] = f"JSONDecodeError: {je}"
                openai_json = {"error": f"JSONDecodeError from OpenAI: {je}", "raw_output": openai_raw, "page_number": page_num}
            except Exception as e:
                print(f"⚠️ OpenAI API error: {e}")
                metrics["openai_api_status"] = 500; metrics["openai_error_message"] = str(e)
                openai_json = {"error": f"OpenAI API call failed: {e}", "page_number": page_num}


            # --- Consolidate, Sanitize, Verify Block ---
            try:
                consolidated_response_json = consolidate_responses(
                    image_base64=image_base64,
                    gemini_json_input=gemini_json,
                    openai_json_input=openai_json,
                    prompt_text=consolidation_prompt
                )
                consolidated_response_json = attach_page_number_tag(consolidated_response_json, page_num)
                
                metrics["genai_response_consolidation_status"] = 200 if consolidated_response_json and not consolidated_response_json.get("error") else 500
                metrics["genai_response_consolidation_response_length"] = len(json.dumps(consolidated_response_json))
                if consolidated_response_json.get("error"): metrics["json_consolidation_error_message"] = consolidated_response_json.get("error_details", consolidated_response_json.get("error"))
                metrics["consolidation_input_tokens"] = consolidated_response_json.get("_consolidation_input_tokens", 0)
                metrics["consolidation_output_tokens"] = consolidated_response_json.get("_consolidation_output_tokens", 0)
                metrics["consolidation_cost_usd"] = consolidated_response_json.get("_consolidation_cost_usd", 0.0)
                for key in ["_consolidation_input_tokens", "_consolidation_output_tokens", "_consolidation_cost_usd"]:
                    if isinstance(consolidated_response_json, dict) and key in consolidated_response_json: del consolidated_response_json[key]

                consolidated_output_path = os.path.join(genai_output_dir, f"page_{page_num}_consolidated.json")
                with open(consolidated_output_path, "w", encoding="utf-8") as f: json.dump(consolidated_response_json, f, indent=2, ensure_ascii=False)
                print("✅ JSON responses consolidated and saved.")

                # --- Sanitize JSON ---
                try:
                    sanitize_response = call_openai_with_json(json_file_path=consolidated_output_path, prompt=sanitize_prompt_text)
                    sanitized_output_path = os.path.join(genai_output_dir, f"page_{page_num}_sanitized.json")
                    with open(sanitized_output_path, "w", encoding="utf-8") as f: f.write(sanitize_response.get("text", ""))
                    print(f"✅ Sanitized JSON saved for page {page_num}")
                    metrics["sanitize_input_tokens"] = sanitize_response.get("input_tokens", 0)
                    metrics["sanitize_output_tokens"] = sanitize_response.get("output_tokens", 0)
                    metrics["sanitize_cost_usd"] = sanitize_response.get("cost", 0.0)
                    metrics["sanitize_status"] = "success"
                except Exception as e_sanitize:
                    print(f"⚠️ Sanitization failed for page {page_num}: {e_sanitize}")
                    metrics["sanitize_status"] = f"fail - {str(e_sanitize)}"
                    # sanitize_response remains {}, .get("text", "") will handle it below

                # --- Verification Step using sanitized JSON ---
                current_page_verification_status = "failed - verification condition not met"
                sanitized_text = sanitize_response.get("text", "")

                if not sanitized_text.strip():
                    print(f"⚠️ Empty sanitized response for page {page_num}")
                    sanitized_response_json = {"error": "Sanitized response was empty", "page_number": page_num}
                    current_page_verification_status = "fail - empty sanitized text"
                else:
                    try:
                        sanitized_response_json = json.loads(sanitized_text)
                        if not isinstance(sanitized_response_json, dict): # Ensure dict for consistency
                            sanitized_response_json = {"parsed_non_dict_content": sanitized_response_json, "page_number": page_num}
                        elif "page_number" not in sanitized_response_json:
                             sanitized_response_json["page_number"] = page_num
                    except json.JSONDecodeError as e_json_decode_sanitize:
                        print(f"⚠️ Failed to parse sanitized JSON: {e_json_decode_sanitize}")
                        sanitized_response_json = {
                            "error": "Failed to parse sanitized JSON", "exception": str(e_json_decode_sanitize),
                            "raw_text": sanitized_text, "page_number": page_num
                        }
                        current_page_verification_status = "fail - JSON decode error"
                
                if isinstance(sanitized_response_json, dict) and "error" not in sanitized_response_json:
                    try:
                        verification_api_prompt = (
                            f"{output_verification_prompt_text}\n\n"
                            f"Sanitized JSON to verify for page {page_num}:\n"
                            f"{json.dumps(sanitized_response_json, indent=2)}"
                        )
                        print(f"🔍 Content verification for page {page_num} started...")
                        verification_response = call_openai_api(prompt=verification_api_prompt, image_base64=image_base64)
                        verification_text = verification_response["text"]
                        metrics["verification_input_tokens"] = verification_response.get("input_tokens", 0)
                        metrics["verification_output_tokens"] = verification_response.get("output_tokens", 0)
                        metrics["verification_cost_usd"] = verification_response.get("cost", 0.0)

                        if "pass" in verification_text.lower(): current_page_verification_status = "pass"
                        elif "fail" in verification_text.lower(): current_page_verification_status = "fail"
                        else: current_page_verification_status = f"fail - unclear: {verification_text[:100].strip()}"
                        print(f"✅ Verification status for page {page_num}: {current_page_verification_status}")
                    except Exception as e_verify:
                        print(f"⚠️ Verification API error for page {page_num}: {e_verify}")
                        current_page_verification_status = f"fail - verification API error: {str(e_verify)}"
                elif isinstance(sanitized_response_json, dict) and "error" in sanitized_response_json:
                     current_page_verification_status = f"fail - input to verification was error object: {sanitized_response_json.get('error', 'unknown error')}"


                metrics["verification_status"] = current_page_verification_status
                if isinstance(sanitized_response_json, dict):
                    sanitized_response_json["page_verification_status"] = current_page_verification_status
                else: # Fallback if somehow not a dict
                    sanitized_response_json = {
                        "error": "Sanitized response was not a dictionary before final status assignment",
                        "original_content": sanitized_response_json, "page_number": page_num,
                        "page_verification_status": current_page_verification_status
                    }
                all_responses.append(sanitized_response_json)
                print(f"✅ Page {page_num} processed and response appended (main path).")

            except Exception as e_consolidate_sanitize_verify_block:
                print(f"⚠️ Error in main processing block (consolidate/sanitize/verify) for page {page_num}: {e_consolidate_sanitize_verify_block}")
                metrics["genai_response_consolidation_status"] = metrics.get("genai_response_consolidation_status") or 500
                metrics["json_consolidation_error_message"] = (metrics.get("json_consolidation_error_message", "") + f"; Block error: {str(e_consolidate_sanitize_verify_block)}").strip()
                metrics["verification_status"] = "fail - processing block error"

                error_payload_for_all_responses = {
                    "error": f"Main processing block failure for page {page_num}", "details": str(e_consolidate_sanitize_verify_block),
                    "page_number": page_num, "page_verification_status": metrics["verification_status"],
                    "gemini_attempt_available": bool(gemini_json), 
                    "openai_attempt_available": bool(openai_json),
                    "consolidation_attempt_available": bool(consolidated_response_json) and consolidated_response_json != {} # Check if it's not the initial empty dict
                }
                all_responses.append(error_payload_for_all_responses)
                print(f"🔴 Appended error object for page {page_num} due to processing block failure.")

        except Exception as e_outer_page_processing: 
            print(f"❌ Outer error processing page {page_num} ({img_path}): {e_outer_page_processing}")
            page_error_info = {
                "error": f"General error processing page {page_num}", "details": str(e_outer_page_processing),
                "page_number": page_num, "page_verification_status": "fail - page processing error"
            }
            all_responses.append(page_error_info)
            metrics["verification_status"] = page_error_info["page_verification_status"] 

        page_metrics.append(metrics)
        # if page_num < len(image_paths): time.sleep(1) # Consider if rate limiting is needed

    master_json_path = os.path.join(output_dir, "layout_with_verification.json")
    with open(master_json_path, "w", encoding="utf-8") as f:
        json.dump(all_responses, f, indent=2, ensure_ascii=False)
    print(f"✅ Master JSON with verification status saved to: {master_json_path}")

    if all_responses:
        # Filter for dictionary items only, as some might be other types if errors occur unexpectedly
        dict_responses = [item for item in all_responses if isinstance(item, dict)]
        if not dict_responses:
            print("No dictionary data found in all_responses to convert to tabular formats.")
        else:
            try:
                convert_json_to_csv_and_excel(dict_responses, output_dir, base_filename="layout_with_verification")
                convert_json_to_html(dict_responses, output_dir, output_filename="layout_with_verification.html")
            except Exception as e_convert:
                print(f"❌ Error during CSV/Excel/HTML conversion: {e_convert}")   
    else:
        print("No responses to convert because all_responses is empty.") # Should not happen with the fix if there are pages

    summary_df = pd.DataFrame(page_metrics)
    summary_excel_path = os.path.join(output_dir, "page_summary_with_verification.xlsx")
    try:
        summary_df.to_excel(summary_excel_path, index=False)
        print(f"✅ Page-level summary with verification written to: {summary_excel_path}")
    except Exception as e:
        print(f"❌ Failed to save page summary to Excel: {e}")
        summary_csv_path = os.path.join(output_dir, "page_summary_with_verification.csv")
        try:
            summary_df.to_csv(summary_csv_path, index=False)
            print(f"✅ Page-level summary written to CSV as fallback: {summary_csv_path}")
        except Exception as e_csv:
            print(f"❌ Failed to save page summary to CSV as fallback: {e_csv}")

    return page_metrics

def enrich_pdf(pdf_path: str, enrichment_prompt: dict, output_dir: str) -> None:
    """
    Uses Gemini to extract structured information from a full PDF using the provided enrichment prompt dict.
    Stores the result in output_dir/genai_outputs/pdf_enrichment_output.json.
    """
    from services.gemini_client import call_gemini_with_pdf  # Ensure this exists

    def encode_pdf_to_base64(path: str) -> str:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    #genai_output_dir = os.path.join(output_dir, "genai_outputs")
    os.makedirs(output_dir, exist_ok=True)
    enrichment_output_path = os.path.join(output_dir, "enrichment_output.json")

    try:
        pdf_base64 = encode_pdf_to_base64(pdf_path)
        enrichment_response = call_gemini_with_pdf(pdf_base64, enrichment_prompt_dict=enrichment_prompt)
        raw_text = enrichment_response.get("text", "")

        # Try to parse JSON from response
        try:
            enrichment_json_str = extract_json_string(raw_text)
            enrichment_json = json.loads(enrichment_json_str) if enrichment_json_str else {}
        except Exception as je:
            enrichment_json = {
                "error": "Failed to parse JSON from enrichment response",
                "raw_text": raw_text,
                "exception": str(je)
            }

        with open(enrichment_output_path, "w", encoding="utf-8") as f:
            json.dump(enrichment_json, f, indent=2, ensure_ascii=False)

        print(f"✅ Enrichment output saved to: {enrichment_output_path}")

    except Exception as e:
        print(f"❌ Failed to enrich PDF with Gemini: {e}")


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent
    project_root_path = base_dir.parents[2]
    print(f"Project root determined as: {project_root_path}")

    # Define input PDF path
    pdf_path = project_root_path / "tests" / "assets" / "inputs" / "sample.pdf"

    # Define output directories
    output_dir_path = project_root_path / "tests" / "assets" / "outputs" / "functions" / "output_doc_layout"
    image_dir_path = output_dir_path / "page_images"
    genai_output_dir = output_dir_path / "genai_outputs"

    # Ensure output folders exist
    os.makedirs(output_dir_path, exist_ok=True)
    os.makedirs(image_dir_path, exist_ok=True)
    os.makedirs(genai_output_dir, exist_ok=True)

    print(f"Input PDF path: {pdf_path}")
    print(f"Output directory: {output_dir_path}")
    print(f"Image directory: {image_dir_path}")

    # Ensure PDF exists
    if not pdf_path.exists():
        print(f"❌ ERROR: PDF file not found at {pdf_path}")
        sys.exit(1)

    # Process PDF for layout extraction
    page_summary_data = process_pdf(
        pdf_path=str(pdf_path),
        output_dir=str(output_dir_path),
        image_dir=str(image_dir_path),
        poppler_path=None
    )

    # Perform enrichment-level extraction
    enrich_pdf(
        pdf_path=str(pdf_path),
        enrichment_prompt=enrichment_prompt,
        output_dir=str(output_dir_path)
    )

    # Final summary
    if page_summary_data:
        print("✅ PDF processing complete. Page summary with verification generated.")
    else:
        print("⚠️ PDF processing completed, but no page summary data was returned.")


