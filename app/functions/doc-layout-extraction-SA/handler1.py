import os
import sys
import time
from pathlib import Path
import fitz # PyMuPDF - ensure it's imported if not already for _create_temp_chunk_pdf usage
import json

# Add project root to PYTHONPATH
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../"))
sys.path.insert(0, project_root)

# Local imports
from utils.file_utils import encode_pdf_to_base64
# Assuming _create_temp_chunk_pdf is in pdf_utils now, replace _create_temp_page_pdf
# from utils.pdf_utils import _create_temp_page_pdf # Old one
from utils.pdf_utils import _create_temp_chunk_pdf # New function, define it in your utils
from utils.metrics_utils import _initialize_page_metrics
from utils.pdf_text_extractor import extract_text_from_pdf_page, extract_text_from_ocr, extract_text_and_links_with_fitz
from utils.text_utils import _verify_item_content_in_direct_text_fuzzy

from core.layout_gemini import _call_gemini_for_layout
from core.layout_openai import _call_openai_for_layout # Assuming this might be used later
# from core.page_processor import _orchestrate_page_processing # Commented out in original
from core.finalizer import _save_results

# Definition of _create_temp_chunk_pdf (if not importing from utils.pdf_utils.py for this example)
# Move this to your utils/pdf_utils.py
# def _create_temp_chunk_pdf(original_pdf_doc: fitz.Document, start_page_index: int, num_pages_in_chunk: int, output_chunk_pdf_path: str):
#     new_pdf_doc = fitz.open()
#     end_page_index_in_original = min(start_page_index + num_pages_in_chunk, len(original_pdf_doc))
#     if start_page_index < end_page_index_in_original:
#         new_pdf_doc.insert_pdf(original_pdf_doc, from_page=start_page_index, to_page=end_page_index_in_original - 1)
#     new_pdf_doc.save(output_chunk_pdf_path)
#     new_pdf_doc.close()


