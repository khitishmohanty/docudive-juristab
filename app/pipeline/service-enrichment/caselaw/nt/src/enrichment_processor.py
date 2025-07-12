import os
from .database_connector import DatabaseConnector
from .html_parser import HtmlParser
from .gemini_client import GeminiClient
from utils.s3_manager import S3Manager # Adjusted import path

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
        """
        source_table_info = self.config['tables']['tables_to_read'][0]
        dest_table_info = self.config['tables']['tables_to_write'][0]
        
        source_table = source_table_info['table']
        dest_table = dest_table_info['table']
        
        s3_bucket = self.config['aws']['s3']['bucket_name']
        s3_base_folder = self.config['aws']['s3']['dest_folder']

        # 1. Read all cases from the source table
        print(f"Reading cases from table: {source_table}")
        cases_df = self.source_db.read_sql(f"SELECT id FROM {source_table}")
        
        print(f"Found {len(cases_df)} cases to process.")

        # 2. Iterate through each case
        for index, row in cases_df.iterrows():
            source_id = str(row['id']) # Ensure source_id is a string
            print(f"\n--- Processing case with source_id: {source_id} ---")
            
            # Define S3 paths
            case_folder = os.path.join(s3_base_folder, source_id)
            # --- FIX: Corrected filename from 'mini_viewer.html' to 'miniviewer.html' ---
            html_file_key = os.path.join(case_folder, 'miniviewer.html')
            txt_file_key = os.path.join(case_folder, 'miniviewer.txt')
            json_file_key = os.path.join(case_folder, 'jurismap.json')
            
            # 3. Insert initial status record
            try:
                self.dest_db.insert_initial_status(table_name=dest_table, source_id=source_id)
            except Exception as e:
                print(f"Failed to insert initial status for {source_id}. Skipping case. Error: {e}")
                continue

            # 4. Process Text Extraction
            text_content = self._extract_and_save_text(s3_bucket, html_file_key, txt_file_key, dest_table, source_id)
            if not text_content:
                continue # Skip to next case if text extraction failed

            # 5. Process JSON Generation and Validation
            self._generate_and_save_json(text_content, s3_bucket, json_file_key, dest_table, source_id)
            
        print("\n--- All cases processed. ---")

    def _extract_and_save_text(self, bucket, html_key, txt_key, status_table, source_id):
        """Handles HTML download, text extraction, and saving to S3."""
        try:
            html_content = self.s3_manager.get_file_content(bucket, html_key)
            text_content = self.html_parser.extract_text(html_content)
            self.s3_manager.save_text_file(bucket, txt_key, text_content)
            self.dest_db.update_status(status_table, source_id, 'status_text_extract', 'pass')
            return text_content
        except Exception as e:
            print(f"Text extraction failed for {source_id}. Error: {e}")
            self.dest_db.update_status(status_table, source_id, 'status_text_extract', 'failed')
            return None

    def _generate_and_save_json(self, text_content, bucket, json_key, status_table, source_id):
        """Handles Gemini call, JSON validation, and saving to S3."""
        try:
            gemini_response = self.gemini_client.generate_json_from_text(self.prompt, text_content)
            
            if self.gemini_client.is_valid_json(gemini_response):
                self.s3_manager.save_text_file(bucket, json_key, gemini_response)
                self.dest_db.update_status(status_table, source_id, 'status_json_valid', 'pass')
            else:
                print(f"Gemini response for {source_id} was not valid JSON.")
                self.dest_db.update_status(status_table, source_id, 'status_json_valid', 'failed')
        except Exception as e:
            print(f"JSON generation failed for {source_id}. Error: {e}")
            self.dest_db.update_status(status_table, source_id, 'status_json_valid', 'failed')
