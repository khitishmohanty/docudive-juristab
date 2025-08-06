# main.py

import os
import time
from dotenv import load_dotenv
from tqdm import tqdm

# Load environment variables from .env file at the very top
load_dotenv()

from utils.helpers import load_config, DatabaseHandler, S3Handler
from src.embedding_generator import EmbeddingGenerator

def main():
    """
    Main function to orchestrate the caselaw embedding process as a batch job.
    """
    print("Starting Caselaw Embedding Service (Batch Mode)...")
    
    # 1. Load Configuration
    config = load_config('config/config.yaml')
    
    # 2. Initialize Handlers
    try:
        # Use the DatabaseHandler that filters based on config (modified for optional filtering)
        db_handler = DatabaseHandler(config)
        s3_handler = S3Handler(config)
        embedding_generator = EmbeddingGenerator(config)
    except Exception as e:
        print(f"FATAL: Could not initialize handlers. Error: {e}")
        return

    # 3. Get years and jurisdictions to process from the config
    registry_config = config.get('tables_registry', {})
    processing_years = registry_config.get('processing_years', [])
    jurisdiction_codes = registry_config.get('jurisdiction_codes', [])

    if not processing_years or not jurisdiction_codes:
        print("FATAL: 'processing_years' or 'jurisdiction_codes' not found in config. Exiting.")
        return

    print(f"Configured to process years: {processing_years}")
    print(f"Configured to process jurisdictions: {jurisdiction_codes}")

    # 4. Loop through each year and then each jurisdiction from the config
    for year in processing_years:
        for jurisdiction in jurisdiction_codes:
            print(f"\n{'='*25}\nProcessing Year: {year}, Jurisdiction: {jurisdiction}\n{'='*25}")

            # 5. Get list of cases to process for the current year and jurisdiction
            try:
                # Use the DatabaseHandler that expects year and jurisdiction
                source_ids_to_process = db_handler.get_cases_to_process(year, jurisdiction)
                if not source_ids_to_process:
                    print(f"No new cases to process for {year}-{jurisdiction}. Continuing.")
                    continue
                print(f"Found {len(source_ids_to_process)} cases to process for {year}-{jurisdiction}.")
            except Exception as e:
                print(f"ERROR: Could not fetch cases for {year}-{jurisdiction}. Skipping. Error: {e}")
                continue

            # 6. Find the S3 folder for each source_id
            id_to_folder_map = db_handler.find_s3_folder_for_ids(
                source_ids_to_process, 
                config['tables']['tables_to_read']
            )

            # 7. Process each case
            desc = f"Processing {year}-{jurisdiction}"
            source_text_filename = config['enrichment_filenames']['source_text']
            embedding_output_filename = config['enrichment_filenames']['embedding_output']
            
            for source_id in tqdm(source_ids_to_process, desc=desc):
                # This processing loop is the same as in the handler
                start_time = time.time()
                if source_id not in id_to_folder_map:
                    db_handler.update_embedding_status(source_id, 'fail_mapping')
                    continue
                try:
                    s3_folder = id_to_folder_map[source_id]
                    text_s3_key = f"{s3_folder}{source_id}/{source_text_filename}"
                    embedding_s3_key = f"{s3_folder}{source_id}/{embedding_output_filename}"
                    caselaw_text = s3_handler.get_caselaw_text(text_s3_key)
                    embedding_vector = embedding_generator.generate_embedding_for_text(caselaw_text)
                    if embedding_vector is None:
                        raise ValueError("Embedding generation returned None.")
                    embedding_bytes = embedding_generator.save_embedding_to_bytes(embedding_vector)
                    s3_handler.upload_embedding(embedding_s3_key, embedding_bytes)
                    duration = time.time() - start_time
                    db_handler.update_embedding_status(source_id, 'pass', duration)
                except Exception as e:
                    print(f"\nERROR processing source_id {source_id}: {e}")
                    db_handler.update_embedding_status(source_id, 'fail')

    print("\nCaselaw Embedding Service batch job finished.")


if __name__ == "__main__":
    main()