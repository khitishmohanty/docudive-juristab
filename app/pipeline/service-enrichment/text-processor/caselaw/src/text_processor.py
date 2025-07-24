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
        """
        Initializes the TextProcessor.

        Args:
            config (dict): The application configuration dictionary.
        """
        self.config = config
        self.html_parser = HtmlParser()
        
        # Initialize the S3 manager
        self.s3_manager = S3Manager(region_name=config['aws']['default_region'])
        
        # This processor connects to both source and destination databases
        self.source_db = DatabaseConnector(db_config=config['database']['source'])
        self.dest_db = DatabaseConnector(db_config=config['database']['destination'])

    def process_cases(self):
        """
        Main method to run the text extraction pipeline.
        It iterates through all source tables defined in the config, reads case IDs,
        and processes each one based on its status.
        """
        tables_to_process = self.config['tables']['tables_to_read']
        dest_table_info = self.config['tables']['tables_to_write'][0]
        dest_table = dest_table_info['table']
        
        s3_bucket = self.config['aws']['s3']['bucket_name']
        filenames = self.config['enrichment_filenames']

        print(f"Found {len(tables_to_process)} source tables to process.")

        # Loop through each source table defined in the configuration
        for source_table_info in tables_to_process:
            source_table = source_table_info['table']
            s3_base_folder = source_table_info['s3_folder']  # Get the specific S3 folder for this table
            
            print(f"\n===== Processing table: {source_table} using S3 folder: {s3_base_folder} =====")

            try:
                # Fetch all case IDs from the current source table
                cases_df = self.source_db.read_sql(f"SELECT id FROM {source_table}")
                print(f"Found {len(cases_df)} total cases in source table '{source_table}'.")
            except Exception as e:
                print(f"ERROR: Could not read from source table {source_table}. Skipping. Error: {e}")
                continue  # Skip to the next table if there's an error

            # Iterate over each case from the source table
            for index, row in cases_df.iterrows():
                source_id = str(row['id'])
                print(f"\n--- Checking case for text extraction: {source_id} from table {source_table} ---")
                
                status_row = self.dest_db.get_status_by_source_id(dest_table, source_id)

                # If no status record exists, create one
                if not status_row:
                    print(f"No status record found for {source_id}. Creating new one.")
                    try:
                        self.dest_db.insert_initial_status(table_name=dest_table, source_id=source_id)
                        status_row = self.dest_db.get_status_by_source_id(dest_table, source_id)
                    except Exception as e:
                        print(f"Failed to insert initial status for {source_id}. Skipping. Error: {e}")
                        continue
                
                # If text has already been extracted successfully, skip it
                if status_row and status_row.status_text_processor == 'pass':
                    print(f"Text for case {source_id} has already been extracted. Skipping.")
                    continue

                # Construct the full S3 path for the source HTML and destination text file
                case_folder = os.path.join(s3_base_folder, source_id)
                html_file_key = os.path.join(case_folder, filenames['source_html'])
                txt_file_key = os.path.join(case_folder, filenames['extracted_text'])
                
                # Perform the text extraction and save the result
                self._extract_and_save_text(s3_bucket, html_file_key, txt_file_key, dest_table, source_id)
            
        print("\n--- Text extraction check completed for all cases in all tables. ---")

    def _extract_and_save_text(self, bucket, html_key, txt_key, status_table, source_id):
        """
        Handles HTML download from S3, text extraction, saving the text file back to S3,
        and updating the status database.

        Args:
            bucket (str): The S3 bucket name.
            html_key (str): The key for the source HTML file in S3.
            txt_key (str): The key for the destination text file in S3.
            status_table (str): The name of the database table for status tracking.
            source_id (str): The unique ID of the case being processed.
        """
        start_time_utc = datetime.now(timezone.utc)
        
        dest_table_info = self.config['tables']['tables_to_write'][0]
        step_columns_config = dest_table_info['step_columns']
        
        try:
            # Step 1: Get the HTML content from S3
            html_content = self.s3_manager.get_file_content(bucket, html_key)
            # Step 2: Extract text from the HTML
            text_content = self.html_parser.extract_text(html_content)
            # Step 3: Save the extracted text back to S3
            self.s3_manager.save_text_file(bucket, txt_key, text_content)
            
            end_time_utc = datetime.now(timezone.utc)
            duration = (end_time_utc - start_time_utc).total_seconds()
            
            # Step 4: Update the database to mark this step as 'pass'
            self.dest_db.update_step_result(
                status_table, source_id, 'text_extract', 'pass', duration, 
                start_time_utc, end_time_utc, step_columns_config
            )
        except Exception as e:
            end_time_utc = datetime.now(timezone.utc)
            duration = (end_time_utc - start_time_utc).total_seconds()
            print(f"Text extraction failed for {source_id}. Error: {e}")
            # Update the database to mark this step as 'failed'
            self.dest_db.update_step_result(
                status_table, source_id, 'text_extract', 'failed', duration,
                start_time_utc, end_time_utc, step_columns_config
            )
