import os
import time
from datetime import datetime
import logging
import json
from config.config import Config
from src.extractor import MetadataExtractor
from src.database import DatabaseManager
from utils.gemini_client import GeminiClient
from utils.file_utils import get_full_s3_key
from utils.s3_client import S3Manager
import mysql.connector

# Configure root logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_records_to_process(db_manager, registry_config, jurisdiction_codes, years):
    """
    Retrieves records from the caselaw_registry table that need processing.
    Selects records where either rule-based or AI extraction has not passed.
    """
    if not db_manager._get_connection():
        return []

    cursor = db_manager.conn.cursor(dictionary=True)
    try:
        jurisdiction_placeholders = ', '.join(['%s'] * len(jurisdiction_codes))
        year_placeholders = ', '.join(['%s'] * len(years))
        
        query = f"""
            SELECT 
                cr.source_id, 
                cr.file_path, 
                cr.jurisdiction_code, 
                cr.status_content_download,
                COALESCE(ces.status_metadataextract_rulebased, 'pending') AS status_metadataextract_rulebased,
                COALESCE(ces.status_metadataextract_ai, 'pending') AS status_metadataextract_ai
            FROM 
                caselaw_registry AS cr
            LEFT JOIN 
                caselaw_enrichment_status AS ces ON cr.source_id = ces.source_id
            WHERE 
                cr.status_content_download = 'pass' 
                AND cr.jurisdiction_code IN ({jurisdiction_placeholders}) 
                AND cr.{registry_config['column']} IN ({year_placeholders})
                AND (
                    ces.source_id IS NULL 
                    OR ces.status_metadataextract_rulebased != 'pass' 
                    OR ces.status_metadataextract_ai != 'pass'
                )
        """
        
        params = jurisdiction_codes + years
        cursor.execute(query, params)
        records = cursor.fetchall()
        logging.info(f"Found {len(records)} records to process for jurisdictions {jurisdiction_codes} and years {years}.")
        return records
    except mysql.connector.Error as err:
        logging.error(f"Failed to query registry table: {err}")
        return []
    finally:
        cursor.close()
        db_manager.close_connection()


def process_record(record, config, field_mapping, db_columns, use_ai_extraction, prompt_content):
    """
    Processes a single case law record, running rule-based and/or AI extraction
    based on the record's current status.
    """
    source_id = record['source_id']
    logging.info(f"Processing record for source_id: {source_id}")

    process_start_time = datetime.now()
    status_updates = {}

    rulebased_status, ai_status = 'skip', 'skip'
    rulebased_duration, ai_duration = 0.0, 0.0
    input_tokens, output_tokens = 0, 0
    input_price, output_price = 0.0, 0.0
    
    metadata, counsel_firm_mappings = {}, []
    db_ops_successful = False

    needs_rulebased_processing = record.get('status_metadataextract_rulebased') != 'pass'
    needs_ai_processing = record.get('status_metadataextract_ai') != 'pass' and use_ai_extraction

    if not needs_rulebased_processing and not needs_ai_processing:
        logging.info(f"Skipping source_id: {source_id} as both steps have passed.")
        return

    aws_config = config.get('aws')
    s3_manager = S3Manager(region_name=aws_config['default_region'])
    s3_file_key = get_full_s3_key(record['source_id'], record['jurisdiction_code'], config)

    if not s3_file_key:
        logging.error(f"Could not construct S3 file key for {source_id}. Skipping.")
        return
        
    bucket_name = next((s3_cfg['bucket_name'] for s3_cfg in config.get('aws', 's3') if s3_cfg['jurisdiction_code'] == record['jurisdiction_code']), None)

    try:
        html_content = s3_manager.get_file_content(bucket_name, s3_file_key)
    except Exception as e:
        logging.error(f"Failed to download HTML file for {source_id}: {e}. Cannot proceed.")
        db_manager = DatabaseManager(config.get('database'))
        fail_updates = {
            "start_time_metadataextract": process_start_time,
            "end_time_metadataextract": datetime.now()
        }
        if needs_rulebased_processing: fail_updates["status_metadataextract_rulebased"] = 'fail'
        if needs_ai_processing: fail_updates["status_metadataextract_ai"] = 'fail'
        db_manager.update_enrichment_status(source_id, fail_updates)
        db_manager.close_connection()
        return

    # --- Step 1: Rule-based extraction ---
    if needs_rulebased_processing:
        logging.info(f"Running rule-based extraction for {source_id}")
        start_time = time.time()
        try:
            extractor = MetadataExtractor(field_mapping=field_mapping)
            extracted_meta, extracted_mappings = extractor.extract_from_html(html_content)
            if extracted_meta:
                metadata.update(extracted_meta)
                counsel_firm_mappings.extend(extracted_mappings)
                rulebased_status = 'pass'
                logging.info("Rule-based extraction successful.")
            else:
                rulebased_status = 'fail'
                logging.warning("Rule-based extraction yielded no metadata.")
        except Exception as e:
            rulebased_status = 'fail'
            logging.error(f"Rule-based extraction error: {e}")
        finally:
            rulebased_duration = time.time() - start_time

    # --- Step 2: AI-based extraction ---
    if needs_ai_processing:
        logging.info(f"Running AI extraction for {source_id}")
        start_time = time.time()
        try:
            gemini_config = config.get('models', 'gemini')
            gemini_client = GeminiClient(model_name=gemini_config['model'])
            raw_json, input_tokens, output_tokens = gemini_client.generate_json_from_text(prompt_content, html_content)
            
            pricing = gemini_config.get('pricing', {})
            input_price = (input_tokens / 1_000_000) * pricing.get('input_per_million', 0.0)
            output_price = (output_tokens / 1_000_000) * pricing.get('output_per_million', 0.0)

            if gemini_client.is_valid_json(raw_json):
                ai_data = json.loads(raw_json).get("filter_tags", {})
                if ai_data:
                    ai_status = 'pass'
                    json_filename = config.get('enrichment_filenames', 'jurismetadata_json')
                    json_s3_key = os.path.join(os.path.dirname(s3_file_key), json_filename)
                    s3_manager.save_json_file(bucket_name, json_s3_key, raw_json)
                    for key, value in ai_data.items():
                        if not metadata.get(key) and value:
                            metadata[key] = value
                else:
                    ai_status = 'fail'
                    logging.warning("AI response missing 'filter_tags'.")
            else:
                ai_status = 'fail'
                logging.error("AI response was not valid JSON.")
        except Exception as e:
            ai_status = 'fail'
            logging.error(f"AI extraction error: {e}")
        finally:
            ai_duration = time.time() - start_time

    # --- Step 3: Database Operations ---
    db_manager = DatabaseManager(config.get('database'))
    try:
        if metadata:
            if db_manager.check_and_upsert_caselaw_metadata(metadata, source_id, db_columns):
                if needs_rulebased_processing and counsel_firm_mappings:
                    db_ops_successful = db_manager.insert_counsel_firm_mapping(counsel_firm_mappings, source_id)
                else:
                    db_ops_successful = True
        else:
            db_ops_successful = True # No data to save, so not a DB failure.

        process_end_time = datetime.now()
        status_updates["start_time_metadataextract"] = process_start_time
        status_updates["end_time_metadataextract"] = process_end_time

        if needs_rulebased_processing:
            status_updates["status_metadataextract_rulebased"] = 'pass' if rulebased_status == 'pass' and db_ops_successful else 'fail'
            status_updates["duration_metadataextract_rulebased"] = rulebased_duration
        
        if needs_ai_processing:
            status_updates["status_metadataextract_ai"] = 'pass' if ai_status == 'pass' and db_ops_successful else 'fail'
            status_updates["duration_metadataextract_ai"] = ai_duration
            status_updates["token_input_metadataextract"] = input_tokens
            status_updates["token_output_metadataextract"] = output_tokens
            status_updates["token_input_price_metadataextract"] = input_price
            status_updates["token_output_price_metadataextract"] = output_price
        
        db_manager.update_enrichment_status(source_id, status_updates)
    
    finally:
        db_manager.close_connection()

    total_duration = (datetime.now() - process_start_time).total_seconds()
    logging.info(f"Finished processing {source_id}. Total duration: {total_duration:.2f}s")


