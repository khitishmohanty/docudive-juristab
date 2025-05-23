import os
import sys
import json
import base64
import time
from pathlib import Path
import fitz

# Add project root to PYTHONPATH
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../"))
sys.path.insert(0, project_root)

# Local imports
from utils.prompt_loader import load_text_prompt, load_json_prompt
from utils.json_utils import extract_json_string
from utils.file_utils import encode_pdf_to_base64
from utils.pdf_utils import _create_temp_page_pdf
from utils.metrics_utils import _initialize_page_metrics

from core.layout_gemini import _call_gemini_for_layout
from core.layout_openai import _call_openai_for_layout
from core.page_processor import _consolidate_sanitize_verify, _extract_and_save_hyperlinks_for_page
from core.finalizer import _save_results

from utils.json_utils import extract_json_string # Ensure this is imported

# Load prompts from file
#gemini_prompt_config = load_json_prompt("gemini_layout_prompt.json") 
#openai_prompt_text = load_text_prompt("openai_layout_prompt.txt")
#consolidation_prompt_text = load_text_prompt("consolidation_prompt.txt")
enrichment_prompt_config = load_json_prompt("enrichment_prompt.json") 
#output_verification_prompt_text = load_text_prompt("output_verification_prompt.txt")
#sanitize_prompt_text = load_text_prompt("sanitize_prompt.txt")
hyperlink_extraction_prompt = load_text_prompt("hyperlink_prompt.txt")


def process_pdf(pdf_path: str, output_dir: str, temp_page_dir: str) -> list:
    os.makedirs(temp_page_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)
    genai_output_dir = os.path.join(output_dir, "genai_outputs")
    os.makedirs(genai_output_dir, exist_ok=True)

    print(f"📄 Processing PDF: {pdf_path} page by page.")

    all_responses = []
    page_metrics_list = []

    try:
        pdf_document = fitz.open(pdf_path)
    except Exception as e:
        print(f"❌ Failed to open PDF {pdf_path}: {e}")
        return []

    for page_index in range(len(pdf_document)):
        page_num_actual = page_index + 1
        print("---------------------")
        print(f"📤 Processing page: {page_num_actual}")

        metrics = _initialize_page_metrics(page_num_actual)
        page_processing_start_time = time.time()

        temp_pdf_page_path = os.path.join(temp_page_dir, f"temp_page_{page_num_actual}.pdf")
        pdf_page_base64 = None
        # Initialize hyperlink data structure for the current page
        # This will now be returned by the subfunction.
        # extracted_hyperlinks_data = {"hyperlinks": [], "status": "not_attempted", "error_message": ""}

        try:
            temp_pdf_creation_start_time = time.time()
            _create_temp_page_pdf(pdf_document, page_index, temp_pdf_page_path)
            metrics["time_sec_temp_pdf_creation"] = time.time() - temp_pdf_creation_start_time
            pdf_page_base64 = encode_pdf_to_base64(temp_pdf_page_path)

            gemini_json = _call_gemini_for_layout(pdf_page_base64, page_num_actual, genai_output_dir, metrics)
            openai_json = _call_openai_for_layout(temp_pdf_page_path, page_num_actual, genai_output_dir, metrics)

            # --- CALL NEW SUBFUNCTION FOR HYPERLINK EXTRACTION ---
            extracted_hyperlinks_data = _extract_and_save_hyperlinks_for_page(
                temp_pdf_page_path=temp_pdf_page_path,
                page_num_actual=page_num_actual,
                genai_output_dir=genai_output_dir,
                metrics=metrics, # Pass the metrics dict to be updated
                prompt_text=hyperlink_extraction_prompt # Pass the loaded prompt
            )
            # --- END HYPERLINK EXTRACTION CALL ---

            final_page_response = _consolidate_sanitize_verify(
                pdf_page_base64, gemini_json, openai_json,
                page_num_actual, genai_output_dir, temp_pdf_page_path, metrics
            )

            if isinstance(final_page_response, dict):
                final_page_response["page_hyperlinks"] = extracted_hyperlinks_data
            else:
                print(f"⚠️ final_page_response for page {page_num_actual} is not a dict. Wrapping with hyperlink data.")
                final_page_response = {
                    "error_from_processing": "Consolidation/Sanitization/Verification did not return a dict",
                    "original_response_content": str(final_page_response),
                    "page_number": page_num_actual,
                    "page_hyperlinks": extracted_hyperlinks_data,
                    "page_verification_status": metrics.get("verification_status", "fail - unknown state")
                }

            all_responses.append(final_page_response)
            print(f"✅ Page {page_num_actual} processed and response (including hyperlinks) appended.")

        except Exception as e_outer_page_processing:
            print(f"❌ Outer error processing page {page_num_actual} (temp PDF: {temp_pdf_page_path}): {e_outer_page_processing}")
            page_error_info = {
                "error": f"General error processing page {page_num_actual}", "details": str(e_outer_page_processing),
                "page_number": page_num_actual, "page_verification_status": "fail - page processing error",
                "page_hyperlinks": extracted_hyperlinks_data if 'extracted_hyperlinks_data' in locals() else {"hyperlinks": [], "status": "error_before_extraction", "error_message": "Outer processing error occurred before hyperlink extraction could complete."}
            }
            all_responses.append(page_error_info)
            metrics["verification_status"] = page_error_info["page_verification_status"]
            if metrics.get("hyperlink_extraction_status", "not attempted") == "not attempted":
                metrics["hyperlink_extraction_status"] = "aborted_due_to_outer_error"
                metrics["hyperlink_error_message"] = str(e_outer_page_processing)
        finally:
            metrics["time_sec_total_page_processing"] = time.time() - page_processing_start_time
            if os.path.exists(temp_pdf_page_path):
                try:
                    os.remove(temp_pdf_page_path)
                except Exception as e_delete:
                    print(f"⚠️ Failed to delete temporary PDF {temp_pdf_page_path}: {e_delete}")

        page_metrics_list.append(metrics)

    if pdf_document:
        pdf_document.close()

    _save_results(all_responses, page_metrics_list, output_dir)

    return page_metrics_list


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

    # Final summary
    if page_summary_data:
        print("✅ PDF processing complete. Page summary with verification generated.")
    else:
        print("⚠️ PDF processing completed, but no page summary data was returned.")


