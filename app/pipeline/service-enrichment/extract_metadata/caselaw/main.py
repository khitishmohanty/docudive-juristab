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
    """
    if not db_manager._get_connection():
        return []

    cursor = db_manager.conn.cursor(dictionary=True)
    try:
        jurisdiction_placeholders = ', '.join(['%s'] * len(jurisdiction_codes))
        year_placeholders = ', '.join(['%s'] * len(years))
        
        query = f"""
            SELECT cr.source_id, cr.file_path, cr.jurisdiction_code, cr.status_content_download 
            FROM caselaw_registry AS cr
            WHERE cr.status_content_download = 'pass' 
            AND cr.jurisdiction_code IN ({jurisdiction_placeholders}) 
            AND cr.{registry_config['column']} IN ({year_placeholders})
            AND NOT EXISTS (
                SELECT 1 FROM caselaw_enrichment_status AS ces
                WHERE cr.source_id = ces.source_id
                AND ces.status_metadataextract = 'pass'
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
    Processes a single case law record, with an optional AI enrichment step.
    """
    source_id = record['source_id']
    logging.info(f"Processing record for source_id: {source_id}")
    start_time = datetime.now()

    rulebased_success, ai_success, db_ops_successful = False, False, False
    input_tokens, output_tokens = 0, 0
    input_price, output_price = 0.0, 0.0

    aws_config = config.get('aws')
    s3_manager = S3Manager(region_name=aws_config['default_region'])
    
    jurisdiction_code = record['jurisdiction_code']
    s3_config_for_jurisdiction = next((s3_cfg for s3_cfg in config.get('aws', 's3') if s3_cfg['jurisdiction_code'] == jurisdiction_code), None)
    if not s3_config_for_jurisdiction:
        logging.error(f"Could not find S3 config for jurisdiction: {jurisdiction_code}")
        return

    bucket_name = s3_config_for_jurisdiction['bucket_name']
    s3_file_key = get_full_s3_key(record['source_id'], record['jurisdiction_code'], config)

    if not s3_file_key:
        logging.error(f"Could not construct a valid S3 file key for source_id: {source_id}. Skipping.")
        return

    try:
        html_content = s3_manager.get_file_content(bucket_name, s3_file_key)
    except Exception as e:
        logging.error(f"Failed to download HTML file: {e}. Cannot proceed with extraction.")
        return

    # Step 1: Rule-based extraction
    extractor = MetadataExtractor(field_mapping=field_mapping)
    metadata, counsel_firm_mappings = extractor.extract_from_html(html_content)

    if metadata:
        rulebased_success = True
        logging.info("Rule-based extraction successful.")
    else:
        logging.warning("Rule-based extraction yielded no metadata.")
        metadata = {}

    # Step 2: AI-based extraction (if enabled)
    if use_ai_extraction:
        s3_save_successful = False
        logging.info(f"AI extraction is enabled for source_id: {source_id}. Calling Gemini API.")
        try:
            gemini_config = config.get('models', 'gemini')
            gemini_client = GeminiClient(model_name=gemini_config['model'])
            
            raw_json_response, input_tokens, output_tokens = gemini_client.generate_json_from_text(prompt_content, html_content)

            if raw_json_response:
                try:
                    # Correctly get the filename using the provided Config class
                    json_filename = config.get('enrichment_filenames', 'jurismetadata_json')

                    if json_filename:
                        json_s3_folder = os.path.dirname(s3_file_key)
                        json_s3_key = os.path.join(json_s3_folder, json_filename)
                        
                        logging.info(f"Saving Gemini response to s3://{bucket_name}/{json_s3_key}")
                        s3_manager.save_json_file(bucket_name, json_s3_key, raw_json_response)
                        s3_save_successful = True
                    else:
                        logging.error("Failed to save Gemini response to S3: 'jurismetadata_json' filename not found in config.")
                except Exception as e:
                    logging.error(f"Failed to save Gemini response to S3: {e}")

            pricing_config = gemini_config.get('pricing', {})
            price_per_million_input = pricing_config.get('input_per_million', 0.0)
            price_per_million_output = pricing_config.get('output_per_million', 0.0)

            input_price = (input_tokens / 1_000_000) * price_per_million_input
            output_price = (output_tokens / 1_000_000) * price_per_million_output
            logging.info(f"AI usage for {source_id}: Input Tokens={input_tokens} (${input_price:.6f}), Output Tokens={output_tokens} (${output_price:.6f})")

            if gemini_client.is_valid_json(raw_json_response):
                gemini_data = json.loads(raw_json_response)
                ai_metadata = gemini_data.get("filter_tags", {})

                if ai_metadata and s3_save_successful:
                    ai_success = True
                    logging.info("AI extraction and S3 save successful.")
                    for key, value in ai_metadata.items():
                        if not metadata.get(key) and value:
                            metadata[key] = value
                else:
                    if not ai_metadata:
                        logging.warning("AI extraction failed: Response was missing 'filter_tags'.")
                    if not s3_save_successful:
                        logging.warning("AI extraction failed: Could not save response to S3.")
            else:
                logging.error("AI extraction failed: Invalid or empty JSON response.")
        except Exception as e:
            logging.error(f"An error occurred during AI extraction: {e}")

    # Step 3: Database operations
    db_config = config.get('database')
    db_manager = DatabaseManager(db_config)
    
    try:
        if metadata:
            if db_manager.check_and_upsert_caselaw_metadata(metadata, source_id, expected_columns=db_columns):
                if counsel_firm_mappings:
                    db_ops_successful = db_manager.insert_counsel_firm_mapping(counsel_firm_mappings, source_id)
                else:
                    db_ops_successful = True
        else:
            logging.error("Metadata is empty, skipping database operations.")
    finally:
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        final_status = 'fail'
        if use_ai_extraction:
            if rulebased_success and ai_success and db_ops_successful:
                final_status = 'pass'
        else:
            if rulebased_success and db_ops_successful:
                final_status = 'pass'

        db_manager.update_enrichment_status(
            source_id, final_status, start_time, end_time, duration,
            token_input=input_tokens,
            token_output=output_tokens,
            token_input_price=input_price,
            token_output_price=output_price
        )
        db_manager.close_connection()

    if final_status == 'pass':
        logging.info(f"Extraction process completed successfully for source_id: {source_id}.")
    else:
        logging.info(f"Extraction process failed for source_id: {source_id}.")
    logging.info(f"Total duration: {duration:.2f} seconds.")


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