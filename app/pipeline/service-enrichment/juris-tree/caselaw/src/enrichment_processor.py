import os
import time
import json
from .database_connector import DatabaseConnector
from .html_parser import HtmlParser
from .gemini_client import GeminiClient
from utils.s3_manager import S3Manager
from utils.html_generator import HtmlGenerator # Import the new generator

class EnrichmentProcessor:
    def __init__(self, config: dict, prompt_path: str):
        self.config = config
        self.html_parser = HtmlParser()
        self.html_generator = HtmlGenerator() # Instantiate the generator
        
        self.s3_manager = S3Manager(region_name=config['aws']['default_region'])
        self.gemini_client = GeminiClient(model_name=config['models']['gemini']['model'])
        
        self.source_db = DatabaseConnector(db_config=config['database']['source'])
        self.dest_db = DatabaseConnector(db_config=config['database']['destination'])
        
        self.prompt = self._load_prompt(prompt_path)

    def _load_prompt(self, prompt_file: str) -> str:
        try:
            print(f"Loading prompt from: {prompt_file}")
            with open(prompt_file, 'r') as f:
                return f.read()
        except FileNotFoundError:
            print(f"Error: Prompt file not found at '{prompt_file}'")
            raise

    def process_cases(self):
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
            
            status_row = self.dest_db.get_status_by_source_id(dest_table, source_id)

            if not status_row:
                print(f"No status record found for {source_id}. Creating new one.")
                try:
                    self.dest_db.insert_initial_status(table_name=dest_table, source_id=source_id)
                    status_row = self.dest_db.get_status_by_source_id(dest_table, source_id)
                    if not status_row:
                        print(f"CRITICAL: Failed to fetch newly created status. Skipping.")
                        continue
                except Exception as e:
                    print(f"Failed to insert initial status for {source_id}. Skipping. Error: {e}")
                    continue
            
            if status_row.status_text_extract == 'pass' and status_row.status_json_valid == 'pass' and status_row.status_jurismap_html == 'pass':
                print(f"Case {source_id} has already been fully processed. Skipping.")
                continue

            case_folder = os.path.join(s3_base_folder, source_id)
            html_file_key = os.path.join(case_folder, filenames['source_html'])
            txt_file_key = os.path.join(case_folder, filenames['extracted_text'])
            json_file_key = os.path.join(case_folder, filenames['jurismap_json'])
            tree_html_file_key = os.path.join(case_folder, filenames['jurismap_html'])

            # Step 1: Text Extraction
            text_content = None
            if status_row.status_text_extract != 'pass':
                print(f"Text extraction status is '{status_row.status_text_extract}'. Running process.")
                text_content = self._extract_and_save_text(s3_bucket, html_file_key, txt_file_key, dest_table, source_id)
            else:
                print("Text extraction already completed. Loading existing text.")
                text_content = self.s3_manager.get_file_content(s3_bucket, txt_file_key)

            if not text_content: continue

            # Step 2: JSON Generation
            json_content = None
            if status_row.status_json_valid != 'pass':
                print(f"JSON validation status is '{status_row.status_json_valid}'. Running process.")
                json_content = self._generate_and_save_json(text_content, s3_bucket, json_file_key, dest_table, source_id)
            else:
                print("JSON generation already completed. Loading existing JSON.")
                json_string = self.s3_manager.get_file_content(s3_bucket, json_file_key)
                json_content = json.loads(json_string)

            if not json_content: continue

            # Step 3: HTML Tree Generation
            # --- FIX: Explicitly check for None, 'failed', or 'not started' ---
            if status_row.status_jurismap_html is None or status_row.status_jurismap_html in ('failed', 'not started'):
                print(f"HTML tree generation status is '{status_row.status_jurismap_html}'. Running process.")
                self._generate_and_save_html_tree(json_content, s3_bucket, tree_html_file_key, dest_table, source_id)
            else:
                print("HTML tree generation already completed successfully.")

        print("\n--- All cases checked. ---")

    def _extract_and_save_text(self, bucket, html_key, txt_key, status_table, source_id):
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
        start_time = time.time()
        try:
            gemini_response_str = self.gemini_client.generate_json_from_text(self.prompt, text_content)
            if self.gemini_client.is_valid_json(gemini_response_str):
                self.s3_manager.save_json_file(bucket, json_key, gemini_response_str)
                duration = time.time() - start_time
                self.dest_db.update_step_result(status_table, source_id, 'json_valid', 'pass', duration)
                return json.loads(gemini_response_str)
            else:
                raise ValueError("Gemini response was not valid JSON.")
        except Exception as e:
            duration = time.time() - start_time
            print(f"JSON generation failed for {source_id}. Error: {e}")
            self.dest_db.update_step_result(status_table, source_id, 'json_valid', 'failed', duration)
            return None

    def _generate_and_save_html_tree(self, json_data, bucket, html_key, status_table, source_id):
        """Generates and saves the HTML tree visualization."""
        start_time = time.time()
        try:
            html_content = self.html_generator.generate_html_tree(json_data)
            # Use save_text_file but specify html content type
            self.s3_manager.save_text_file(bucket, html_key, html_content) 
            duration = time.time() - start_time
            self.dest_db.update_step_result(status_table, source_id, 'jurismap_html', 'pass', duration)
        except Exception as e:
            duration = time.time() - start_time
            print(f"HTML tree generation failed for {source_id}. Error: {e}")
            self.dest_db.update_step_result(status_table, source_id, 'jurismap_html', 'failed', duration)

