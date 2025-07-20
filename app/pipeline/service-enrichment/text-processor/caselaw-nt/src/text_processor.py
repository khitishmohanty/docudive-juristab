import os
import time
from datetime import datetime, timezone
from utils.database_connector import DatabaseConnector
from utils.html_parser import HtmlParser
from utils.s3_manager import S3Manager

class TextProcessor:
    """
    Handles the text extraction part of the pipeline.
    """
    def __init__(self, config: dict):
        self.config = config
        self.html_parser = HtmlParser()
        
        self.s3_manager = S3Manager(region_name=config['aws']['default_region'])
        
        # This processor only needs to connect to both databases
        self.source_db = DatabaseConnector(db_config=config['database']['source'])
        self.dest_db = DatabaseConnector(db_config=config['database']['destination'])

    def process_cases(self):
        """
        Main method to run the text extraction pipeline.
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
            print(f"\n--- Checking case for text extraction: {source_id} ---")
            
            status_row = self.dest_db.get_status_by_source_id(dest_table, source_id)

            if not status_row:
                print(f"No status record found for {source_id}. Creating new one.")
                try:
                    self.dest_db.insert_initial_status(table_name=dest_table, source_id=source_id)
                    status_row = self.dest_db.get_status_by_source_id(dest_table, source_id)
                except Exception as e:
                    print(f"Failed to insert initial status for {source_id}. Skipping. Error: {e}")
                    continue
            
            if status_row.status_text_processor == 'pass':
                print(f"Text for case {source_id} has already been extracted. Skipping.")
                continue

            case_folder = os.path.join(s3_base_folder, source_id)
            html_file_key = os.path.join(case_folder, filenames['source_html'])
            txt_file_key = os.path.join(case_folder, filenames['extracted_text'])
            
            self._extract_and_save_text(s3_bucket, html_file_key, txt_file_key, dest_table, source_id)
            
        print("\n--- Text extraction check completed for all cases. ---")

    def _extract_and_save_text(self, bucket, html_key, txt_key, status_table, source_id):
        """Handles HTML download, text extraction, and saving to S3, including timing and DB logging."""
        start_time_utc = datetime.now(timezone.utc)
        
        dest_table_info = self.config['tables']['tables_to_write'][0]
        step_columns_config = dest_table_info['step_columns']
        
        try:
            html_content = self.s3_manager.get_file_content(bucket, html_key)
            text_content = self.html_parser.extract_text(html_content)
            self.s3_manager.save_text_file(bucket, txt_key, text_content)
            
            end_time_utc = datetime.now(timezone.utc)
            duration = (end_time_utc - start_time_utc).total_seconds()
            
            self.dest_db.update_step_result(
                status_table, source_id, 'text_extract', 'pass', duration, 
                start_time_utc, end_time_utc, step_columns_config
            )
        except Exception as e:
            end_time_utc = datetime.now(timezone.utc)
            duration = (end_time_utc - start_time_utc).total_seconds()
            print(f"Text extraction failed for {source_id}. Error: {e}")
            self.dest_db.update_step_result(
                status_table, source_id, 'text_extract', 'failed', duration,
                start_time_utc, end_time_utc, step_columns_config
            )