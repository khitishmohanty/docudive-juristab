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
from utils.pdf_text_extractor import (
    extract_text_from_pdf_chunk_pypdf2, 
    extract_text_from_chunk_ocr, 
    extract_text_and_links_from_chunk_fitz
)
from utils.text_utils import _verify_item_content_in_direct_text_fuzzy

from core.layout_gemini import _call_gemini_for_layout
from core.layout_openai import _call_openai_for_layout # Assuming this might be used later
# from core.page_processor import _orchestrate_page_processing # Commented out in original
from core.finalizer import _save_results



def _process_page_chunk(
    temp_chunk_pdf_path: str,
    original_pdf_page_indices: list,
    start_actual_page_num_in_pdf: int,
    genai_output_dir_path: str,
    poppler_bin,
    fuzzy_match_thresh,
    min_direct_text_len, # Min characters for PyPDF2/OCR fallback to be "sufficient"
    min_fitz_text_len    # Min characters for Fitz to be "sufficient"
):
    chunk_responses = []
    chunk_metrics_list = []
    num_intended_pages_in_chunk = len(original_pdf_page_indices)

    # 1. Encode PDF & 2. Call Gemini (remain the same as your last version)
    pdf_chunk_base64 = None
    if os.path.exists(temp_chunk_pdf_path):
        pdf_chunk_base64 = encode_pdf_to_base64(temp_chunk_pdf_path)
    else:
        print(f"⚠️ Temporary chunk PDF not found: {temp_chunk_pdf_path}. Skipping.")
        for i in range(num_intended_pages_in_chunk):
            actual_page_num = start_actual_page_num_in_pdf + i
            metrics = _initialize_page_metrics(actual_page_num)
            metrics["error"] = "temp_chunk_pdf_missing"; chunk_metrics_list.append(metrics)
            chunk_responses.append({"page_number": actual_page_num, "error": "temp_chunk_pdf_missing"})
        return chunk_responses, chunk_metrics_list

    gemini_call_specific_metrics = {}
    chunk_gemini_json_output = _call_gemini_for_layout(pdf_chunk_base64, start_actual_page_num_in_pdf, num_intended_pages_in_chunk, genai_output_dir_path, gemini_call_specific_metrics) if pdf_chunk_base64 else {"error": "skipped_no_base64_for_chunk"}


    # --- Perform Chunk-level Text Extractions ---
    pypdf2_texts_for_chunk_pages = []
    ocr_texts_for_chunk_pages = []
    fitz_data_for_chunk_pages = []
    extraction_error_occurred = False
    try:
        pypdf2_texts_for_chunk_pages = extract_text_from_pdf_chunk_pypdf2(temp_chunk_pdf_path)
        fitz_data_for_chunk_pages = extract_text_and_links_from_chunk_fitz(temp_chunk_pdf_path)
        ocr_texts_for_chunk_pages = extract_text_from_chunk_ocr(temp_chunk_pdf_path, poppler_path=poppler_bin)
        # (Optional validation of list lengths can be added here)
    except Exception as e_chunk_extraction:
        print(f"❌ Major error during chunk-level text extraction for {temp_chunk_pdf_path}: {e_chunk_extraction}")
        extraction_error_occurred = True
        # (Error handling as before)
        for i in range(num_intended_pages_in_chunk):
            actual_page_num = start_actual_page_num_in_pdf + i
            metrics = _initialize_page_metrics(actual_page_num)
            metrics["error"] = f"chunk_text_extraction_failed: {e_chunk_extraction}"
            metrics["pypdf2_status"] = "chunk_extraction_error" 
            metrics["ocr_status"] = "chunk_extraction_error"    
            metrics["fitz_extraction_status"] = "chunk_extraction_error"
            page_response_data = {"page_number": actual_page_num, "error": f"Chunk text extraction failed: {e_chunk_extraction}"}
            chunk_responses.append(page_response_data)
            chunk_metrics_list.append(metrics)
        return chunk_responses, chunk_metrics_list

    # --- Save combined Fitz data to _crawl.json (remains the same) ---
    # ... (logic for saving fitz_crawl_data_for_json_file to _crawl.json as per your previous request) ...
    first_page_actual_in_chunk_fitz = start_actual_page_num_in_pdf
    last_page_actual_in_chunk_fitz = start_actual_page_num_in_pdf + num_intended_pages_in_chunk - 1
    if num_intended_pages_in_chunk == 1:
        crawl_json_filename = f"page_{first_page_actual_in_chunk_fitz}_crawl.json"
    else:
        crawl_json_filename = f"page_{first_page_actual_in_chunk_fitz}_{last_page_actual_in_chunk_fitz}_crawl.json"
    crawl_json_filepath = os.path.join(genai_output_dir_path, crawl_json_filename)
    fitz_crawl_data_for_json_file = {} 
    for idx_for_fitz_save in range(num_intended_pages_in_chunk):
        actual_page_num_for_save = start_actual_page_num_in_pdf + idx_for_fitz_save
        page_fitz_text, page_fitz_links = "", []
        if not extraction_error_occurred and idx_for_fitz_save < len(fitz_data_for_chunk_pages):
            page_fitz_text, page_fitz_links = fitz_data_for_chunk_pages[idx_for_fitz_save]
        page_key = f"Page{actual_page_num_for_save}"
        fitz_crawl_data_for_json_file[page_key] = {
            "fitz_extracted_text": page_fitz_text.strip() if page_fitz_text else "",
            "extracted_hyperlinks": page_fitz_links if page_fitz_links else []
        }
    try:
        with open(crawl_json_filepath, "w", encoding="utf-8") as crawl_json_file:
            json.dump(fitz_crawl_data_for_json_file, crawl_json_file, indent=2, ensure_ascii=False)
        print(f"✅ Fitz crawl data for chunk saved.")
    except Exception as e_crawl_save:
        print(f"⚠️ Error writing Fitz crawl data to {crawl_json_filepath}: {e_crawl_save}")


    all_chosen_fallback_texts_for_chunk = [] # Initialize list to collect fallback texts

    # 3. Process each page's extracted data
    for page_idx_in_chunk in range(num_intended_pages_in_chunk):
        actual_page_num = start_actual_page_num_in_pdf + page_idx_in_chunk
        page_processing_start_time_specific = time.time()
        metrics = _initialize_page_metrics(actual_page_num)
        # ... (standard metrics setup: chunk_info, gemini_*) ...
        metrics["chunk_info"] = {
            "processed_in_chunk_starting_page": start_actual_page_num_in_pdf,
            "intended_pages_in_this_chunk": num_intended_pages_in_chunk,
            "page_index_within_chunk": page_idx_in_chunk 
        }
        metrics["gemini_chunk_call_status"] = gemini_call_specific_metrics.get("gemini_status", "unknown")
        metrics["time_sec_gemini_on_chunk"] = gemini_call_specific_metrics.get("time_sec_gemini")

        # Initialize specific metrics
        metrics["pypdf2_status"] = "not_attempted"
        metrics["pypdf2_char_count"] = 0
        metrics["ocr_status"] = "not_attempted"
        metrics["ocr_char_count"] = 0
        metrics["fitz_extraction_status"] = "not_attempted"
        metrics["fitz_text_char_count"] = 0
        metrics["fitz_link_count"] = 0
        metrics["fallback_text_method_used"] = "none" # For PyPDF2->OCR fallback
        metrics["fallback_text_status"] = "not_attempted"
        metrics["fallback_text_char_count"] = 0
        metrics["verification_text_source"] = "none"

        pypdf2_text_for_page = ""
        ocr_text_for_page = ""
        fitz_page_text_content_for_this_page = ""
        hyperlinks_from_fitz_content_for_this_page = []
        chosen_fallback_text_for_page = "" # This will hold the result of PyPDF2->OCR chain

        try:
            # --- Assign extracted data for the current page_idx_in_chunk ---
            direct_pypdf2_text_raw = pypdf2_texts_for_chunk_pages[page_idx_in_chunk] if not extraction_error_occurred and page_idx_in_chunk < len(pypdf2_texts_for_chunk_pages) else None
            pypdf2_text_for_page = direct_pypdf2_text_raw.strip() if direct_pypdf2_text_raw else ""
            metrics["pypdf2_char_count"] = len(pypdf2_text_for_page)
            metrics["pypdf2_status"] = "success" if direct_pypdf2_text_raw is not None and pypdf2_text_for_page else ("empty_result" if direct_pypdf2_text_raw is not None else "extraction_failed")
            
            ocr_text_raw = ocr_texts_for_chunk_pages[page_idx_in_chunk] if not extraction_error_occurred and page_idx_in_chunk < len(ocr_texts_for_chunk_pages) else None
            ocr_text_for_page = ocr_text_raw.strip() if ocr_text_raw else ""
            metrics["ocr_char_count"] = len(ocr_text_for_page)
            metrics["ocr_status"] = "success" if ocr_text_raw is not None and ocr_text_for_page else ("empty_result" if ocr_text_raw is not None else "extraction_failed")
            
            if not extraction_error_occurred and page_idx_in_chunk < len(fitz_data_for_chunk_pages):
                raw_fitz_text, raw_fitz_links = fitz_data_for_chunk_pages[page_idx_in_chunk]
                fitz_page_text_content_for_this_page = raw_fitz_text.strip() if raw_fitz_text else ""
                hyperlinks_from_fitz_content_for_this_page = raw_fitz_links if raw_fitz_links else []
                metrics["fitz_extraction_status"] = "success"
                metrics["fitz_text_char_count"] = len(fitz_page_text_content_for_this_page)
                metrics["fitz_link_count"] = len(hyperlinks_from_fitz_content_for_this_page)
            else:
                 metrics["fitz_extraction_status"] = "fitz_data_missing_or_extraction_error" if extraction_error_occurred else "fitz_data_missing_for_page_in_chunk"


            # --- Block 1: Reinstated Fallback Logic (PyPDF2 -> OCR) ---
            pypdf2_sufficient_for_fallback = False
            if metrics["pypdf2_status"] in ["success", "empty_result"]: # PyPDF2 attempt was made
                if pypdf2_text_for_page and len(pypdf2_text_for_page) > min_direct_text_len:
                    chosen_fallback_text_for_page = pypdf2_text_for_page
                    metrics["fallback_text_method_used"] = "direct_pypdf2"
                    metrics["fallback_text_status"] = "success_sufficient"
                    pypdf2_sufficient_for_fallback = True
                elif pypdf2_text_for_page: # PyPDF2 text exists but is short
                    chosen_fallback_text_for_page = pypdf2_text_for_page # Tentatively use it
                    metrics["fallback_text_method_used"] = "direct_pypdf2"
                    metrics["fallback_text_status"] = "success_insufficient_length"
                else: # PyPDF2 returned empty
                    metrics["fallback_text_method_used"] = "direct_pypdf2"
                    metrics["fallback_text_status"] = "empty_result"
            else: # PyPDF2 extraction failed
                metrics["fallback_text_method_used"] = "direct_pypdf2"
                metrics["fallback_text_status"] = "extraction_failed"

            if not pypdf2_sufficient_for_fallback:
                if metrics["ocr_status"] in ["success", "empty_result"]: # OCR attempt was made
                    if ocr_text_for_page and len(ocr_text_for_page) > min_direct_text_len: # Check OCR sufficiency
                        chosen_fallback_text_for_page = ocr_text_for_page # OCR overrides if sufficient
                        metrics["fallback_text_method_used"] = "ocr_fallback"
                        metrics["fallback_text_status"] = "success_sufficient"
                    elif ocr_text_for_page: # OCR text exists but is short
                        if not chosen_fallback_text_for_page: # Only use short OCR if PyPDF2 was empty/failed
                            chosen_fallback_text_for_page = ocr_text_for_page
                        metrics["fallback_text_method_used"] = "ocr_fallback"
                        metrics["fallback_text_status"] = "success_insufficient_length"
                    elif not chosen_fallback_text_for_page : # PyPDF2 was also empty/failed, and OCR is also empty
                        metrics["fallback_text_method_used"] = "ocr_fallback" # Mark OCR as attempted
                        metrics["fallback_text_status"] = "both_pypdf2_and_ocr_empty"
                    # If PyPDF2 was insufficient and OCR is empty, chosen_fallback_text_for_page retains insufficient PyPDF2
                    # and fallback_text_status reflects PyPDF2's insufficiency.
                elif not chosen_fallback_text_for_page : # OCR extraction failed & PyPDF2 was empty/failed
                     metrics["fallback_text_method_used"] = "ocr_fallback" # Mark OCR as attempted
                     metrics["fallback_text_status"] = "both_pypdf2_and_ocr_failed"


            metrics["fallback_text_char_count"] = len(chosen_fallback_text_for_page)
            all_chosen_fallback_texts_for_chunk.append(chosen_fallback_text_for_page) # Collect for chunk file

            # --- Determine Text for Content Verification ---
            text_for_content_verification = ""
            if metrics["fitz_extraction_status"] == "success" and \
               fitz_page_text_content_for_this_page and \
               len(fitz_page_text_content_for_this_page) >= min_fitz_text_len:
                text_for_content_verification = fitz_page_text_content_for_this_page
                metrics["verification_text_source"] = "fitz"
            elif chosen_fallback_text_for_page: # Use the result of the PyPDF2->OCR chain
                text_for_content_verification = chosen_fallback_text_for_page
                metrics["verification_text_source"] = metrics["fallback_text_method_used"]
            else:
                metrics["verification_text_source"] = "none_available"

            # --- Construct page_response_data ---
            page_data = {
                "page_number": actual_page_num,
                "gemini_layout_output_for_chunk": chunk_gemini_json_output,
                "pypdf2_extracted_text": pypdf2_text_for_page,
                "ocr_extracted_text": ocr_text_for_page,
                "chosen_fallback_text": chosen_fallback_text_for_page, # Text from PyPDF2->OCR chain
                "fitz_text_extracted": fitz_page_text_content_for_this_page,
                "fitz_hyperlinks": hyperlinks_from_fitz_content_for_this_page,
                "text_used_for_verification_source": metrics["verification_text_source"],
                "text_used_for_verification_char_count": len(text_for_content_verification),
            }
            chunk_responses.append(page_data)

        except IndexError: 
            print(f"❌ IndexError processing data for page {actual_page_num} (index {page_idx_in_chunk} in chunk) - extraction lists might be too short.")
            page_error_data = { "page_number": actual_page_num, "error": "IndexError during page data processing from chunk results."}
            chunk_responses.append(page_error_data)
            metrics["error"] = "page_data_processing_index_error"; # Add to metrics
            all_chosen_fallback_texts_for_chunk.append("") # Add empty fallback for this failed page
        except Exception as e_page_processing: 
            print(f"❌ Error processing data for page {actual_page_num} from chunk results: {e_page_processing}")
            page_error_data = {
                "page_number": actual_page_num, "error": f"Error processing page data: {e_page_processing}",
                "gemini_layout_output_for_chunk": chunk_gemini_json_output
            }
            chunk_responses.append(page_error_data)
            metrics["error"] = f"page_data_processing_failed: {e_page_processing}"; # Add to metrics
            all_chosen_fallback_texts_for_chunk.append("") # Add empty fallback for this failed page
        finally:
            metrics["time_sec_total_page_processing_in_chunk"] = time.time() - page_processing_start_time_specific
            chunk_metrics_list.append(metrics)

    # --- Save all collected fallback texts for the chunk to _crawl_fallback.txt ---
    first_page_fb_chunk = start_actual_page_num_in_pdf
    last_page_fb_chunk = start_actual_page_num_in_pdf + num_intended_pages_in_chunk - 1
    if num_intended_pages_in_chunk == 1:
        crawl_fallback_filename = f"page_{first_page_fb_chunk}_crawl_fallback.txt"
    else:
        crawl_fallback_filename = f"page_{first_page_fb_chunk}_{last_page_fb_chunk}_crawl_fallback.txt"
    crawl_fallback_filepath = os.path.join(genai_output_dir_path, crawl_fallback_filename)

    try:
        with open(crawl_fallback_filepath, "w", encoding="utf-8") as fb_file:
            for i, text_content in enumerate(all_chosen_fallback_texts_for_chunk):
                page_num_header = start_actual_page_num_in_pdf + i
                fb_file.write(f"--- Page {page_num_header} ---\n")
                fb_file.write(text_content + "\n\n")
        print(f"✅ Chosen fallback texts for chunk saved.")
    except Exception as e_save_fallback_txt:
        print(f"⚠️ Error saving fallback text file {crawl_fallback_filepath}: {e_save_fallback_txt}")

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
        
        print(f"\n⚙️  Processing chunk: Original Page(s) {[p_idx + 1 for p_idx in original_page_indices_in_chunk]}")

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
    output_dir_path = project_root_path / "tests" / "assets" / "outputs" / "functions" / "output_doc_layout"
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