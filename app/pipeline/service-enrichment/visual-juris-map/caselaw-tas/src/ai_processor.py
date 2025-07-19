import os
import time
import json
from utils.database_connector import DatabaseConnector
from utils.gemini_client import GeminiClient
from utils.s3_manager import S3Manager
from utils.html_generator import HtmlGenerator

class AiProcessor:
    def __init__(self, config: dict, prompt_path: str):
        self.config = config
        self.html_generator = HtmlGenerator()
        self.s3_manager = S3Manager(region_name=config['aws']['default_region'])
        self.gemini_client = GeminiClient(model_name=config['models']['gemini']['model'])
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
        dest_table_info = self.config['tables']['tables_to_write'][0]
        dest_table = dest_table_info['table']
        # Extract column config
        column_config = dest_table_info['columns']
        
        # Pass column_config to the query method
        cases_df = self.dest_db.get_records_for_ai_processing(dest_table, column_config)
        print(f"Found {len(cases_df)} cases ready for AI enrichment and visualization.")

        for index, row in cases_df.iterrows():
            source_id = str(row['source_id'])
            print(f"\n--- Processing AI/HTML for case: {source_id} ---")
            
            s3_bucket = self.config['aws']['s3']['bucket_name']
            s3_base_folder = self.config['aws']['s3']['dest_folder']
            filenames = self.config['enrichment_filenames']
            
            case_folder = os.path.join(s3_base_folder, source_id)
            txt_file_key = os.path.join(case_folder, filenames['extracted_text'])
            json_file_key = os.path.join(case_folder, filenames['jurismap_json'])
            tree_html_file_key = os.path.join(case_folder, filenames['jurismap_html'])

            json_content = None
            if getattr(row, column_config['json_valid_status']) != 'pass':
                print(f"JSON status is not 'pass'. Running process.")
                text_content = self.s3_manager.get_file_content(s3_bucket, txt_file_key)
                if text_content:
                    json_content = self._generate_and_save_json(text_content, s3_bucket, json_file_key, dest_table, source_id, column_config)
            else:
                print("JSON already generated. Loading from S3.")
                try:
                    json_string = self.s3_manager.get_file_content(s3_bucket, json_file_key)
                    json_content = json.loads(json_string)
                except Exception as e:
                    print(f"Could not load existing JSON for {source_id}. Error: {e}")
                    continue

            if not json_content:
                print(f"Skipping HTML generation for {source_id} due to missing JSON content.")
                continue

            if getattr(row, column_config['jurismap_html_status']) != 'pass':
                print(f"HTML status is not 'pass'. Running process.")
                self._generate_and_save_html_tree(json_content, s3_bucket, tree_html_file_key, dest_table, source_id, column_config)
            else:
                print("HTML tree already generated. Skipping.")

        print("\n--- AI Enrichment check completed for all cases. ---")

    def _generate_and_save_json(self, text_content, bucket, json_key, status_table, source_id, column_config):
        start_time = time.time()
        try:
            gemini_response_str = self.gemini_client.generate_json_from_text(self.prompt, text_content)
            if self.gemini_client.is_valid_json(gemini_response_str):
                self.s3_manager.save_json_file(bucket, json_key, gemini_response_str)
                duration = time.time() - start_time
                self.dest_db.update_step_result(status_table, source_id, 'json_valid', 'pass', duration, column_config)
                return json.loads(gemini_response_str)
            else:
                raise ValueError("Gemini response was not valid JSON.")
        except Exception as e:
            duration = time.time() - start_time
            print(f"JSON generation failed for {source_id}. Error: {e}")
            self.dest_db.update_step_result(status_table, source_id, 'json_valid', 'failed', duration, column_config)
            return None

    def _generate_and_save_html_tree(self, json_data, bucket, html_key, status_table, source_id, column_config):
        start_time = time.time()
        try:
            html_content = self.html_generator.generate_html_tree(json_data)
            self.s3_manager.save_text_file(bucket, html_key, html_content)
            duration = time.time() - start_time
            self.dest_db.update_step_result(status_table, source_id, 'jurismap_html', 'pass', duration, column_config)
        except Exception as e:
            duration = time.time() - start_time
            print(f"HTML tree generation failed for {source_id}. Error: {e}")
            self.dest_db.update_step_result(status_table, source_id, 'jurismap_html', 'failed', duration, column_config)