def main():
    """
    Main function to run the case law metadata extraction process.
    """
    logging.info("Starting case law metadata extraction service...")
    
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(script_dir, "config", "config.yaml")
        config = Config(config_path=config_path)
        
        rulebased_on = config.get('extraction_switch', 'rulebased_extract')
        ai_on = config.get('extraction_switch', 'AI_extract')
        
        if not rulebased_on:
            logging.info("Rule-based extraction is turned off. Exiting.")
            return
            
        use_ai_extraction = rulebased_on and ai_on
        
        if use_ai_extraction:
            logging.info("Configuration loaded. Rule-based and AI extraction are enabled.")
        else:
            logging.info("Configuration loaded. Only rule-based extraction is enabled.")

    except (FileNotFoundError, ValueError) as e:
        logging.error(f"Failed to load configuration: {e}")
        return

    prompt_content = ""
    if use_ai_extraction:
        try:
            prompt_path = os.path.join(script_dir, "config", "prompt.txt")
            with open(prompt_path, 'r') as f:
                prompt_content = f.read()
            logging.info("Successfully loaded AI prompt from config folder.")
        except FileNotFoundError:
            logging.error("AI extraction is on, but 'prompt.txt' was not found in the 'config' directory. AI step will be skipped.")
            use_ai_extraction = False

    db_config = config.get('database')
    registry_config = config.get('tables_registry')
    jurisdiction_codes = [s3_config['jurisdiction_code'] for s3_config in config.get('aws', 's3')]
    processing_years = config.get('tables_registry', 'processing_years')

    caselaw_metadata_config = None
    for table_config in config.get('tables', 'tables_to_write'):
        if table_config.get('table') == 'caselaw_metadata':
            caselaw_metadata_config = table_config
            break
    
    if not caselaw_metadata_config:
        logging.error("Could not find 'caselaw_metadata' configuration in config.yaml.")
        return

    db_columns = list(caselaw_metadata_config['columns'].keys())

    field_mapping = {
        "Citation": "citation",
        "Key issues": "key_issues",
        "Catchwords": "keywords",
        "Judgment of": "presiding_officer",
        "Judge": "presiding_officer",
        "Panelist": "panelist",
        "Orders": "orders",
        "Decision": "decision",
        "Decision Date": "judgment_date",
        "Cases Cited": "cases_cited",
        "Legislation Cited": "legislation_cited",
        "Filenumber": "file_no",
        "Hearing Dates": "hearing_date",
        "Jurisdiction": "matter_type",
        "Parties": "parties",
        "Category": "category",
        "BJS Number": "bjs_number"
    }

    db_manager_for_fetch = DatabaseManager(db_config)
    records_to_process = get_records_to_process(db_manager_for_fetch, registry_config, jurisdiction_codes, processing_years)

    if not records_to_process:
        logging.info("No records to process. Exiting.")
        return

    for record in records_to_process:
        process_record(record, config, field_mapping, db_columns, use_ai_extraction, prompt_content)

    logging.info("All records processed.")

if __name__ == "__main__":
    main()