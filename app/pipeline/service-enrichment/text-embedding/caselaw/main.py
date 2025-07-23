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
    Main function to orchestrate the caselaw embedding process.
    """
    print("Starting Caselaw Embedding Service...")
    
    # 1. Load Configuration
    config = load_config()
    
    # 2. Initialize Handlers
    try:
        db_handler = DatabaseHandler(config)
        s3_handler = S3Handler(config)
        embedding_generator = EmbeddingGenerator(config)
    except Exception as e:
        print(f"FATAL: Could not initialize handlers. Error: {e}")
        return

    # 3. Get list of cases to process
    print("Fetching cases to process from the database...")
    try:
        source_ids_to_process = db_handler.get_cases_to_process()
        if not source_ids_to_process:
            print("No new cases to process. Exiting.")
            return
        print(f"Found {len(source_ids_to_process)} cases to process.")
    except Exception as e:
        print(f"FATAL: Could not fetch cases from database. Error: {e}")
        return

    # 4. Find the S3 folder for each source_id
    print("Mapping source_ids to their respective S3 folders...")
    try:
        id_to_folder_map = db_handler.find_s3_folder_for_ids(
            source_ids_to_process, 
            config['tables']['tables_to_read']
        )
        print(f"Successfully mapped {len(id_to_folder_map)} IDs to S3 folders.")
    except Exception as e:
        print(f"FATAL: Could not map source IDs to S3 folders. Error: {e}")
        return

    # 5. Process each case
    print("Starting embedding generation for each case...")
    source_text_filename = config['enrichment_filenames']['source_text']
    embedding_output_filename = config['enrichment_filenames']['embedding_output']
    
    for source_id in tqdm(source_ids_to_process, desc="Processing Cases"):
        start_time = time.time()
        
        if source_id not in id_to_folder_map:
            print(f"Warning: Could not find a source table for source_id '{source_id}'. Skipping.")
            db_handler.update_embedding_status(source_id, 'fail_mapping')
            continue

        s3_folder = id_to_folder_map[source_id]
        
        try:
            # Construct S3 paths
            text_s3_key = f"{s3_folder}{source_id}/{source_text_filename}"
            embedding_s3_key = f"{s3_folder}{source_id}/{embedding_output_filename}"
            
            # --- Transactional Block for a single case ---
            
            # a. Get caselaw text from S3
            caselaw_text = s3_handler.get_caselaw_text(text_s3_key)
            
            # b. Calculate counts and update metadata table
            char_count = len(caselaw_text)
            word_count = len(caselaw_text.split()) # Simple word count by splitting on whitespace
            db_handler.update_metadata_counts(source_id, char_count, word_count)
            
            # c. Generate embedding
            embedding_vector = embedding_generator.generate_embedding_for_text(caselaw_text)
            
            if embedding_vector is None:
                raise ValueError("Embedding generation resulted in None (likely empty text).")

            # d. Save embedding to a bytes buffer
            embedding_bytes = embedding_generator.save_embedding_to_bytes(embedding_vector)
            
            # e. Upload embedding file to S3
            s3_handler.upload_embedding(embedding_s3_key, embedding_bytes)
            
            # f. If all successful, update DB status to 'pass'
            duration = time.time() - start_time
            db_handler.update_embedding_status(source_id, 'pass', duration)
            
        except Exception as e:
            # If any step fails, update DB status to 'fail'
            print(f"\nERROR processing source_id {source_id}: {e}")
            db_handler.update_embedding_status(source_id, 'fail')

    print("Caselaw Embedding Service finished.")


if __name__ == "__main__":
    main()
