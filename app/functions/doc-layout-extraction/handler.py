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

# Load prompts from file
gemini_prompt = load_json_prompt("gemini_layout_prompt.json")
openai_prompt = load_text_prompt("openai_layout_prompt.txt")
consolidation_prompt = load_text_prompt("consolidation_prompt.txt")
# New prompt for output verification
output_verification_prompt_text = load_text_prompt("output_verification_prompt.txt")


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


def consolidate_responses(image_base64: str, gemini_json_input, openai_json_input, prompt_text: str) -> dict:
    global gemini_prompt

    try:
        prompt_details = gemini_prompt.get("prompt_details", {})
        task = prompt_details.get("task_description", "Consolidate the provided JSON outputs based on the task.")
        schema_obj = prompt_details.get("output_format_instructions", {})
        schema_str = json.dumps(schema_obj, indent=2)
        image_desc = prompt_details.get("input_image_description", "")

        consolidation_instructions = prompt_text

        prompt_parts = [
            {"text": consolidation_instructions},
            {"text": f"Original Task Description: {task}"},
            {"text": f"Image context (if relevant for consolidation): {image_desc}"},
            {"text": f"Strictly adhere to this Output JSON Schema:\n{schema_str}"},
            {"text": f"GEMINI RESPONSE TO CONSOLIDATE:\n{json.dumps(gemini_json_input, indent=2)}"},
            {"text": f"OPENAI RESPONSE TO CONSOLIDATE:\n{json.dumps(openai_json_input, indent=2)}"}
        ]

        result_text = call_gemini_api(image_base64, prompt_parts)
        cleaned_json_str = extract_json_string(result_text)
        
        if cleaned_json_str:
            return json.loads(cleaned_json_str)
        return {"error": "Consolidation failed to produce valid JSON", "gemini_original": gemini_json_input, "openai_original": openai_json_input, "verification_status_internal": "Fallback_NoValidJson"}

    except json.JSONDecodeError as je:
        print(f"❌ Consolidation JSON DECODING ERROR: {je}")
        print(f"Problematic JSON string during consolidation was: >>>\n{cleaned_json_str}\n<<<")
        return {"gemini_original": gemini_json_input, "openai_original": openai_json_input, "verification_status_internal": "Fallback_JsonDecodeError", "error_details": str(je)}
    except Exception as e:
        print(f"❌ Consolidation failed with unexpected error: {e}")
        return {"gemini_original": gemini_json_input, "openai_original": openai_json_input, "verification_status_internal": "Fallback_Exception", "error_details": str(e)}

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

    print(f"📄 Converting PDF to images from: {pdf_path}")
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
            "openai_api_status": None, "openai_response_length": 0, "openai_error_message": "",
            "genai_response_consolidation_status": None, "genai_response_consolidation_response_length": 0,
            "json_consolidation_error_message": "",
            "verification_status": "failed - verification not performed" # Default status for the new verification
        }
        gemini_json_str = ""
        openai_json_str = ""
        
        try:
            image_base64 = encode_image_to_base64(img_path)

            # Call Gemini
            gemini_json = {}
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
                if not gemini_api_parts:
                    raise ValueError("Could not construct any valid text prompt parts from gemini_prompt for the primary Gemini API call.")
                gemini_raw = call_gemini_api(image_base64, gemini_api_parts)
                with open(os.path.join(genai_output_dir, f"page_{page_num}_gemini_raw.txt"), "w", encoding="utf-8") as f: f.write(gemini_raw)
                metrics["gemini_api_status"] = 200
                gemini_json_str = extract_json_string(gemini_raw)
                metrics["gemini_response_length"] = len(gemini_json_str or "")
                gemini_json = json.loads(gemini_json_str) if gemini_json_str else {"error": "Empty JSON string from Gemini."}
                print("Received and parsed Gemini response")
            except json.JSONDecodeError as je:
                print(f"⚠️ JSON DECODING ERROR (Primary Gemini Call): {je}")
                metrics["gemini_api_status"] = 500 
                metrics["gemini_error_message"] = f"JSONDecodeError: {je}"
                gemini_json = {"error": f"JSONDecodeError from Gemini: {je}", "raw_output": gemini_json_str}
            except Exception as e:
                print(f"⚠️ Gemini API error: {e}")
                metrics["gemini_api_status"] = 500
                metrics["gemini_error_message"] = str(e)
                gemini_json = {"error": f"Gemini API call failed: {e}"}

            # Call OpenAI for initial layout extraction
            openai_json = {}
            try:
                openai_raw = call_openai_api(openai_prompt, image_base64=image_base64) # Removed image_path assuming base64 is preferred
                with open(os.path.join(genai_output_dir, f"page_{page_num}_openai_raw.txt"), "w", encoding="utf-8") as f: f.write(openai_raw)
                metrics["openai_api_status"] = 200
                openai_json_str = extract_json_string(openai_raw)
                metrics["openai_response_length"] = len(openai_json_str or "")
                openai_json = json.loads(openai_json_str) if openai_json_str else {"error": "Empty JSON string from OpenAI."}
                print("Received and parsed OpenAI response")
            except json.JSONDecodeError as je:
                print(f"⚠️ JSON DECODING ERROR (OpenAI Call): {je}")
                metrics["openai_api_status"] = 500
                metrics["openai_error_message"] = f"JSONDecodeError: {je}"
                openai_json = {"error": f"JSONDecodeError from OpenAI: {je}", "raw_output": openai_json_str}
            except Exception as e:
                print(f"⚠️ OpenAI API error: {e}")
                metrics["openai_api_status"] = 500
                metrics["openai_error_message"] = str(e)
                openai_json = {"error": f"OpenAI API call failed: {e}"}

            # Consolidate results
            consolidated_response_json = {}
            try:
                consolidated_response_json = consolidate_responses(
                    image_base64=image_base64,
                    gemini_json_input=gemini_json,
                    openai_json_input=openai_json,
                    prompt_text=consolidation_prompt # Pass the text content
                )
                
                consolidated_response_json = attach_page_number_tag(consolidated_response_json, page_num)

                metrics["genai_response_consolidation_status"] = 200 if consolidated_response_json and not consolidated_response_json.get("error") else 500
                metrics["genai_response_consolidation_response_length"] = len(json.dumps(consolidated_response_json)) if consolidated_response_json else 0
                if consolidated_response_json.get("error"):
                    metrics["json_consolidation_error_message"] = consolidated_response_json.get("error_details", consolidated_response_json.get("error"))
                
                # --- MODIFICATION START: Save consolidated response ---
                consolidated_output_path = os.path.join(genai_output_dir, f"page_{page_num}_consolidated.json")
                with open(consolidated_output_path, "w", encoding="utf-8") as f:
                    json.dump(consolidated_response_json, f, indent=2, ensure_ascii=False)
                #print(f"Saved consolidated response to: {consolidated_output_path}")
                # --- MODIFICATION END ---
                
                print(f"json responses consolidated")
            except Exception as e:
                print(f"⚠️ Consolidation function error: {e}")
                metrics["genai_response_consolidation_status"] = 500
                metrics["json_consolidation_error_message"] = str(e)
                consolidated_response_json = {"gemini_original": gemini_json, "openai_original": openai_json, "verification_status_internal": "Fallback_ConsolidationException", "error_details": f"Consolidation function error: {str(e)}"}

            # --- New Verification Step using OpenAI ---
            current_page_verification_status = "failed - verification condition not met"
            if isinstance(consolidated_response_json, dict) and not consolidated_response_json.get("error") and not consolidated_response_json.get("verification_status_internal", "").startswith("Fallback"):
                try:
                    # Construct the prompt for OpenAI verification
                    verification_api_prompt = f"{output_verification_prompt_text}\n\nExtracted JSON to verify for page {page_num}:\n{json.dumps(consolidated_response_json, indent=2)}"
                    
                    print(f"Content verification for page {page_num} started...")
                    verification_raw_response = call_openai_api(
                        prompt=verification_api_prompt,
                        image_base64=image_base64
                    )
                    
                    # Simple pass/fail check based on keywords in response
                    if "pass" in verification_raw_response.lower():
                        current_page_verification_status = "pass"
                    elif "fail" in verification_raw_response.lower():
                        current_page_verification_status = "fail"
                    else:
                        current_page_verification_status = f"fail - unclear response: {verification_raw_response[:100].strip()}"
                    print(f"Verification status for page {page_num}: {current_page_verification_status}")

                except Exception as e_verify:
                    print(f"⚠️ OpenAI verification API error for page {page_num}: {e_verify}")
                    current_page_verification_status = f"fail - verification API error: {str(e_verify)}"
            elif consolidated_response_json.get("error") or consolidated_response_json.get("verification_status_internal", "").startswith("Fallback"):
                current_page_verification_status = f"fail - skipped due to consolidation error: {consolidated_response_json.get('error_details', consolidated_response_json.get('error', 'Unknown consolidation issue'))}"
            else: # E.g. if consolidated_response_json is not a dict or other unexpected cases
                current_page_verification_status = "fail - consolidated data not suitable for verification"
            
            metrics["verification_status"] = current_page_verification_status
            if isinstance(consolidated_response_json, dict):
                consolidated_response_json["page_verification_status"] = current_page_verification_status
            # --- End New Verification Step ---

            if isinstance(consolidated_response_json, list):
                all_responses.extend(consolidated_response_json)
            elif isinstance(consolidated_response_json, dict):
                all_responses.append(consolidated_response_json)
            else:
                print(f"⚠️ Unexpected type from consolidation: {type(consolidated_response_json)}. Appending as error.")
                all_responses.append({"error": "Unexpected consolidation output type", "page": page_num, "raw_consolidated_output": str(consolidated_response_json), "page_verification_status": current_page_verification_status})

            print(f"Page {page_num} processed and response appended.")

        except Exception as e: 
            print(f"❌ Outer error processing page {page_num} ({img_path}): {e}")
            error_info = {"error": f"General error processing page {page_num}", "details": str(e), "page_verification_status": "fail - page processing error"}
            all_responses.append(error_info)
            metrics["verification_status"] = error_info["page_verification_status"] 

        page_metrics.append(metrics)
        # if page_num < len(image_paths): time.sleep(1) 

    master_json_path = os.path.join(output_dir, "layout_with_verification.json")
    with open(master_json_path, "w", encoding="utf-8") as f:
        json.dump(all_responses, f, indent=2, ensure_ascii=False)
    print(f"✅ Master JSON with verification status saved to: {master_json_path}")

    if all_responses:
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
        print("No responses to convert.")

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


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent
    project_root_path = base_dir.parents[2] 
    print(f"Project root determined as: {project_root_path}")

    pdf_path = project_root_path / "tests" / "assets" / "inputs" / "sample.pdf"
    output_dir_path = project_root_path / "tests" / "assets" / "outputs" / "functions" / "output_doc_layout"
    image_dir_path = output_dir_path / "page_images"
    genai_output_dir = os.path.join(output_dir_path, "genai_outputs")
    os.makedirs(genai_output_dir, exist_ok=True)
    
    poppler_path_env = None

    print(f"Input PDF path: {pdf_path}")
    print(f"Output directory: {output_dir_path}")
    print(f"Image directory: {image_dir_path}")

    if not pdf_path.exists():
        print(f"❌ ERROR: PDF file not found at {pdf_path}")
        sys.exit(1) 
    
    os.makedirs(output_dir_path, exist_ok=True)
    os.makedirs(image_dir_path, exist_ok=True)

    page_summary_data = process_pdf(
        pdf_path=str(pdf_path),
        output_dir=str(output_dir_path),
        image_dir=str(image_dir_path),
        poppler_path=poppler_path_env # Pass None if not used or handled by system PATH
    )

    if page_summary_data:
        print("✅ PDF processing complete. Page summary with verification generated.")
    else:
        print("⚠️ PDF processing completed, but no page summary data was returned.")


