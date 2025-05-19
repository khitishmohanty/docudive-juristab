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
from services.openai_client import call_openai_api
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


def extract_json_string(raw_text: str) -> str:
    """Extracts the first valid JSON array or object from a raw string."""
    # Corrected regex to handle potential markdown ```json ... ``` blocks
    # and find the innermost valid JSON structure.
    # This regex looks for content between ```json and ``` or the first { to the last } or [ to last ].
    # It's a common pattern, but complex/nested/malformed JSON from LLMs might still be tricky.
    json_markdown_match = re.search(r"```json\s*([\s\S]*?)\s*```", raw_text, re.DOTALL)
    if json_markdown_match:
        return json_markdown_match.group(1).strip()

    # If no markdown block, try to find the first '{' or '[' and its corresponding '}' or ']'
    # This is a simplified approach and might grab more than intended if there's surrounding text.
    # A more robust parser might be needed for highly complex or noisy outputs.
    json_pattern = r"(\[.*?\]|\{.*?\})" # Original pattern
    matches = re.findall(json_pattern, raw_text, re.DOTALL) # re.DOTALL allows . to match newlines
    
    if matches:
        # Try to parse each match to find the first valid one, as LLMs might output multiple JSON-like snippets
        for match in matches:
            try:
                json.loads(match) # Test if it's valid JSON
                return match # Return the first valid JSON string
            except json.JSONDecodeError:
                continue # Not valid, try next match
    return "" # Return empty if no valid JSON found


