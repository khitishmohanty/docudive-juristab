import os
import re
import sys
import json
import base64
import time
from pathlib import Path
import pandas as pd
import fitz

# Add project root to PYTHONPATH
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../"))
sys.path.insert(0, project_root)

# Local imports
from utils.pdf_to_image_converter import convert_pdf_to_images
from services.gemini_client import call_gemini_api
from services.openai_client import call_openai_api, call_openai_with_json, call_openai_with_pdf 
from utils.csv_excel_converter import convert_json_to_csv_and_excel 
from utils.csv_excel_converter import convert_json_to_csv_and_excel
from utils.html_converter import convert_json_to_html
from utils.prompt_loader import load_text_prompt, load_json_prompt
from utils.pdf_text_extractor import (
    extract_text_from_pdf_page,
    extract_text_from_ocr,
    is_fidelity_preserved,
)
from utils.json_utils import (
    attach_page_number_tag,
    extract_json_string,
)
from utils.file_utils import encode_pdf_to_base64
from services.gemini_client import call_gemini_api, call_gemini_with_pdf 
from services.openai_client import call_openai_api, call_openai_with_json
from core.consolidator import consolidate_responses

# Load prompts from file
gemini_prompt_config = load_json_prompt("gemini_layout_prompt.json") # Expects image
openai_prompt_text = load_text_prompt("openai_layout_prompt.txt")
consolidation_prompt_text = load_text_prompt("consolidation_prompt.txt")
enrichment_prompt_config = load_json_prompt("enrichment_prompt.json") # For call_gemini_with_pdf
output_verification_prompt_text = load_text_prompt("output_verification_prompt.txt")
sanitize_prompt_text = load_text_prompt("sanitize_prompt.txt")

