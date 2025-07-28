import os
import time
import json
from datetime import datetime, timezone
from utils.database_connector import DatabaseConnector
from utils.gemini_client import GeminiClient
from utils.s3_manager import S3Manager
from utils.html_generator import HtmlGenerator

class AiProcessor:
    # __init__ now accepts a 'source_info' dictionary and a 'processing_year'.
    def __init__(self, config: dict, prompt_path: str, source_info: dict, processing_year: int):
        self.config = config
        self.source_info = source_info # Store the specific source config
        self.processing_year = processing_year # Store the processing year
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
        column_config = dest_table_info['columns']
        
        registry_config = self.config.get('tables_registry', {})
        if not registry_config or 'column' not in registry_config:
            raise ValueError("Configuration error: 'tables_registry' with a 'column' key is not defined in config.yaml")

        cases_df = self.dest_db.get_records_for_ai_processing(
            dest_table, 
            column_config, 
            self.source_info,
            self.processing_year,
            registry_config
        )
        
        source_table_name = self.source_info['table']
        print(f"Found {len(cases_df)} cases for year {self.processing_year} from source '{source_table_name}' ready for AI enrichment.")

        for index, row in cases_df.iterrows():
            source_id = str(row['source_id'])
            print(f"\n--- Processing AI/HTML for case: {source_id} ---")
            
            s3_bucket = self.config['aws']['s3']['bucket_name']
            s3_base_folder = self.source_info['s3_dest_folder']
            filenames = self.config['enrichment_filenames']
            
            case_folder = os.path.join(s3_base_folder, source_id)
            txt_file_key = os.path.join(case_folder, filenames['extracted_text'])
            summary_json_file_key = os.path.join(case_folder, filenames['jurismap_json'])
            filter_json_file_key = os.path.join(case_folder, filenames['jurisfilter_json'])
            tree_html_file_key = os.path.join(case_folder, filenames['jurismap_html'])

            json_summary_content = None
            if getattr(row, column_config['json_valid_status']) != 'pass':
                print(f"JSON status is not 'pass'. Running process.")
                text_content = self.s3_manager.get_file_content(s3_bucket, txt_file_key)
                if text_content:
                    json_summary_content = self._generate_and_save_json(
                        text_content, 
                        s3_bucket, 
                        summary_json_file_key, 
                        filter_json_file_key,
                        dest_table, 
                        source_id, 
                        column_config
                    )
            else:
                print("JSONs already generated. Loading summary from S3 for HTML generation.")
                try:
                    # Only load the summary JSON, as that's what's needed for HTML
                    json_string = self.s3_manager.get_file_content(s3_bucket, summary_json_file_key)
                    json_summary_content = json.loads(json_string)
                except Exception as e:
                    print(f"Could not load existing summary JSON for {source_id}. Error: {e}")
                    continue

            if not json_summary_content:
                print(f"Skipping HTML generation for {source_id} due to missing JSON summary content.")
                continue

            if getattr(row, column_config['html_status']) != 'pass':
                print(f"HTML status is not 'pass'. Running process.")
                self._generate_and_save_html_tree(json_summary_content, s3_bucket, tree_html_file_key, dest_table, source_id, column_config)
            else:
                print("HTML tree already generated. Skipping.")

        print(f"\n--- AI Enrichment check completed for source: {source_table_name} for year {self.processing_year} ---")
    
    def _generate_and_save_json(self, text_content, bucket, summary_json_key, filter_json_key, status_table, source_id, column_config):
        """
        Generates a full JSON from text, then splits it into two files (summary and filter),
        saves the filter data to the database, and saves both JSON files to S3.
        The json_valid_status is only passed if all steps are successful.
        """
        start_time_dt = datetime.now(timezone.utc)
        input_tokens, output_tokens = 0, 0
        input_price, output_price = 0.0, 0.0

        try:
            # Step 1: Get response from Gemini and calculate cost
            gemini_response_str, input_tokens, output_tokens = self.gemini_client.generate_json_from_text(self.prompt, text_content)
            pricing_config = self.config['models']['gemini']['pricing']
            input_price = (pricing_config['input_per_million'] / 1000000) * input_tokens
            output_price = (pricing_config['output_per_million'] / 1000000) * output_tokens
            print(f"Gemini Token Usage - Input: {input_tokens} (${input_price:.6f}), Output: {output_tokens} (${output_price:.6f})")

            # Step 2: Validate and parse the full JSON response
            if not self.gemini_client.is_valid_json(gemini_response_str):
                raise ValueError("Gemini response was not valid JSON.")
            full_data = json.loads(gemini_response_str)

            # Step 3: Extract and validate the two data parts
            filter_tags_data = full_data.get("filter_tags")
            summary_data = {
                "caseTitle": full_data.get("caseTitle"),
                "caseSubtitle": full_data.get("caseSubtitle"),
                "cards": full_data.get("cards")
            }
            if not filter_tags_data or not summary_data.get("cards"):
                raise ValueError("Parsed JSON is missing 'filter_tags' or 'cards' key.")

            # Step 4: Save filter tags to the metadata database
            metadata_config = self.config.get('tables_metadata')
            if not metadata_config:
                raise ValueError("Configuration for 'tables_metadata' is missing from config.yaml.")
            self.dest_db.upsert_metadata(metadata_config, source_id, filter_tags_data)

            # Step 5: Save the two separate JSON files to S3
            self.s3_manager.save_json_file(bucket, summary_json_key, json.dumps(summary_data, indent=2))
            self.s3_manager.save_json_file(bucket, filter_json_key, json.dumps(filter_tags_data, indent=2))

            # Step 6: On success, update status and metrics in the main status table
            end_time_dt = datetime.now(timezone.utc)
            duration = (end_time_dt - start_time_dt).total_seconds()
            self.dest_db.update_step_result(
                status_table, source_id, 'json_valid', 'pass', duration, column_config,
                token_input=input_tokens, token_output=output_tokens,
                token_input_price=input_price, token_output_price=output_price,
                start_time=start_time_dt, end_time=end_time_dt
            )
            
            # Return the summary data for immediate HTML generation
            return summary_data

        except Exception as e:
            # On any failure, log the 'failed' status and all available metrics
            end_time_dt = datetime.now(timezone.utc)
            duration = (end_time_dt - start_time_dt).total_seconds()
            print(f"JSON generation and saving process failed for {source_id}. Error: {e}")
            self.dest_db.update_step_result(
                status_table, source_id, 'json_valid', 'failed', duration, column_config,
                token_input=input_tokens, token_output=output_tokens,
                token_input_price=input_price, token_output_price=output_price,
                start_time=start_time_dt, end_time=end_time_dt
            )
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