def encode_image_to_base64(image_path: str) -> str:
    """Encodes an image file to a base64 string."""
    with open(image_path, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode("utf-8")


def consolidate_responses(image_base64: str, gemini_json_input, openai_json_input, prompt: dict) -> dict: # Renamed inputs to avoid conflict
    # Ensure prompt is a dictionary (loaded from consolidation_prompt.txt, assumed to be text, needs parsing if it's JSON)
    # For this function, prompt is expected to be the content of consolidation_prompt.txt
    # If consolidation_prompt.txt is *meant* to be a JSON structure itself (like gemini_layout_prompt.json),
    # it should be loaded with load_json_prompt and handled accordingly.
    # Assuming 'prompt' here is the *text* of the consolidation prompt.
    # And the call_gemini_api expects specific parts from `gemini_layout_prompt.json` for schema details.
    # We will use the gemini_prompt (global) for schema details as in the original logic.

    global gemini_prompt # Access the globally loaded gemini_layout_prompt for schema

    try:
        # Using the global `gemini_prompt` (loaded from gemini_layout_prompt.json) for schema details
        prompt_details = gemini_prompt.get("prompt_details", {})
        task = prompt_details.get("task_description", "Consolidate the provided JSON outputs based on the task.") # Generic task if not found
        schema_obj = prompt_details.get("output_format_instructions", {})
        schema_str = json.dumps(schema_obj, indent=2)
        image_desc = prompt_details.get("input_image_description", "") # From gemini_layout_prompt

        # The 'prompt' argument for this function is the content of 'consolidation_prompt.txt'
        # This text prompt guides the consolidation.
        consolidation_instructions = prompt # This is the text from consolidation_prompt.txt

        prompt_parts = [
            {"text": consolidation_instructions}, # Main instruction from consolidation_prompt.txt
            {"text": f"Original Task Description: {task}"}, # Add original task for context
            {"text": f"Image context (if relevant for consolidation): {image_desc}"},
            {"text": f"Strictly adhere to this Output JSON Schema:\n{schema_str}"},
            {"text": f"GEMINI RESPONSE TO CONSOLIDATE:\n{json.dumps(gemini_json_input, indent=2)}"},
            {"text": f"OPENAI RESPONSE TO CONSOLIDATE:\n{json.dumps(openai_json_input, indent=2)}"}
        ]

        result_text = call_gemini_api(image_base64, prompt_parts)
        cleaned_json_str = extract_json_string(result_text)

        #print(f"--- DEBUG: Attempting to parse cleaned_json_str (from consolidation call) ---")
        #print(f"Raw result_text: {result_text[:500]}...") # Print start of raw text
        #print(f"Extracted cleaned_json_str: {cleaned_json_str[:500]}...") # Print start of extracted string
        #print(f"--- END DEBUG: cleaned_json_str ---")
        
        if cleaned_json_str:
            return json.loads(cleaned_json_str)
        return {"error": "Consolidation failed to produce valid JSON", "gemini_original": gemini_json_input, "openai_original": openai_json_input, "verification-flag": "Fallback"}

    except json.JSONDecodeError as je:
        print(f"❌ Consolidation JSON DECODING ERROR: {je}")
        print(f"Problematic JSON string during consolidation was: >>>\n{cleaned_json_str}\n<<<")
        return {"gemini_original": gemini_json_input, "openai_original": openai_json_input, "verification-flag": "Fallback", "error_details": str(je)}
    except Exception as e:
        print(f"❌ Consolidation failed with unexpected error: {e}")
        return {"gemini_original": gemini_json_input, "openai_original": openai_json_input, "verification-flag": "Fallback", "error_details": str(e)}


def process_pdf(pdf_path: str, output_dir: str, image_dir: str, poppler_path: str = None) -> list:
    os.makedirs(image_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    print(f"📄 Converting PDF to images from: {pdf_path}")
    image_paths = convert_pdf_to_images(pdf_path, image_dir, poppler_path=poppler_path)

    all_responses = []
    page_metrics = []

    # Access the global gemini_prompt loaded from gemini_layout_prompt.json
    global gemini_prompt
    global openai_prompt
    global consolidation_prompt # Make sure this is loaded as text if used as text

    for page_num, img_path in enumerate(image_paths, start=1):
        print("---------------------")
        print(f"📤 Processing page: {page_num}")
        metrics = {
            "page": page_num,
            "gemini_api_status": None, "gemini_response_length": 0, "gemini_error_message": "",
            "openai_api_status": None, "openai_response_length": 0, "openai_error_message": "",
            "genai_response_consolidation_status": None, "genai_response_consolidation_response_length": 0,
            "json_consolidation_error_message": "", "content_verification_status": "failed"
        }
        gemini_json_str = "" # Initialize to ensure it's defined for error logging
        openai_json_str = "" # Initialize
        cleaned_json_str_consolidation = "" # Initialize

        try:
            image_base64 = encode_image_to_base64(img_path)

            # Call Gemini
            gemini_json = {}
            try:
                prompt_details = gemini_prompt.get("prompt_details", {})
                task_description = prompt_details.get("task_description", "")
                output_format_instructions_obj = prompt_details.get("output_format_instructions", {})
                input_image_desc_from_prompt = prompt_details.get("input_image_description", "")

                gemini_api_parts = []
                if task_description:
                    gemini_api_parts.append({"text": task_description})
                if output_format_instructions_obj:
                    instructions_text = "Please adhere strictly to the following output format and schema:\n"
                    instructions_text += json.dumps(output_format_instructions_obj, indent=2)
                    gemini_api_parts.append({"text": instructions_text})
                if input_image_desc_from_prompt:
                    gemini_api_parts.append({"text": "Contextual description of the image provided:\n" + input_image_desc_from_prompt})
                
                gemini_api_parts = [part for part in gemini_api_parts if part.get("text", "").strip()]

                if not gemini_api_parts:
                    raise ValueError("Could not construct any valid text prompt parts from gemini_prompt for the primary Gemini API call.")

                gemini_raw = call_gemini_api(image_base64, gemini_api_parts)
                metrics["gemini_api_status"] = 200 # Assuming success if no HTTP error
                gemini_json_str = extract_json_string(gemini_raw)
                metrics["gemini_response_length"] = len(gemini_json_str or "")

                #print(f"--- DEBUG: Attempting to parse gemini_json_str (from primary Gemini call) ---")
                #print(f"Raw gemini_raw: {gemini_raw[:500]}...")
                #print(f"Extracted gemini_json_str: {gemini_json_str[:500]}...")
                #print(f"--- END DEBUG: gemini_json_str ---")

                if gemini_json_str:
                    gemini_json = json.loads(gemini_json_str)
                else:
                    gemini_json = {"error": "Empty JSON string from Gemini."}
                print("Received and parsed Gemini response")
            except json.JSONDecodeError as je:
                print(f"⚠️ JSON DECODING ERROR (Primary Gemini Call): {je}")
                print(f"Problematic JSON string (gemini_json_str) was: >>>\n{gemini_json_str}\n<<<")
                metrics["gemini_api_status"] = 500 
                metrics["gemini_error_message"] = f"JSONDecodeError: {je}"
                gemini_json = {"error": f"JSONDecodeError from Gemini: {je}", "raw_output": gemini_json_str}
            except Exception as e:
                print(f"⚠️ Gemini API error: {e}")
                metrics["gemini_api_status"] = 500
                metrics["gemini_error_message"] = str(e)
                gemini_json = {"error": f"Gemini API call failed: {e}"}

            # Call OpenAI
            openai_json = {}
            try:
                # Ensure openai_prompt is just the text string
                openai_raw = call_openai_api(openai_prompt, image_base64=image_base64, image_path=img_path)
                metrics["openai_api_status"] = 200
                openai_json_str = extract_json_string(openai_raw)
                metrics["openai_response_length"] = len(openai_json_str or "")

                #print(f"--- DEBUG: Attempting to parse openai_json_str ---")
                #print(f"Raw openai_raw: {openai_raw[:500]}...")
                #print(f"Extracted openai_json_str: {openai_json_str[:500]}...")
                #print(f"--- END DEBUG: openai_json_str ---")

                if openai_json_str:
                    openai_json = json.loads(openai_json_str)
                else:
                    openai_json = {"error": "Empty JSON string from OpenAI."}
                print("Received and parsed OpenAI response")
            except json.JSONDecodeError as je:
                print(f"⚠️ JSON DECODING ERROR (OpenAI Call): {je}")
                print(f"Problematic JSON string (openai_json_str) was: >>>\n{openai_json_str}\n<<<")
                metrics["openai_api_status"] = 500
                metrics["openai_error_message"] = f"JSONDecodeError: {je}"
                openai_json = {"error": f"JSONDecodeError from OpenAI: {je}", "raw_output": openai_json_str}
            except Exception as e:
                print(f"⚠️ OpenAI API error: {e}")
                metrics["openai_api_status"] = 500
                metrics["openai_error_message"] = str(e)
                openai_json = {"error": f"OpenAI API call failed: {e}"}

            # Consolidate results
            consolidated = {}
            try:
                # Pass the actual text content of consolidation_prompt
                consolidated = consolidate_responses(
                    image_base64=image_base64,
                    gemini_json_input=gemini_json, # Pass parsed JSON
                    openai_json_input=openai_json, # Pass parsed JSON
                    prompt=consolidation_prompt # This is the text content of consolidation_prompt.txt
                )
                metrics["genai_response_consolidation_status"] = 200 if consolidated and not consolidated.get("error") else 500
                metrics["genai_response_consolidation_response_length"] = len(json.dumps(consolidated)) if consolidated else 0
                if consolidated.get("error"):
                    metrics["json_consolidation_error_message"] = consolidated.get("error_details", consolidated.get("error"))

            except Exception as e: # Catchall for unexpected errors during consolidation call itself
                print(f"⚠️ Consolidation function error: {e}")
                metrics["genai_response_consolidation_status"] = 500
                metrics["json_consolidation_error_message"] = str(e)
                consolidated = {"gemini_original": gemini_json, "openai_original": openai_json, "verification-flag": "Fallback", "error_details": f"Consolidation function error: {str(e)}"}

            # Add content verification
            if isinstance(consolidated, dict) and consolidated.get("verification-flag") != "Fallback" and not consolidated.get("error"):
                metrics["content_verification_status"] = "success"
            elif consolidated.get("error"):
                metrics["content_verification_status"] = f"failed - {consolidated.get('error_details', 'Consolidation error')}"


            if isinstance(consolidated, list): # If consolidation returns a list directly (as per original prompt expectation)
                all_responses.extend(consolidated)
            elif isinstance(consolidated, dict) and "document_elements" in consolidated and isinstance(consolidated["document_elements"], list):
                # If it returns a dict like {"document_elements": [...]}
                all_responses.extend(consolidated["document_elements"])
            elif isinstance(consolidated, dict): # If it's a single dict object not matching above
                all_responses.append(consolidated) # Append the whole dict, might be an error object or fallback
            else: # Fallback for unexpected types
                print(f"⚠️ Unexpected type from consolidation: {type(consolidated)}. Appending as is.")
                all_responses.append({"error": "Unexpected consolidation output type", "raw_consolidated_output": str(consolidated)})


            print("Both the responses processed and appended.")
        except json.JSONDecodeError as je: # Should be caught by inner try-excepts now
            print(f"⚠️ Outer JSON decoding error for image {img_path}: {je} - THIS SHOULD HAVE BEEN CAUGHT INTERNALLY.")
            all_responses.append({"error": f"Outer JSONDecodeError processing page {page_num}", "details": str(je)})
        except Exception as e:
            print(f"❌ Error processing image {img_path}: {e}")
            all_responses.append({"error": f"General error processing page {page_num}", "details": str(e)})

        page_metrics.append(metrics)
        #if page_num < len(image_paths): # Avoid sleep after the last page
        #    print(f"Sleeping for 5 seconds before next page...")
        #    time.sleep(5)

    master_json_path = os.path.join(output_dir, "layout.json")
    with open(master_json_path, "w", encoding="utf-8") as f:
        json.dump(all_responses, f, indent=2, ensure_ascii=False)
    print(f"✅ Master JSON saved to: {master_json_path}")

    # Ensure all_responses is a list of dictionaries for tabular conversion
    if not isinstance(all_responses, list):
        print(f"⚠️ all_responses is not a list, it's {type(all_responses)}. Cannot convert to CSV/Excel/HTML directly.")
    elif all_responses and not all(isinstance(item, dict) for item in all_responses):
        print(f"⚠️ Not all items in all_responses are dictionaries. CSV/Excel/HTML conversion might be partial or fail.")
        # Attempt to convert only dict items, or log problematic items
        valid_items_for_conversion = [item for item in all_responses if isinstance(item, dict)]
        if valid_items_for_conversion:
            convert_json_to_csv_and_excel(valid_items_for_conversion, output_dir, base_filename="layout")
            convert_json_to_html(valid_items_for_conversion, output_dir, output_filename="layout.html")
        else:
            print("No valid dictionary items found in all_responses for conversion.")
    elif not all_responses:
        print("No responses to convert to CSV/Excel/HTML.")
    else: # It's a list of dicts
        convert_json_to_csv_and_excel(all_responses, output_dir, base_filename="layout")
        convert_json_to_html(all_responses, output_dir, output_filename="layout.html")


    # Save page summary to Excel
    summary_df = pd.DataFrame(page_metrics)
    summary_excel_path = os.path.join(output_dir, "page_summary.xlsx")
    try:
        summary_df.to_excel(summary_excel_path, index=False)
        print(f"✅ Page-level summary written to: {summary_excel_path}")
    except Exception as e:
        print(f"❌ Failed to save page summary to Excel: {e}")
        # Fallback: save as CSV
        summary_csv_path = os.path.join(output_dir, "page_summary.csv")
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
    output_dir_path = project_root_path / "tests" / "assets" / "output_doc_layout"
    image_dir_path = output_dir_path / "page_images"

    poppler_path_env = None

    print(f"Input PDF path: {pdf_path}")
    print(f"Output directory: {output_dir_path}")
    print(f"Image directory: {image_dir_path}")

    if not pdf_path.exists():
        print(f"❌ ERROR: PDF file not found at {pdf_path}")
        sys.exit(1)
    
    # Create output directories if they don't exist
    os.makedirs(output_dir_path, exist_ok=True)
    os.makedirs(image_dir_path, exist_ok=True)


    page_summary_data = process_pdf(
        pdf_path=str(pdf_path),
        output_dir=str(output_dir_path),
        image_dir=str(image_dir_path),
        poppler_path=poppler_path_env
    )

    # The page summary saving is now inside process_pdf, so this is just a confirmation.
    if page_summary_data:
        print("✅ PDF processing complete. Page summary generated.")
    else:
        print("⚠️ PDF processing completed, but no page summary data was returned.")