def _process_page_chunk(
    temp_chunk_pdf_path: str,
    original_pdf_page_indices: list, # List of 0-based indices from the original PDF in this chunk
    start_actual_page_num_in_pdf: int, # Actual page number (1-based) of the first page in this chunk from original PDF
    genai_output_dir_path: str,
    poppler_bin,
    fuzzy_match_thresh,
    min_direct_text_len,
    min_fitz_text_len
):
    chunk_responses = []
    chunk_metrics_list = []

    # 1. Encode the entire chunk PDF for Gemini
    pdf_chunk_base64 = None
    if os.path.exists(temp_chunk_pdf_path):
        pdf_chunk_base64 = encode_pdf_to_base64(temp_chunk_pdf_path)
    else:
        print(f"⚠️ Temporary chunk PDF not found: {temp_chunk_pdf_path}. Skipping GenAI call.")
        # Populate empty results if chunk PDF is missing, or handle error as appropriate
        for i, original_page_idx in enumerate(original_pdf_page_indices):
            actual_page_num = start_actual_page_num_in_pdf + i
            metrics = _initialize_page_metrics(actual_page_num)
            metrics["error"] = "temp_chunk_pdf_missing"
            page_response_data = {"page_number": actual_page_num, "error": "Temporary chunk PDF was not created or found."}
            chunk_responses.append(page_response_data)
            chunk_metrics_list.append(metrics)
        return chunk_responses, chunk_metrics_list


    # 2. Call Gemini for the entire chunk
    gemini_call_specific_metrics = {} # For metrics related to this specific GenAI call
    chunk_gemini_json_output = None
    if pdf_chunk_base64:
        chunk_gemini_json_output = _call_gemini_for_layout(
            pdf_chunk_base64,
            start_actual_page_num_in_pdf, # Use starting page number to identify the chunk in logs/outputs
            genai_output_dir_path,
            gemini_call_specific_metrics # This dict can be updated by the call with time, status, etc.
        )
    else:
        gemini_call_specific_metrics["gemini_status"] = "skipped_no_base64_for_chunk"


    # 3. Process each page within the chunk PDF for text extraction and individual metrics
    try:
        doc_chunk_opened = fitz.open(temp_chunk_pdf_path)
    except Exception as e_open_chunk:
        print(f"❌ Error opening temporary chunk PDF {temp_chunk_pdf_path}: {e_open_chunk}")
        # Populate error results for all pages in this chunk
        for i, original_page_idx in enumerate(original_pdf_page_indices):
            actual_page_num = start_actual_page_num_in_pdf + i
            metrics = _initialize_page_metrics(actual_page_num)
            metrics["error"] = f"failed_to_open_temp_chunk_pdf: {e_open_chunk}"
            page_response_data = {"page_number": actual_page_num, "error": f"Failed to open temporary chunk PDF: {e_open_chunk}"}
            chunk_responses.append(page_response_data)
            chunk_metrics_list.append(metrics)
        return chunk_responses, chunk_metrics_list

    for page_idx_in_chunk_pdf in range(len(doc_chunk_opened)):
        actual_page_num = start_actual_page_num_in_pdf + page_idx_in_chunk_pdf
        page_processing_start_time_specific = time.time()

        metrics = _initialize_page_metrics(actual_page_num)
        metrics["chunk_info"] = {
            "processed_in_chunk_starting_page": start_actual_page_num_in_pdf,
            "pages_in_this_chunk_file": len(doc_chunk_opened),
            "page_index_within_chunk_file": page_idx_in_chunk_pdf
        }
        # Copy relevant metrics from the Gemini call to each page in the chunk
        metrics["gemini_chunk_call_status"] = gemini_call_specific_metrics.get("gemini_status", "unknown")
        metrics["time_sec_gemini_on_chunk"] = gemini_call_specific_metrics.get("time_sec_gemini") # Assuming _call_gemini adds this

        metrics["fallback_text_method_used"] = "none"
        metrics["fallback_text_status"] = "not_attempted"
        metrics["fallback_text_char_count"] = 0
        metrics["fitz_extraction_status"] = "not_attempted"
        metrics["fitz_text_char_count"] = 0
        metrics["fitz_link_count"] = 0
        metrics["verification_text_source"] = "none"

        chosen_text_from_fallback = ""
        fitz_page_text_content = ""
        hyperlinks_from_fitz_content = []

        try:
            # --- Block 1: Fallback Text Extraction (PyPDF2 -> OCR) for page_idx_in_chunk_pdf ---
            direct_pypdf2_sufficient = False
            try:
                # Process page_idx_in_chunk_pdf from temp_chunk_pdf_path
                direct_pypdf2_text = extract_text_from_pdf_page(temp_chunk_pdf_path, page_idx_in_chunk_pdf)
                if direct_pypdf2_text and len(direct_pypdf2_text.strip()) > min_direct_text_len:
                    chosen_text_from_fallback = direct_pypdf2_text.strip()
                    metrics["fallback_text_method_used"] = "direct_pypdf2"
                    metrics["fallback_text_status"] = "success"
                    direct_pypdf2_sufficient = True
                else: # PyPDF2 insufficient or empty
                    metrics["fallback_text_status"] = "direct_pypdf2_empty_or_insufficient"
            except Exception as e_direct:
                metrics["fallback_text_status"] = f"direct_pypdf2_fail: {str(e_direct)}"

            if not direct_pypdf2_sufficient:
                try:
                    ocr_text = extract_text_from_ocr(temp_chunk_pdf_path, page_idx_in_chunk_pdf, poppler_path=poppler_bin)
                    if ocr_text and len(ocr_text.strip()) > 0:
                        chosen_text_from_fallback = ocr_text.strip()
                        metrics["fallback_text_method_used"] = "ocr_fallback"
                        metrics["fallback_text_status"] = "success"
                    else: # OCR empty
                        metrics["fallback_text_method_used"] = "ocr_fallback"
                        metrics["fallback_text_status"] = "ocr_empty_result"
                except Exception as e_ocr:
                    metrics["fallback_text_method_used"] = "ocr_fallback"
                    metrics["fallback_text_status"] = f"ocr_fail: {str(e_ocr)}"
            
            metrics["fallback_text_char_count"] = len(chosen_text_from_fallback)
            if chosen_text_from_fallback:
                fb_text_path = os.path.join(genai_output_dir_path, f"page_{actual_page_num}_fallback_text.txt")
                with open(fb_text_path, "w", encoding="utf-8") as f: f.write(chosen_text_from_fallback)

            # --- Block 2: Fitz Text and Link Extraction for page_idx_in_chunk_pdf ---
            fitz_output_filename = f"page_{actual_page_num}_fitz_data.json"
            fitz_output_path = os.path.join(genai_output_dir_path, fitz_output_filename)
            try:
                extracted_text_fitz, hyperlinks_fitz = extract_text_and_links_with_fitz(temp_chunk_pdf_path, page_idx_in_chunk_pdf)
                fitz_page_text_content = extracted_text_fitz.strip() if extracted_text_fitz else ""
                hyperlinks_from_fitz_content = hyperlinks_fitz
                
                with open(fitz_output_path, "w", encoding="utf-8") as f:
                    json.dump({"page_number": actual_page_num, "fitz_extracted_text": fitz_page_text_content, "extracted_hyperlinks": hyperlinks_from_fitz_content}, f, indent=2, ensure_ascii=False)
                metrics["fitz_extraction_status"] = "success"
                metrics["fitz_text_char_count"] = len(fitz_page_text_content)
                metrics["fitz_link_count"] = len(hyperlinks_from_fitz_content)
            except Exception as e_fitz:
                metrics["fitz_extraction_status"] = f"fail: {str(e_fitz)}"
                with open(fitz_output_path, "w", encoding="utf-8") as f:
                    json.dump({"error": f"Fitz extraction failed for page {actual_page_num}: {str(e_fitz)}", "page_number": actual_page_num}, f, indent=2)

            # --- Determine Text for Content Verification ---
            text_for_content_verification = ""
            if metrics["fitz_extraction_status"] == "success" and fitz_page_text_content and len(fitz_page_text_content) >= min_fitz_text_len:
                text_for_content_verification = fitz_page_text_content
                metrics["verification_text_source"] = "fitz"
            elif chosen_text_from_fallback:
                text_for_content_verification = chosen_text_from_fallback
                metrics["verification_text_source"] = metrics["fallback_text_method_used"]
            else:
                metrics["verification_text_source"] = "none_available"

            # --- Construct page_response_data for this specific actual_page_num ---
            page_data = {
                "page_number": actual_page_num,
                "gemini_layout_output_for_chunk": chunk_gemini_json_output, # Shared by pages in the chunk
                "fallback_text_used": chosen_text_from_fallback if metrics["verification_text_source"] != "fitz" else "",
                "fitz_text_extracted": fitz_page_text_content,
                "fitz_hyperlinks": hyperlinks_from_fitz_content,
                "text_used_for_verification_source": metrics["verification_text_source"],
                "text_used_for_verification_char_count": len(text_for_content_verification),
                # Add other per-page extracted info as needed
            }
            # (Original verification logic was commented out, adapt if re-enabled)

            chunk_responses.append(page_data)
        
        except Exception as e_page_in_chunk:
            print(f"❌ Error processing page {actual_page_num} (index {page_idx_in_chunk_pdf} in chunk): {e_page_in_chunk}")
            page_error_data = {
                "page_number": actual_page_num,
                "error": f"Error processing page within chunk: {e_page_in_chunk}",
                "gemini_layout_output_for_chunk": chunk_gemini_json_output # Still include if available
            }
            chunk_responses.append(page_error_data)
            metrics["error"] = f"page_processing_in_chunk_failed: {e_page_in_chunk}"
            # Ensure all necessary metric fields are present even in error
            metrics["fallback_text_status"] = metrics.get("fallback_text_status", "error")
            metrics["fitz_extraction_status"] = metrics.get("fitz_extraction_status", "error")

        finally:
            metrics["time_sec_total_page_processing_in_chunk"] = time.time() - page_processing_start_time_specific
            chunk_metrics_list.append(metrics)

    doc_chunk_opened.close()
    return chunk_responses, chunk_metrics_list


