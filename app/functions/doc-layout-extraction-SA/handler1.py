import os
import sys
import time
from pathlib import Path
import fitz  # PyMuPDF
import json
import copy # For deep copying

# Add project root to PYTHONPATH
current_dir = os.path.dirname(os.path.abspath(__file__))
# Adjust this path if handler1.py is not two levels deep from project root
project_root = os.path.abspath(os.path.join(current_dir, "../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Local imports
try:
    from utils.file_utils import encode_pdf_to_base64
    from utils.pdf_utils import _create_temp_chunk_pdf
    from utils.metrics_utils import _initialize_page_metrics
    from utils.pdf_text_extractor import (
        extract_text_from_pdf_chunk_pypdf2,
        extract_text_from_chunk_ocr,
        extract_text_and_links_from_chunk_fitz
    )
    from utils.file_converters import convert_book_json_to_html
    from utils import text_utils
    from core.layout_gemini import _call_gemini_for_layout
    from core.finalizer import _save_results # This will be the modified finalizer
except ImportError as e:
    print(f"Error importing utility modules: {e}. Ensure PYTHONPATH is set correctly or modules are in the right location.")
    sys.exit(1)


def _process_page_chunk(
    temp_chunk_pdf_path: str,
    original_pdf_page_indices: list,
    start_actual_page_num_in_pdf: int,
    genai_output_dir_path: str,
    poppler_bin,
    fuzzy_match_thresh: int,
    min_direct_text_len: int,
    min_fitz_text_len: int,
    min_content_len_for_fuzzy: int
):
    """
    Processes a chunk of PDF pages, performs text extraction, calls GenAI,
    verifies content, matches hyperlinks, transforms, and saves page-specific outputs.
    """
    chunk_responses_for_results_json = []
    chunk_metrics_list = []
    num_intended_pages_in_chunk = len(original_pdf_page_indices)

    # 1. Encode PDF
    pdf_chunk_base64 = None
    if os.path.exists(temp_chunk_pdf_path):
        pdf_chunk_base64 = encode_pdf_to_base64(temp_chunk_pdf_path)
    else:
        print(f"⚠️ Temporary chunk PDF not found: {temp_chunk_pdf_path}. Skipping.")
        for i in range(num_intended_pages_in_chunk):
            actual_page_num = original_pdf_page_indices[i] + 1
            metrics = _initialize_page_metrics(actual_page_num)
            metrics["error"] = "temp_chunk_pdf_missing"
            chunk_metrics_list.append(metrics)
            original_genai_fn = f"page_{actual_page_num}_genai.json"
            final_content_fn = f"page_{actual_page_num}_final_content.json"
            chunk_responses_for_results_json.append({
                "page_number": actual_page_num,
                "error": "temp_chunk_pdf_missing",
                "gemini_original_output_file": original_genai_fn,
                "gemini_final_content_file": final_content_fn
            })
        return chunk_responses_for_results_json, chunk_metrics_list

    # 2. Call Gemini for Layout
    gemini_call_specific_metrics = {}
    chunk_gemini_json_output = _call_gemini_for_layout(
        pdf_chunk_base64,
        start_actual_page_num_in_pdf,
        num_intended_pages_in_chunk,
        gemini_call_specific_metrics
    ) if pdf_chunk_base64 else {
        "error": "skipped_no_base64_for_chunk",
        "processed_chunk_page_range": [
            start_actual_page_num_in_pdf,
            start_actual_page_num_in_pdf + num_intended_pages_in_chunk - 1
        ]
    }

    # 3. Perform Chunk-level Text Extractions
    pypdf2_texts_for_chunk_pages = []
    ocr_texts_for_chunk_pages = []
    fitz_data_for_chunk_pages = []
    extraction_error_occurred = False
    try:
        pypdf2_texts_for_chunk_pages = extract_text_from_pdf_chunk_pypdf2(temp_chunk_pdf_path)
        fitz_data_for_chunk_pages = extract_text_and_links_from_chunk_fitz(temp_chunk_pdf_path)
        ocr_texts_for_chunk_pages = extract_text_from_chunk_ocr(temp_chunk_pdf_path, poppler_path=poppler_bin)
    except Exception as e_chunk_extraction:
        print(f"❌ Major error during chunk-level text extraction for {temp_chunk_pdf_path}: {e_chunk_extraction}")
        extraction_error_occurred = True
        for i in range(num_intended_pages_in_chunk):
            actual_page_num = original_pdf_page_indices[i] + 1
            metrics = _initialize_page_metrics(actual_page_num)
            metrics["error"] = f"chunk_text_extraction_failed: {e_chunk_extraction}"
            chunk_metrics_list.append(metrics)
            original_genai_fn = f"page_{actual_page_num}_genai.json"
            final_content_fn = f"page_{actual_page_num}_final_content.json"
            page_response_data = {
                "page_number": actual_page_num,
                "error": f"Chunk text extraction failed: {e_chunk_extraction}",
                "gemini_original_output_file": original_genai_fn,
                "gemini_final_content_file": final_content_fn
            }
            chunk_responses_for_results_json.append(page_response_data)
        return chunk_responses_for_results_json, chunk_metrics_list

    # 4. Process each page's extracted data and save page-wise outputs
    for page_idx_in_chunk in range(num_intended_pages_in_chunk):
        actual_page_num = original_pdf_page_indices[page_idx_in_chunk] + 1
        page_processing_start_time_specific = time.time()
        metrics = _initialize_page_metrics(actual_page_num)

        original_genai_filename = f"page_{actual_page_num}_genai.json"
        final_content_filename = f"page_{actual_page_num}_final_content.json"

        metrics["chunk_info"] = {
            "processed_in_chunk_starting_page": start_actual_page_num_in_pdf,
            "intended_pages_in_this_chunk": num_intended_pages_in_chunk,
            "page_index_within_chunk": page_idx_in_chunk,
            "original_pdf_page_number": actual_page_num
        }
        metrics["gemini_chunk_call_status"] = gemini_call_specific_metrics.get("gemini_api_status", "unknown")
        metrics["time_sec_gemini_on_chunk"] = gemini_call_specific_metrics.get("time_sec_gemini_layout")
        metrics["gemini_input_tokens_on_chunk"] = gemini_call_specific_metrics.get("gemini_input_tokens")
        metrics["gemini_output_tokens_on_chunk"] = gemini_call_specific_metrics.get("gemini_output_tokens")
        metrics["gemini_cost_usd_on_chunk"] = gemini_call_specific_metrics.get("gemini_cost_usd")
        if gemini_call_specific_metrics.get("gemini_error_message"):
            metrics["gemini_error_message_on_chunk"] = gemini_call_specific_metrics.get("gemini_error_message")

        metrics["pypdf2_status"], metrics["pypdf2_char_count"] = "not_attempted", 0
        metrics["ocr_status"], metrics["ocr_char_count"] = "not_attempted", 0
        metrics["fitz_extraction_status"], metrics["fitz_text_char_count"], metrics["fitz_link_count"] = "not_attempted", 0, 0
        metrics["fallback_text_method_used"], metrics["fallback_text_status"], metrics["fallback_text_char_count"] = "none", "not_attempted", 0
        metrics["verification_text_source"], metrics["content_verification_status"] = "none", "not_attempted"

        pypdf2_text_for_page, ocr_text_for_page = "", ""
        fitz_page_text_content_for_this_page, hyperlinks_from_fitz_content_for_this_page = "", []
        chosen_fallback_text_for_page = ""
        genai_content_for_this_page_file = []

        try:
            direct_pypdf2_text_raw = pypdf2_texts_for_chunk_pages[page_idx_in_chunk] if not extraction_error_occurred and page_idx_in_chunk < len(pypdf2_texts_for_chunk_pages) else None
            pypdf2_text_for_page = direct_pypdf2_text_raw.strip() if direct_pypdf2_text_raw else "" # type: ignore
            metrics["pypdf2_char_count"] = len(pypdf2_text_for_page)
            metrics["pypdf2_status"] = "success" if direct_pypdf2_text_raw is not None and pypdf2_text_for_page else ("empty_result" if direct_pypdf2_text_raw is not None else "extraction_failed")

            ocr_text_raw = ocr_texts_for_chunk_pages[page_idx_in_chunk] if not extraction_error_occurred and page_idx_in_chunk < len(ocr_texts_for_chunk_pages) else None
            ocr_text_for_page = ocr_text_raw.strip() if ocr_text_raw else "" # type: ignore
            metrics["ocr_char_count"] = len(ocr_text_for_page)
            metrics["ocr_status"] = "success" if ocr_text_raw is not None and ocr_text_for_page else ("empty_result" if ocr_text_raw is not None else "extraction_failed")

            if not extraction_error_occurred and page_idx_in_chunk < len(fitz_data_for_chunk_pages):
                raw_fitz_text, raw_fitz_links = fitz_data_for_chunk_pages[page_idx_in_chunk]
                fitz_page_text_content_for_this_page = raw_fitz_text.strip() if raw_fitz_text else ""
                hyperlinks_from_fitz_content_for_this_page = raw_fitz_links if raw_fitz_links else []
                metrics["fitz_extraction_status"], metrics["fitz_text_char_count"], metrics["fitz_link_count"] = "success", len(fitz_page_text_content_for_this_page), len(hyperlinks_from_fitz_content_for_this_page)
            else:
                metrics["fitz_extraction_status"] = "fitz_data_missing_or_extraction_error" if extraction_error_occurred else "fitz_data_missing_for_page_in_chunk"

            page_crawl_json_filename = f"page_{actual_page_num}_crawl.json"
            page_crawl_json_filepath = os.path.join(genai_output_dir_path, page_crawl_json_filename)
            page_fitz_content_to_save = {"fitz_extracted_text": fitz_page_text_content_for_this_page, "extracted_hyperlinks": hyperlinks_from_fitz_content_for_this_page}
            try:
                with open(page_crawl_json_filepath, "w", encoding="utf-8") as crawl_file: json.dump(page_fitz_content_to_save, crawl_file, indent=2, ensure_ascii=False)
            except Exception as e_crawl_save: print(f"⚠️ Error writing Fitz crawl data to {page_crawl_json_filepath}: {e_crawl_save}"); metrics["error_saving_crawl_json"] = str(e_crawl_save)

            pypdf2_sufficient_for_fallback = False
            if metrics["pypdf2_status"] in ["success", "empty_result"]:
                if pypdf2_text_for_page and len(pypdf2_text_for_page) > min_direct_text_len: chosen_fallback_text_for_page = pypdf2_text_for_page; metrics["fallback_text_method_used"], metrics["fallback_text_status"], pypdf2_sufficient_for_fallback = "direct_pypdf2", "success_sufficient", True
                elif pypdf2_text_for_page: chosen_fallback_text_for_page = pypdf2_text_for_page; metrics["fallback_text_method_used"], metrics["fallback_text_status"] = "direct_pypdf2", "success_insufficient_length"
                else: metrics["fallback_text_method_used"], metrics["fallback_text_status"] = "direct_pypdf2", "empty_result"
            else: metrics["fallback_text_method_used"], metrics["fallback_text_status"] = "direct_pypdf2", "extraction_failed"
            if not pypdf2_sufficient_for_fallback:
                if metrics["ocr_status"] in ["success", "empty_result"]:
                    if ocr_text_for_page and len(ocr_text_for_page) > min_direct_text_len: chosen_fallback_text_for_page = ocr_text_for_page; metrics["fallback_text_method_used"], metrics["fallback_text_status"] = "ocr_fallback", "success_sufficient"
                    elif ocr_text_for_page:
                        if not chosen_fallback_text_for_page: chosen_fallback_text_for_page = ocr_text_for_page
                        metrics["fallback_text_method_used"], metrics["fallback_text_status"] = "ocr_fallback", "success_insufficient_length"
                    elif not chosen_fallback_text_for_page : metrics["fallback_text_method_used"], metrics["fallback_text_status"] = "ocr_fallback", "both_pypdf2_and_ocr_empty"
                elif not chosen_fallback_text_for_page : metrics["fallback_text_method_used"], metrics["fallback_text_status"] = "ocr_fallback", "both_pypdf2_and_ocr_failed"
            metrics["fallback_text_char_count"] = len(chosen_fallback_text_for_page)

            page_crawl_fallback_filename = f"page_{actual_page_num}_crawl_fallback.txt"; page_crawl_fallback_filepath = os.path.join(genai_output_dir_path, page_crawl_fallback_filename)
            try:
                with open(page_crawl_fallback_filepath, "w", encoding="utf-8") as fb_file: fb_file.write(f"--- Page {actual_page_num} ---\n"); fb_file.write(chosen_fallback_text_for_page + "\n\n")
            except Exception as e_save_fallback: print(f"⚠️ Error saving fallback text to {page_crawl_fallback_filepath}: {e_save_fallback}"); metrics["error_saving_fallback_txt"] = str(e_save_fallback)

            text_for_content_verification = ""
            if metrics["fitz_extraction_status"] == "success" and fitz_page_text_content_for_this_page and len(fitz_page_text_content_for_this_page) >= min_fitz_text_len: text_for_content_verification = fitz_page_text_content_for_this_page; metrics["verification_text_source"] = "fitz"
            elif chosen_fallback_text_for_page: text_for_content_verification = chosen_fallback_text_for_page; metrics["verification_text_source"] = metrics["fallback_text_method_used"]
            else: metrics["verification_text_source"] = "none_available"

            if isinstance(chunk_gemini_json_output, dict):
                page_key = f"Page{actual_page_num}"
                if page_key in chunk_gemini_json_output and isinstance(chunk_gemini_json_output[page_key], list):
                    genai_content_for_this_page_file = chunk_gemini_json_output[page_key]
                elif "items" in chunk_gemini_json_output and isinstance(chunk_gemini_json_output["items"], list):
                    genai_content_for_this_page_file = [item for item in chunk_gemini_json_output["items"] if isinstance(item, dict) and item.get("page_number") == actual_page_num]
                elif chunk_gemini_json_output.get("page_number") == actual_page_num and not any(k.startswith("Page") for k in chunk_gemini_json_output.keys()) and "items" not in chunk_gemini_json_output:
                     genai_content_for_this_page_file = [chunk_gemini_json_output]
                elif "error" in chunk_gemini_json_output:
                     genai_content_for_this_page_file = [chunk_gemini_json_output]
            
            if not (len(genai_content_for_this_page_file) == 1 and isinstance(genai_content_for_this_page_file[0], dict) and "error" in genai_content_for_this_page_file[0]):
                genai_content_for_this_page_file = copy.deepcopy(genai_content_for_this_page_file)

            original_genai_filepath = os.path.join(genai_output_dir_path, original_genai_filename)
            try:
                with open(original_genai_filepath, "w", encoding="utf-8") as f_orig_genai: json.dump(genai_content_for_this_page_file, f_orig_genai, indent=2, ensure_ascii=False)
            except Exception as e_save_orig_genai: print(f"⚠️ Error saving original Gemini data to {original_genai_filepath}: {e_save_orig_genai}"); metrics["error_saving_original_genai_json"] = str(e_save_orig_genai)

            if isinstance(genai_content_for_this_page_file, list) and genai_content_for_this_page_file:
                if not (len(genai_content_for_this_page_file) == 1 and isinstance(genai_content_for_this_page_file[0], dict) and "error" in genai_content_for_this_page_file[0]):
                    text_utils._verify_item_content_in_direct_text_fuzzy(
                        page_data_dict=genai_content_for_this_page_file, direct_text=text_for_content_verification,
                        page_num=actual_page_num, fuzzy_threshold=fuzzy_match_thresh, min_content_len_for_fuzzy=min_content_len_for_fuzzy)
                metrics["content_verification_status"] = "fuzzy_attempted"
            elif isinstance(genai_content_for_this_page_file, list) and not genai_content_for_this_page_file: metrics["content_verification_status"] = "skipped_empty_genai_content"
            else: metrics["content_verification_status"] = "skipped_genai_content_not_a_list"

            if isinstance(genai_content_for_this_page_file, list) and genai_content_for_this_page_file and hyperlinks_from_fitz_content_for_this_page:
                if not (len(genai_content_for_this_page_file) == 1 and isinstance(genai_content_for_this_page_file[0], dict) and "error" in genai_content_for_this_page_file[0]):
                    for genai_item in genai_content_for_this_page_file:
                        if isinstance(genai_item, dict) and "content" in genai_item:
                            item_content_value = genai_item.get("content")
                            if item_content_value and isinstance(item_content_value, str):
                                normalized_item_content = text_utils._normalize_text(item_content_value)
                                item_matched_hyperlinks = []
                                for hyperlink in hyperlinks_from_fitz_content_for_this_page:
                                    hyperlink_text = hyperlink.get("text")
                                    if hyperlink_text and isinstance(hyperlink_text, str):
                                        normalized_hyperlink_text = text_utils._normalize_text(hyperlink_text)
                                        if normalized_hyperlink_text and normalized_hyperlink_text in normalized_item_content:
                                            matched_link_info = {k: v for k, v in hyperlink.items() if k != 'rect'} # Exclude 'rect'
                                            item_matched_hyperlinks.append(matched_link_info)
                                if item_matched_hyperlinks:
                                    # Rename matched_hyperlinks to hyperlinks
                                    genai_item["hyperlinks"] = item_matched_hyperlinks # Assign directly, overwriting/creating "hyperlinks"
            
            # Post-process: Remove page_number from individual items and ensure correct hyperlink key name
            if isinstance(genai_content_for_this_page_file, list):
                for genai_item in genai_content_for_this_page_file:
                    if isinstance(genai_item, dict):
                        if "matched_hyperlinks" in genai_item and "hyperlinks" not in genai_item : # If renaming didn't happen perfectly above due to logic flow
                            genai_item["hyperlinks"] = genai_item.pop("matched_hyperlinks")
                        elif "matched_hyperlinks" in genai_item and "hyperlinks" in genai_item and genai_item["hyperlinks"] != genai_item["matched_hyperlinks"]:
                            # This case should ideally not happen if logic is clean, but as a safeguard
                            del genai_item["matched_hyperlinks"]


                        if "page_number" in genai_item:
                            del genai_item["page_number"]

            final_content_filepath = os.path.join(genai_output_dir_path, final_content_filename)
            try:
                with open(final_content_filepath, "w", encoding="utf-8") as f_final_genai: json.dump(genai_content_for_this_page_file, f_final_genai, indent=2, ensure_ascii=False)
            except Exception as e_save_final_genai: print(f"⚠️ Error saving final Gemini data to {final_content_filepath}: {e_save_final_genai}"); metrics["error_saving_final_genai_json"] = str(e_save_final_genai)

            page_data = {
                "page_number": actual_page_num, "gemini_original_output_file": original_genai_filename, "gemini_final_content_file": final_content_filename,
                "pypdf2_extracted_text": pypdf2_text_for_page, "ocr_extracted_text": ocr_text_for_page, "chosen_fallback_text": chosen_fallback_text_for_page,
                "fitz_text_extracted": fitz_page_text_content_for_this_page, "fitz_hyperlinks": hyperlinks_from_fitz_content_for_this_page,
                "text_used_for_verification_source": metrics["verification_text_source"], "text_used_for_verification_char_count": len(text_for_content_verification),
            }
            chunk_responses_for_results_json.append(page_data)

        except IndexError:
            print(f"❌ IndexError processing data for page {actual_page_num} (index {page_idx_in_chunk} in chunk).")
            page_error_data = {"page_number": actual_page_num, "error": "IndexError during page data processing.", "gemini_original_output_file": original_genai_filename, "gemini_final_content_file": final_content_filename}
            try:
                error_content = [{"error": page_error_data["error"]}]
                with open(os.path.join(genai_output_dir_path, final_content_filename), "w", encoding="utf-8") as f_err_final: json.dump(error_content, f_err_final, indent=2)
                if not os.path.exists(os.path.join(genai_output_dir_path, original_genai_filename)):
                    with open(os.path.join(genai_output_dir_path, original_genai_filename), "w", encoding="utf-8") as f_err_orig: json.dump(error_content, f_err_orig, indent=2)
            except Exception as e_save_err: print(f"⚠️ Error saving error JSON for page {actual_page_num}: {e_save_err}")
            chunk_responses_for_results_json.append(page_error_data); metrics["error"] = "page_data_processing_index_error"
        except Exception as e_page_processing:
            print(f"❌ Error processing data for page {actual_page_num}: {e_page_processing}")
            page_error_data = {"page_number": actual_page_num, "error": f"Error processing page data: {e_page_processing}", "gemini_original_output_file": original_genai_filename, "gemini_final_content_file": final_content_filename}
            try:
                error_content = [{"error": page_error_data["error"]}]
                with open(os.path.join(genai_output_dir_path, final_content_filename), "w", encoding="utf-8") as f_err_final: json.dump(error_content, f_err_final, indent=2)
                if not os.path.exists(os.path.join(genai_output_dir_path, original_genai_filename)):
                     with open(os.path.join(genai_output_dir_path, original_genai_filename), "w", encoding="utf-8") as f_err_orig: json.dump(error_content, f_err_orig, indent=2)
            except Exception as e_save_err: print(f"⚠️ Error saving error JSON for page {actual_page_num}: {e_save_err}")
            chunk_responses_for_results_json.append(page_error_data); metrics["error"] = f"page_data_processing_failed: {e_page_processing}"
        finally:
            metrics["time_sec_total_page_processing_in_chunk"] = time.time() - page_processing_start_time_specific
            chunk_metrics_list.append(metrics)

    return chunk_responses_for_results_json, chunk_metrics_list


def _create_book_output(all_page_data_for_results: list, genai_output_dir: str, main_output_dir: str):
    """
    Creates book_output.json by aggregating and transforming page_{N}_final_content.json files.
    The structure will be a dictionary with page numbers as keys.
    The 'rect' node will be removed from 'hyperlinks' (formerly 'matched_hyperlinks').
    The 'page_number' node will be removed from individual items.
    """
    book_data = {}
    print(f"\n📚 Creating consolidated book_output.json in {main_output_dir}")

    sorted_page_data = sorted(all_page_data_for_results, key=lambda x: x.get("page_number", float('inf')))

    for page_data in sorted_page_data:
        page_number = page_data.get("page_number")
        final_content_filename = page_data.get("gemini_final_content_file")

        if page_number is None or not final_content_filename:
            print(f"⚠️ Skipping page for book_output.json due to missing page_number or final_content_filename: {page_data}")
            continue

        final_content_filepath = os.path.join(genai_output_dir, final_content_filename)
        
        page_content_list_for_book = []
        try:
            if os.path.exists(final_content_filepath):
                with open(final_content_filepath, "r", encoding="utf-8") as f_final:
                    page_items_from_file = json.load(f_final)
                
                # Content from _final_content.json should already have 'hyperlinks' (not 'matched_hyperlinks')
                # and 'page_number' removed from items by _process_page_chunk.
                # This function just ensures the structure for book_output.json.
                # However, to be safe and ensure the "rect" removal is applied here if it wasn't perfectly done before or for other sources:
                processed_page_items = copy.deepcopy(page_items_from_file)

                if isinstance(processed_page_items, list):
                    for item in processed_page_items:
                        if isinstance(item, dict):
                            # Ensure 'hyperlinks' key and remove 'rect' from its contents
                            if "hyperlinks" in item and isinstance(item["hyperlinks"], list):
                                transformed_hyperlinks = []
                                for hyperlink_details in item["hyperlinks"]:
                                    if isinstance(hyperlink_details, dict):
                                        link_without_rect = {k: v for k, v in hyperlink_details.items() if k != 'rect'}
                                        transformed_hyperlinks.append(link_without_rect)
                                item["hyperlinks"] = transformed_hyperlinks
                            # Ensure page_number is removed if it somehow persisted
                            if "page_number" in item:
                                del item["page_number"]
                    page_content_list_for_book = processed_page_items
                else:
                    print(f"⚠️ Content of {final_content_filepath} for page {page_number} is not a list. Storing as is.")
                    page_content_list_for_book = processed_page_items 
            else:
                print(f"⚠️ File not found: {final_content_filepath} for page {page_number}. Storing error placeholder.")
                page_content_list_for_book = [{"error": f"File {final_content_filename} not found"}]
        
        except json.JSONDecodeError as je:
            print(f"⚠️ Error decoding JSON from {final_content_filepath} for page {page_number}: {je}. Storing error placeholder.")
            page_content_list_for_book = [{"error": f"JSONDecodeError in {final_content_filename}: {str(je)}"}]
        except Exception as e:
            print(f"⚠️ Unexpected error processing {final_content_filepath} for page {page_number}: {e}. Storing error placeholder.")
            page_content_list_for_book = [{"error": f"Unexpected error processing {final_content_filename}: {str(e)}"}]
            
        book_data[str(page_number)] = page_content_list_for_book

    book_output_filepath = os.path.join(main_output_dir, "book_output.json")
    try:
        with open(book_output_filepath, "w", encoding="utf-8") as f_book:
            json.dump(book_data, f_book, indent=2, ensure_ascii=False)
        print(f"✅ Successfully created {book_output_filepath}")
    except Exception as e_save_book:
        print(f"❌ Error saving consolidated book_output.json: {e_save_book}")


def process_pdf(pdf_path: str, output_dir: str, temp_page_dir: str) -> list:
    os.makedirs(temp_page_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)
    genai_output_dir = os.path.join(output_dir, "genai_outputs") 
    os.makedirs(genai_output_dir, exist_ok=True)

    CHUNK_SIZE_STR = os.environ.get('PDF_CHUNK_SIZE', '2')
    try:
        CHUNK_SIZE = int(CHUNK_SIZE_STR)
        if CHUNK_SIZE <= 0: CHUNK_SIZE = 2; print(f"⚠️ Invalid PDF_CHUNK_SIZE '{CHUNK_SIZE_STR}'. Defaulting to 2.")
    except ValueError: CHUNK_SIZE = 2; print(f"⚠️ PDF_CHUNK_SIZE '{CHUNK_SIZE_STR}' not valid int. Defaulting to 2.")
    print(f"📄 Processing PDF: {pdf_path} in chunks of up to {CHUNK_SIZE} pages.")

    all_page_responses_for_results_json, all_page_metrics = [], []
    poppler_bin_path = os.environ.get("POPPLER_PATH") 

    MIN_DIRECT_PYPDF2_TEXT_LENGTH_THRESHOLD = int(os.environ.get("MIN_PYPDF2_LEN", "20"))
    MIN_FITZ_TEXT_LENGTH_THRESHOLD = int(os.environ.get("MIN_FITZ_LEN", "20"))
    FUZZY_MATCH_THRESHOLD = int(os.environ.get("FUZZY_THRESHOLD", "88")) 
    MIN_CONTENT_LEN_FOR_FUZZY = int(os.environ.get("MIN_CONTENT_FUZZY_LEN", "4"))

    pdf_document_original = None
    try:
        pdf_document_original = fitz.open(pdf_path)
    except Exception as e:
        print(f"❌ Failed to open PDF {pdf_path}: {e}"); return []
    num_pages_total_original = len(pdf_document_original)
    print(f"Total pages in PDF: {num_pages_total_original}")

    for i in range(0, num_pages_total_original, CHUNK_SIZE):
        original_page_indices_in_chunk, num_pages_for_this_chunk = [], 0
        for page_offset in range(CHUNK_SIZE):
            current_original_page_index = i + page_offset
            if current_original_page_index < num_pages_total_original:
                original_page_indices_in_chunk.append(current_original_page_index); num_pages_for_this_chunk += 1
            else: break
        if num_pages_for_this_chunk == 0: continue

        start_actual_page_num_for_chunk = original_page_indices_in_chunk[0] + 1
        print(f"\n⚙️  Processing chunk: Original Page(s) {[p_idx + 1 for p_idx in original_page_indices_in_chunk]} (Actual: {start_actual_page_num_for_chunk} to {original_page_indices_in_chunk[-1] + 1})")
        temp_chunk_pdf_file_path = os.path.join(temp_page_dir, f"temp_chunk_p{start_actual_page_num_for_chunk}.pdf")

        try:
            _create_temp_chunk_pdf(pdf_document_original, original_page_indices_in_chunk[0], num_pages_for_this_chunk, temp_chunk_pdf_file_path)
            responses_from_chunk, metrics_from_chunk = _process_page_chunk(
                temp_chunk_pdf_file_path, original_page_indices_in_chunk,
                start_actual_page_num_for_chunk, genai_output_dir, poppler_bin_path, 
                FUZZY_MATCH_THRESHOLD, MIN_DIRECT_PYPDF2_TEXT_LENGTH_THRESHOLD,
                MIN_FITZ_TEXT_LENGTH_THRESHOLD, MIN_CONTENT_LEN_FOR_FUZZY
            )
            all_page_responses_for_results_json.extend(responses_from_chunk)
            all_page_metrics.extend(metrics_from_chunk)
        except Exception as e_chunk_creation_or_processing:
            print(f"❌ Error creating or processing chunk for original pages {original_page_indices_in_chunk}: {e_chunk_creation_or_processing}")
            for original_page_idx_in_failed_chunk in original_page_indices_in_chunk:
                failed_page_actual_num = original_page_idx_in_failed_chunk + 1
                error_metrics = _initialize_page_metrics(failed_page_actual_num); error_metrics["error"] = f"chunk_level_error: {e_chunk_creation_or_processing}"; all_page_metrics.append(error_metrics)
                orig_fn, final_fn = f"page_{failed_page_actual_num}_genai.json", f"page_{failed_page_actual_num}_final_content.json"
                all_page_responses_for_results_json.append({"page_number": failed_page_actual_num, "error": f"Chunk level processing failed: {e_chunk_creation_or_processing}", "gemini_original_output_file": orig_fn, "gemini_final_content_file": final_fn})
                try:
                    error_content_for_file = [{"error": f"Chunk level processing failed: {e_chunk_creation_or_processing}"}]
                    for fn_to_write_error in [orig_fn, final_fn]:
                        error_filepath = os.path.join(genai_output_dir, fn_to_write_error) 
                        with open(error_filepath, "w", encoding="utf-8") as f_err: json.dump(error_content_for_file, f_err, indent=2)
                except Exception as e_save_err: print(f"⚠️ Also failed to save error file for page {failed_page_actual_num}: {e_save_err}")
        finally:
            if os.path.exists(temp_chunk_pdf_file_path):
                try: os.remove(temp_chunk_pdf_file_path)
                except Exception as e_delete: print(f"⚠️ Failed to delete temporary chunk PDF {temp_chunk_pdf_file_path}: {e_delete}")

    if pdf_document_original: pdf_document_original.close()
    
    _save_results(all_page_responses_for_results_json, all_page_metrics, output_dir) 

    _create_book_output(all_page_responses_for_results_json, genai_output_dir, output_dir) 
    
    # After creating book_output.json, convert it to HTML
    book_output_json_path = os.path.join(output_dir, "book_output.json")
    if os.path.exists(book_output_json_path):
        try:
            with open(book_output_json_path, "r", encoding="utf-8") as f_book_json:
                book_data_for_html = json.load(f_book_json)
            # Make sure convert_book_json_to_html is imported at the top of handler1.py
            # from utils.file_converters import convert_book_json_to_html
            convert_book_json_to_html(book_data_for_html, output_dir, "book_output.html")
        except Exception as e_html_conversion:
            print(f"❌ Error converting book_output.json to HTML: {e_html_conversion}")
    else:
        print(f"⚠️ Could not find book_output.json at {book_output_json_path} for HTML conversion.")

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