def process_pdf(pdf_path: str, output_dir: str, temp_page_dir: str) -> list:
    # temp_page_dir is where temporary single-page PDFs will be stored.
    # poppler_path is no longer needed.
    os.makedirs(temp_page_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)
    genai_output_dir = os.path.join(output_dir, "genai_outputs")
    os.makedirs(genai_output_dir, exist_ok=True)

    print(f"📄 Processing PDF: {pdf_path} page by page.")
    
    all_responses = []
    page_metrics = []

    global gemini_prompt_config
    global openai_prompt_text
    global consolidation_prompt_text
    global output_verification_prompt_text

    try:
        pdf_document = fitz.open(pdf_path)
    except Exception as e:
        print(f"❌ Failed to open PDF {pdf_path}: {e}")
        return [] # Return empty if PDF can't be opened

    for page_index in range(len(pdf_document)):
        page_num_actual = page_index + 1
        print("---------------------")
        print(f"📤 Processing page: {page_num_actual}")

        metrics = {
            "page": page_num_actual,
            "time_sec_total_page_processing": 0.0, # New
            "time_sec_temp_pdf_creation": 0.0,    # New
            "gemini_api_status": None, "gemini_response_length": 0, "gemini_error_message": "",
            "gemini_input_tokens": 0, "gemini_output_tokens": 0, "gemini_cost_usd": 0.0,
            "time_sec_gemini_layout": 0.0,        # New
            "openai_api_status": None, "openai_response_length": 0, "openai_error_message": "",
            "openai_input_tokens": 0, "openai_output_tokens": 0, "openai_cost_usd": 0.0,
            "time_sec_openai_layout": 0.0,        # New
            "genai_response_consolidation_status": None, "genai_response_consolidation_response_length": 0,
            "json_consolidation_error_message": "",
            "consolidation_input_tokens": 0, "consolidation_output_tokens": 0, "consolidation_cost_usd": 0.0,
            "time_sec_consolidation": 0.0,        # New
            "sanitize_input_tokens": 0, "sanitize_output_tokens": 0, "sanitize_cost_usd": 0.0,
            "sanitize_status": "not attempted",
            "time_sec_sanitize": 0.0,             # New
            "verification_status": "failed - verification not performed",
            "verification_input_tokens": 0, "verification_output_tokens": 0, "verification_cost_usd": 0.0,
            "time_sec_verification": 0.0          # New
        }
        
        page_processing_start_time = time.time() # For total page time
        
        gemini_json = {}
        openai_json = {}
        consolidated_response_json = {}
        sanitized_response_json = {}
        
        temp_pdf_page_path = os.path.join(temp_page_dir, f"temp_page_{page_num_actual}.pdf")
        pdf_page_base64 = None

        try: # Outermost try for the entire page processing
            temp_pdf_creation_start_time = time.time() # Start timer
            # Create a temporary PDF for the current page
            single_page_doc = fitz.open()
            single_page_doc.insert_pdf(pdf_document, from_page=page_index, to_page=page_index)
            single_page_doc.save(temp_pdf_page_path)
            single_page_doc.close()
            metrics["time_sec_temp_pdf_creation"] = time.time() - temp_pdf_creation_start_time # End timer & store

            pdf_page_base64 = encode_pdf_to_base64(temp_pdf_page_path)

            # --- Call Gemini for Layout ---
            # This now requires call_gemini_api to be adapted for PDF mime_type,
            # or a new function like call_gemini_api_with_pdf_page_data.
            # We use gemini_prompt_config (gemini_layout_prompt.json)
            gemini_raw_text = ""
            try:
                gemini_layout_start_time = time.time() # Start timer
                prompt_details = gemini_prompt_config.get("prompt_details", {})
                task_desc = prompt_details.get("task_description", "")
                output_format_obj = prompt_details.get("output_format_instructions", {})
                # input_desc = prompt_details.get("input_image_description", "") # Old: for image
                input_desc = prompt_details.get("input_pdf_page_description", "The input is a single page from a PDF document.")


                gemini_api_parts = [
                    {"text": text} for text in [
                        task_desc,
                        f"Please adhere strictly to the following output format and schema:\n{json.dumps(output_format_obj, indent=2)}" if output_format_obj else None,
                        f"Contextual description of the PDF page provided:\n{input_desc}" if input_desc else None
                    ] if text and text.strip()
                ]
                if not gemini_api_parts: raise ValueError("Could not construct valid prompt parts for Gemini.")

                # Assuming call_gemini_api is flexible enough or a new PDF-specific function is used.
                # Passing pdf_page_base64 as image_base64 and specifying mime_type.
                gemini_api_call_response = call_gemini_api(
                    image_base64=pdf_page_base64, 
                    prompt_parts=gemini_api_parts,
                    mime_type="application/pdf" # Critical change for Gemini
                )
                metrics["time_sec_gemini_layout"] = time.time() - gemini_layout_start_time # End timer & store
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
                if 'gemini_layout_start_time' in locals(): # Ensure timer was started
                    metrics["time_sec_gemini_layout"] = time.time() - gemini_layout_start_time
                print(f"⚠️ JSON DECODING ERROR (Gemini Call, Page {page_num_actual}): {je}")
                metrics.update({"gemini_api_status": 500, "gemini_error_message": f"JSONDecodeError: {je}"})
                gemini_json = {"error": f"JSONDecodeError from Gemini: {je}", "raw_output": gemini_raw_text, "page_number": page_num_actual}
            except Exception as e:
                if 'gemini_layout_start_time' in locals():
                    metrics["time_sec_gemini_layout"] = time.time() - gemini_layout_start_time
                print(f"⚠️ Gemini API error (Page {page_num_actual}): {e}")
                metrics.update({"gemini_api_status": 500, "gemini_error_message": str(e)})
                gemini_json = {"error": f"Gemini API call failed: {e}", "page_number": page_num_actual}

            # --- Call OpenAI for Layout ---
            # Uses call_openai_with_pdf, which uploads the temporary single-page PDF.
            openai_raw_text = ""
            try:
                openai_layout_start_time = time.time() # Start timer
                # openai_prompt_text is the content of openai_layout_prompt.txt
                openai_api_call_response = call_openai_with_pdf(
                    pdf_path=temp_pdf_page_path, 
                    prompt=openai_prompt_text
                )
                metrics["time_sec_openai_layout"] = time.time() - openai_layout_start_time # End timer & store
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
                if 'openai_layout_start_time' in locals():
                    metrics["time_sec_openai_layout"] = time.time() - openai_layout_start_time
                print(f"⚠️ JSON DECODING ERROR (OpenAI Call, Page {page_num_actual}): {je}")
                metrics.update({"openai_api_status": 500, "openai_error_message": f"JSONDecodeError: {je}"})
                openai_json = {"error": f"JSONDecodeError from OpenAI: {je}", "raw_output": openai_raw_text, "page_number": page_num_actual}
            except Exception as e:
                if 'openai_layout_start_time' in locals():
                    metrics["time_sec_openai_layout"] = time.time() - openai_layout_start_time
                print(f"⚠️ OpenAI API error (Page {page_num_actual}): {e}")
                metrics.update({"openai_api_status": 500, "openai_error_message": str(e)})
                openai_json = {"error": f"OpenAI API call failed: {e}", "page_number": page_num_actual}

            # --- Consolidate, Sanitize, Verify Block ---
            try:
                consolidation_start_time = time.time() # Start timer for consolidation
                consolidated_response_json = consolidate_responses(
                    pdf_page_base64=pdf_page_base64, # Pass PDF base64 for context
                    gemini_json_input=gemini_json,
                    openai_json_input=openai_json,
                    prompt_text=consolidation_prompt_text
                )
                metrics["time_sec_consolidation"] = time.time() - consolidation_start_time # End timer & store
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
                try:
                    sanitize_start_time = time.time() # Start timer for sanitize
                    # call_openai_with_json expects a file path to the JSON to be sanitized
                    sanitize_response = call_openai_with_json(json_file_path=consolidated_output_path, prompt=sanitize_prompt_text)
                    metrics["time_sec_sanitize"] = time.time() - sanitize_start_time # End timer & store
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
                    if 'sanitize_start_time' in locals():
                        metrics["time_sec_sanitize"] = time.time() - sanitize_start_time
                    print(f"⚠️ Sanitization failed for page {page_num_actual}: {e_sanitize}")
                    metrics["sanitize_status"] = f"fail - {str(e_sanitize)}"
                
                # --- Verification Step using sanitized JSON and PDF page ---
                current_page_verification_status = "failed - verification condition not met"
                sanitized_text_content = sanitize_response.get("text", "")

                if not sanitized_text_content.strip():
                    print(f"⚠️ Empty sanitized response for page {page_num_actual}, using consolidated for verification if available.")
                    sanitized_response_json = {"error": "Sanitized response was empty", "page_number": page_num_actual}
                    current_page_verification_status = "fail - empty sanitized text"
                    # If sanitization failed, maybe try to verify the consolidated one? Or mark as fail.
                    # For now, if sanitize fails, verification input is based on that failure.
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
                
                # Proceed with verification if sanitized_response_json is a dict and not an error placeholder from above
                if isinstance(sanitized_response_json, dict) and "error" not in sanitized_response_json :
                    try:
                        verification_start_time = time.time() # Start timer for verification
                        # The verification prompt text itself
                        verification_api_main_prompt = (
                            f"{output_verification_prompt_text}\n\n"
                            f"Sanitized JSON to verify for page {page_num_actual}:\n"
                            f"{json.dumps(sanitized_response_json, indent=2)}"
                        )
                        print(f"🔍 Content verification for page {page_num_actual} started (using PDF page).")
                        # Pass the temporary single-page PDF for verification context
                        verification_response = call_openai_with_pdf(
                            pdf_path=temp_pdf_page_path,
                            prompt=verification_api_main_prompt
                        )
                        metrics["time_sec_verification"] = time.time() - verification_start_time # End timer & store
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
                        if 'verification_start_time' in locals():
                            metrics["time_sec_verification"] = time.time() - verification_start_time
                        print(f"⚠️ Verification API error for page {page_num_actual}: {e_verify}")
                        current_page_verification_status = f"fail - verification API error: {str(e_verify)}"
                
                elif isinstance(sanitized_response_json, dict) and "error" in sanitized_response_json:
                    current_page_verification_status = f"fail - input to verification was error object: {sanitized_response_json.get('error', 'unknown error')}"


                metrics["verification_status"] = current_page_verification_status
                if isinstance(sanitized_response_json, dict): # Ensure it is a dict before adding new key
                    sanitized_response_json["page_verification_status"] = current_page_verification_status
                else: # Fallback if it became non-dict
                    sanitized_response_json = {
                        "error": "Sanitized response was not a dictionary before final status assignment",
                        "original_content_type": type(sanitized_response_json).__name__,
                        "page_number": page_num_actual,
                        "page_verification_status": current_page_verification_status
                    }

                all_responses.append(sanitized_response_json)
                print(f"✅ Page {page_num_actual} processed and response appended.")

            except Exception as e_consolidate_sanitize_verify_block:
                print(f"⚠️ Error in main processing block (consolidate/sanitize/verify) for page {page_num_actual}: {e_consolidate_sanitize_verify_block}")
                metrics.update({
                    "genai_response_consolidation_status": metrics.get("genai_response_consolidation_status") or 500,
                    "json_consolidation_error_message": (metrics.get("json_consolidation_error_message", "") + f"; Block error: {str(e_consolidate_sanitize_verify_block)}").strip(),
                    "verification_status": "fail - processing block error"
                })
                error_payload = {
                    "error": f"Main processing block failure for page {page_num_actual}", "details": str(e_consolidate_sanitize_verify_block),
                    "page_number": page_num_actual, "page_verification_status": metrics["verification_status"],
                    "gemini_attempt_available": bool(gemini_json), 
                    "openai_attempt_available": bool(openai_json),
                    "consolidation_attempt_available": bool(consolidated_response_json) and consolidated_response_json != {}
                }
                all_responses.append(error_payload)
                print(f"🔴 Appended error object for page {page_num_actual} due to processing block failure.")

        except Exception as e_outer_page_processing: 
            print(f"❌ Outer error processing page {page_num_actual} (temp PDF: {temp_pdf_page_path}): {e_outer_page_processing}")
            page_error_info = {
                "error": f"General error processing page {page_num_actual}", "details": str(e_outer_page_processing),
                "page_number": page_num_actual, "page_verification_status": "fail - page processing error"
            }
            all_responses.append(page_error_info)
            metrics["verification_status"] = page_error_info["page_verification_status"]
        
        finally:
            metrics["time_sec_total_page_processing"] = time.time() - page_processing_start_time # End total page timer
            # Clean up the temporary single-page PDF
            if os.path.exists(temp_pdf_page_path):
                try:
                    os.remove(temp_pdf_page_path)
                    # print(f"🧹 Cleaned up temporary PDF: {temp_pdf_page_path}")
                except Exception as e_delete:
                    print(f"⚠️ Failed to delete temporary PDF {temp_pdf_page_path}: {e_delete}")

        page_metrics.append(metrics)
        # if page_index < len(pdf_document) - 1: time.sleep(1) # Optional delay

    if pdf_document:
        pdf_document.close()

    master_json_path = os.path.join(output_dir, "layout_with_verification.json")
    with open(master_json_path, "w", encoding="utf-8") as f:
        json.dump(all_responses, f, indent=2, ensure_ascii=False)
    print(f"✅ Master JSON with verification status saved to: {master_json_path}")

    if all_responses:
        dict_responses = [item for item in all_responses if isinstance(item, dict)]
        if dict_responses:
            try:
                convert_json_to_csv_and_excel(dict_responses, output_dir, base_filename="layout_with_verification")
                convert_json_to_html(dict_responses, output_dir, output_filename="layout_with_verification.html")
            except Exception as e_convert:
                print(f"❌ Error during CSV/Excel/HTML conversion: {e_convert}")   
        else:
            print("No dictionary data found in all_responses to convert to tabular formats.")
    else:
        print("No responses to convert because all_responses is empty.")

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
    # Ensure PyMuPDF is installed: pip install PyMuPDF
    try:
        import fitz # This import is local to this block for the check
    except ImportError:
        print("❌ PyMuPDF (fitz) is not installed. Please install it using: pip install PyMuPDF")
        sys.exit(1)
        
    base_dir = Path(__file__).resolve().parent
    project_root_path = base_dir.parents[2]
    print(f"Project root determined as: {project_root_path}")

    # Define input PDF path
    pdf_path = project_root_path / "tests" / "assets" / "inputs" / "sample.pdf"

    # Define output directories
    output_dir_path = project_root_path / "tests" / "assets" / "outputs" / "functions" / "output_doc_layout"
    image_dir_path = output_dir_path / "page_images"
    genai_output_dir = output_dir_path / "genai_outputs"

    # Define temp_pdf_page_dir_path correctly
    temp_pdf_page_dir_path = output_dir_path / "temp_pdf_pages" 
    
    # Ensure output folders exist
    os.makedirs(output_dir_path, exist_ok=True)
    os.makedirs(image_dir_path, exist_ok=True)
    os.makedirs(genai_output_dir, exist_ok=True)
    os.makedirs(temp_pdf_page_dir_path, exist_ok=True)

    print(f"Input PDF path: {pdf_path}")
    print(f"Output directory: {output_dir_path}")
    print(f"Temporary PDF page directory: {temp_pdf_page_dir_path}")

    # Ensure PDF exists
    if not pdf_path.exists():
        print(f"❌ ERROR: PDF file not found at {pdf_path}")
        sys.exit(1)

    # Process PDF for layout extraction
    page_summary_data = process_pdf(
        pdf_path=str(pdf_path),
        output_dir=str(output_dir_path),
        temp_page_dir=str(temp_pdf_page_dir_path) # Pass the new temp_page_dir argument
    )

    # Perform enrichment-level extraction
    enrich_pdf(
        pdf_path=str(pdf_path),
        enrichment_prompt=enrichment_prompt_config, 
        output_dir=str(output_dir_path)
    )

    # Final summary
    if page_summary_data:
        print("✅ PDF processing complete. Page summary with verification generated.")
    else:
        print("⚠️ PDF processing completed, but no page summary data was returned.")


