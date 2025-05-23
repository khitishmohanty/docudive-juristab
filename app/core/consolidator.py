import json
from services.gemini_client import call_gemini_api
from utils.json_utils import extract_json_string
from utils.prompt_loader import load_json_prompt

gemini_prompt_config = load_json_prompt("gemini_layout_prompt.json") # Expects image

def consolidate_responses(pdf_page_base64: str, gemini_json_input, openai_json_input, prompt_text: str) -> dict:
    """
    Consolidates responses from Gemini and OpenAI using Gemini.
    Assumes the Gemini API call can handle base64 PDF data for context if needed.
    """
    global gemini_prompt_config # This is the layout prompt config

    try:
        prompt_details = gemini_prompt_config.get("prompt_details", {}) # Using layout prompt for schema reference
        task = prompt_details.get("task_description", "Consolidate the provided JSON outputs based on the task.")
        schema_obj = prompt_details.get("output_format_instructions", {})
        schema_str = json.dumps(schema_obj, indent=2)
        # Changed from "input_image_description" to a more generic term
        input_data_description = prompt_details.get("input_image_description", "Input is a page from a PDF document.")


        # Construct prompt parts for consolidation
        # The consolidation prompt itself (prompt_text) guides the main task.
        # The schema from the original layout prompt is used for structure.
        # PDF context is provided via pdf_page_base64 to call_gemini_api.
        consolidation_api_prompt_parts = [
            {"text": prompt_text},
            {"text": f"Original Task Context (related to layout extraction): {task}"},
            {"text": f"Contextual description of the PDF page provided: {input_data_description}"},
            {"text": f"Strictly adhere to this Output JSON Schema:\n{schema_str}"},
            {"text": f"GEMINI RESPONSE TO CONSOLIDATE:\n{json.dumps(gemini_json_input, indent=2)}"},
            {"text": f"OPENAI RESPONSE TO CONSOLIDATE:\n{json.dumps(openai_json_input, indent=2)}"}
        ]

        # This call now sends PDF base64 data and assumes call_gemini_api can handle it by setting mime_type.
        # This is a key change: call_gemini_api needs to be flexible.
        # (gemini_client.py needs: call_gemini_api(data_base64, prompt_parts, mime_type="application/pdf"))
        gemini_response = call_gemini_api(
            image_base64=pdf_page_base64, # Re-purposing image_base64 to carry pdf_base64
            prompt_parts=consolidation_api_prompt_parts,
            mime_type="application/pdf" # Explicitly setting mime type for PDF
        )
        result_text = gemini_response["text"]
        cleaned_json_str = extract_json_string(result_text)

        if cleaned_json_str:
            parsed_result = json.loads(cleaned_json_str)
            parsed_result["_consolidation_input_tokens"] = gemini_response.get("input_tokens", 0)
            parsed_result["_consolidation_output_tokens"] = gemini_response.get("output_tokens", 0)
            parsed_result["_consolidation_cost_usd"] = gemini_response.get("cost", 0.0)
            return parsed_result
        else: # Fallback if no valid JSON
            return {
                "error": "Consolidation failed to produce valid JSON",
                "gemini_original": gemini_json_input,
                "openai_original": openai_json_input,
                "verification_status_internal": "Fallback_NoValidJsonFromConsolidation",
                "raw_consolidation_output": result_text
            }


    except json.JSONDecodeError as je:
        print(f"❌ Consolidation JSON DECODING ERROR: {je}")
        # print(f"Problematic JSON string during consolidation was: >>>\n{cleaned_json_str}\n<<<") # cleaned_json_str might not be defined
        return {
            "gemini_original": gemini_json_input,
            "openai_original": openai_json_input,
            "verification_status_internal": "Fallback_JsonDecodeErrorInConsolidation",
            "error_details": str(je)
        }

    except Exception as e:
        print(f"❌ Consolidation failed with unexpected error: {e}")
        return {
            "gemini_original": gemini_json_input,
            "openai_original": openai_json_input,
            "verification_status_internal": "Fallback_ExceptionInConsolidation",
            "error_details": str(e)
        }