def process_pdf(pdf_path: str, output_dir: str, temp_page_dir: str) -> list: # Returns page_metrics_list
    os.makedirs(temp_page_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)
    genai_output_dir = os.path.join(output_dir, "genai_outputs")
    os.makedirs(genai_output_dir, exist_ok=True)

    print(f"📄 Processing PDF: {pdf_path} in chunks of up to 2 pages.")

    all_page_responses = [] # Stores one entry per actual page
    all_page_metrics = []   # Stores one entry per actual page
    
    poppler_bin_path = None
    MIN_DIRECT_PYPDF2_TEXT_LENGTH_THRESHOLD = 20
    MIN_FITZ_TEXT_LENGTH_THRESHOLD = 20
    FUZZY_MATCH_THRESHOLD = 88
    
    pdf_document_original = None
    try:
        pdf_document_original = fitz.open(pdf_path)
    except Exception as e:
        print(f"❌ Failed to open PDF {pdf_path}: {e}")
        return [] 

    num_pages_total_original = len(pdf_document_original)
    print(f"Total pages in PDF: {num_pages_total_original}")

    for i in range(0, num_pages_total_original, 2): # Iterate by 2 for chunks
        original_page_indices_in_chunk = [i]
        num_pages_for_this_chunk = 1
        if i + 1 < num_pages_total_original:
            original_page_indices_in_chunk.append(i + 1)
            num_pages_for_this_chunk = 2
        
        start_actual_page_num = i + 1 # 1-based page number of the first page in chunk
        
        print(f"\n⚙️ Processing chunk: Original Page(s) {[p_idx + 1 for p_idx in original_page_indices_in_chunk]}")

        temp_chunk_pdf_file_path = os.path.join(temp_page_dir, f"temp_chunk_p{start_actual_page_num}.pdf")
        
        try:
            _create_temp_chunk_pdf(pdf_document_original, 
                                   original_page_indices_in_chunk[0], # start_page_index (0-based)
                                   num_pages_for_this_chunk, 
                                   temp_chunk_pdf_file_path)

            # Process the created chunk (1 or 2 pages)
            responses_from_chunk, metrics_from_chunk = _process_page_chunk(
                temp_chunk_pdf_file_path,
                original_page_indices_in_chunk,
                start_actual_page_num,
                genai_output_dir,
                poppler_bin_path,
                FUZZY_MATCH_THRESHOLD,
                MIN_DIRECT_PYPDF2_TEXT_LENGTH_THRESHOLD,
                MIN_FITZ_TEXT_LENGTH_THRESHOLD
            )
            all_page_responses.extend(responses_from_chunk)
            all_page_metrics.extend(metrics_from_chunk)

        except Exception as e_chunk_creation_or_processing:
            print(f"❌ Error creating or processing chunk starting at original page {start_actual_page_num}: {e_chunk_creation_or_processing}")
            # Add error entries for pages in this failed chunk
            for page_offset_in_failed_chunk in range(num_pages_for_this_chunk):
                failed_page_actual_num = start_actual_page_num + page_offset_in_failed_chunk
                error_metrics = _initialize_page_metrics(failed_page_actual_num)
                error_metrics["error"] = f"chunk_level_error: {e_chunk_creation_or_processing}"
                all_page_metrics.append(error_metrics)
                all_page_responses.append({
                    "page_number": failed_page_actual_num,
                    "error": f"Chunk level processing failed: {e_chunk_creation_or_processing}"
                })
        finally:
            if os.path.exists(temp_chunk_pdf_file_path):
                try:
                    os.remove(temp_chunk_pdf_file_path)
                except Exception as e_delete:
                    print(f"⚠️ Failed to delete temporary chunk PDF {temp_chunk_pdf_file_path}: {e_delete}")

    if pdf_document_original:
        pdf_document_original.close()

    _save_results(all_page_responses, all_page_metrics, output_dir)

    return all_page_metrics


