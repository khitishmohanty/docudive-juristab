import os
import time # Import the time module
from .database_connector import DatabaseConnector
from .html_parser import HtmlParser
from .gemini_client import GeminiClient
from utils.s3_manager import S3Manager 

class EnrichmentProcessor:
    def __init__(self, config: dict, prompt_path: str):
        """
        Initializes the processor.

        Args:
            config (dict): The application configuration dictionary.
            prompt_path (str): The file path to the prompt text file.
        """
        self.config = config
        self.html_parser = HtmlParser()
        
        # Initialize managers and clients
        self.s3_manager = S3Manager(region_name=config['aws']['default_region'])
        self.gemini_client = GeminiClient(model_name=config['models']['gemini']['model'])
        
        # Initialize database connectors
        self.source_db = DatabaseConnector(db_config=config['database']['source'])
        self.dest_db = DatabaseConnector(db_config=config['database']['destination'])
        
        # Load the prompt from the specified file path
        self.prompt = self._load_prompt(prompt_path)

    def _load_prompt(self, prompt_file: str) -> str:
        """Loads the prompt from a file."""
        try:
            print(f"Loading prompt from: {prompt_file}")
            with open(prompt_file, 'r') as f:
                return f.read()
        except FileNotFoundError:
            print(f"Error: Prompt file not found at '{prompt_file}'")
            raise

    def process_cases(self):
        """
        Main method to run the entire enrichment pipeline.
        Checks existing status to avoid reprocessing successful cases.
        """
        source_table_info = self.config['tables']['tables_to_read'][0]
        dest_table_info = self.config['tables']['tables_to_write'][0]
        
        source_table = source_table_info['table']
        dest_table = dest_table_info['table']
        
        s3_bucket = self.config['aws']['s3']['bucket_name']
        s3_base_folder = self.config['aws']['s3']['dest_folder']
        
        filenames = self.config['enrichment_filenames']

        cases_df = self.source_db.read_sql(f"SELECT id FROM {source_table}")
        print(f"Found {len(cases_df)} total cases in source table.")

        for index, row in cases_df.iterrows():
            source_id = str(row['id'])
            print(f"\n--- Checking case with source_id: {source_id} ---")
            
            # Define S3 paths early
            case_folder = os.path.join(s3_base_folder, source_id)
            html_file_key = os.path.join(case_folder, filenames['source_html'])
            txt_file_key = os.path.join(case_folder, filenames['extracted_text'])
            json_file_key = os.path.join(case_folder, filenames['jurismap_json'])

            # 1. Check for an existing status record
            status_row = self.dest_db.get_status_by_source_id(dest_table, source_id)

            if not status_row:
                print(f"No status record found for {source_id}. Creating new one.")
                try:
                    self.dest_db.insert_initial_status(table_name=dest_table, source_id=source_id)
                    status_row = self.dest_db.get_status_by_source_id(dest_table, source_id)
                    if not status_row:
                        print(f"CRITICAL: Failed to fetch newly created status for {source_id}. Skipping.")
                        continue
                except Exception as e:
                    print(f"Failed to insert initial status for {source_id}. Skipping. Error: {e}")
                    continue
            
            # 2. Process Text Extraction if its status is 'failed' or 'not started'
            text_content = None
            if status_row.status_text_extract in ('failed', 'not started'):
                print(f"Text extraction status is '{status_row.status_text_extract}'. Running process.")
                text_content = self._extract_and_save_text(s3_bucket, html_file_key, txt_file_key, dest_table, source_id)
            else:
                print("Text extraction already completed successfully. Loading existing text.")
                try:
                    text_content = self.s3_manager.get_file_content(s3_bucket, txt_file_key)
                except Exception as e:
                    print(f"Could not retrieve existing text file for {source_id}. Error: {e}")
                    # Can't proceed to JSON step without text
                    continue

            if not text_content:
                print(f"Cannot proceed for {source_id} due to missing text content.")
                continue

            # 3. Process JSON Generation if its status is 'failed' or 'not started'
            if status_row.status_json_valid in ('failed', 'not started'):
                print(f"JSON validation status is '{status_row.status_json_valid}'. Running process.")
                self._generate_and_save_json(text_content, s3_bucket, json_file_key, dest_table, source_id)
            else:
                print("JSON validation already completed successfully. Skipping.")
            
        print("\n--- All cases checked. ---")

    def _extract_and_save_text(self, bucket, html_key, txt_key, status_table, source_id):
        """Handles HTML download, text extraction, and saving to S3, including timing."""
        start_time = time.time()
        try:
            html_content = self.s3_manager.get_file_content(bucket, html_key)
            text_content = self.html_parser.extract_text(html_content)
            self.s3_manager.save_text_file(bucket, txt_key, text_content)
            
            duration = time.time() - start_time
            self.dest_db.update_step_result(status_table, source_id, 'text_extract', 'pass', duration)
            return text_content
        except Exception as e:
            duration = time.time() - start_time
            print(f"Text extraction failed for {source_id}. Error: {e}")
            self.dest_db.update_step_result(status_table, source_id, 'text_extract', 'failed', duration)
            return None

    def _generate_and_save_json(self, text_content, bucket, json_key, status_table, source_id):
        """Handles Gemini call, JSON validation, and saving to S3, including timing."""
        start_time = time.time()
        try:
            gemini_response = self.gemini_client.generate_json_from_text(self.prompt, text_content)
            
            if self.gemini_client.is_valid_json(gemini_response):
                self.s3_manager.save_json_file(bucket, json_key, gemini_response)
                duration = time.time() - start_time
                self.dest_db.update_step_result(status_table, source_id, 'json_valid', 'pass', duration)
            else:
                duration = time.time() - start_time
                print(f"Gemini response for {source_id} was not valid JSON.")
                self.dest_db.update_step_result(status_table, source_id, 'json_valid', 'failed', duration)
        except Exception as e:
            duration = time.time() - start_time
            print(f"JSON generation failed for {source_id}. Error: {e}")
            self.dest_db.update_step_result(status_table, source_id, 'json_valid', 'failed', duration)