if __name__ == "__main__":
    # Ensure utils.pdf_utils._create_temp_chunk_pdf is correctly defined and importable
    # For example, if you copied the _create_temp_chunk_pdf function into your handler.py for testing,
    # make sure it's available or properly imported from its utils location.

    try: import fitz
    except ImportError: print("❌ PyMuPDF (fitz) is not installed. Please install it using: pip install PyMuPDF"); sys.exit(1)
    try: import pytesseract # type: ignore
    except ImportError: print("⚠️ pytesseract library not found. OCR extraction will fail if Tesseract engine is not found.")
    try: from PyPDF2 import PdfReader # type: ignore
    except ImportError: print("⚠️ PyPDF2 library not found. Direct PyPDF2 text extraction will fail.")
    try: from pdf2image import convert_from_path # type: ignore
    except ImportError: print("⚠️ pdf2image library not found. OCR extraction will fail.")
    try: from thefuzz import fuzz # type: ignore
    except ImportError: print("⚠️ thefuzz library not found. Fuzzy verification will fail. pip install thefuzz python-Levenshtein")
 
    base_dir = Path(__file__).resolve().parent
    project_root_path = base_dir.parents[2]
  
    print(f"Project root for __main__ determined as: {project_root_path}")

    pdf_path = project_root_path / "tests" / "assets" / "inputs" / "sample.pdf" # Ensure sample.pdf exists
    output_dir_path = project_root_path / "tests" / "assets" / "outputs" / "functions" / "output_doc_layout_chunked"
    temp_pdf_page_dir_path = output_dir_path / "temp_pdf_chunks" # Changed name for clarity
    
    os.makedirs(output_dir_path, exist_ok=True)
    os.makedirs(temp_pdf_page_dir_path, exist_ok=True)

    print(f"Input PDF path: {pdf_path}")
    print(f"Output directory: {output_dir_path}")
    print(f"Temporary PDF chunk directory: {temp_pdf_page_dir_path}")

    if not pdf_path.exists():
        print(f"❌ ERROR: PDF file not found at {pdf_path}")
        sys.exit(1)

    # Make sure your sample.pdf has at least 1 page for testing.
    # You might want to test with 1, 2, and 3 page PDFs to check chunking logic.
    page_summary_metrics = process_pdf(
        pdf_path=str(pdf_path),
        output_dir=str(output_dir_path),
        temp_page_dir=str(temp_pdf_page_dir_path)
    )

    if page_summary_metrics:
        print(f"✅ PDF processing complete. Metrics for {len(page_summary_metrics)} pages generated.")
    else:
        print("⚠️ PDF processing completed, but no page summary metrics were returned (check for errors).")