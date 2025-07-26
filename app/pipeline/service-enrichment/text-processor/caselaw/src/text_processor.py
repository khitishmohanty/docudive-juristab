import os
import time
from datetime import datetime, timezone
from utils.database_connector import DatabaseConnector
from utils.html_parser import HtmlParser
from utils.s3_manager import S3Manager

class TextProcessor:
    """
    Handles the text extraction part of the pipeline by efficiently identifying
    and processing cases that have not yet been successfully completed.
    """
    def __init__(self, config: dict):
        """
        Initializes the TextProcessor.

        Args:
            config (dict): The application configuration dictionary.
        """
        self.config = config
        self.html_parser = HtmlParser()
        
        # Initialize the S3 manager using the region from the config
        self.s3_manager = S3Manager(region_name=config['aws']['default_region'])
        
        # This processor connects to both source and destination databases
        self.source_db = DatabaseConnector(db_config=config['database']['source'])
        self.dest_db = DatabaseConnector(db_config=config['database']['destination'])

    def process_cases(self):
        """
        Main method to run the text extraction pipeline.
        It identifies cases needing processing using an efficient JOIN query
        and processes each one.
        """
        tables_to_process = self.config['tables']['tables_to_read']
        dest_table_info = self.config['tables']['tables_to_write'][0]
        
        # --- FIX: Get destination DB name and table name from config ---
        dest_db_name = dest_table_info['database']
        dest_table = dest_table_info['table']
        status_column = dest_table_info['step_columns']['text_extract']['status']
        
        s3_bucket = self.config['aws']['s3']['bucket_name']
        filenames = self.config['enrichment_filenames']

        print(f"Found {len(tables_to_process)} source tables to process.")

        # Loop through each source table defined in the configuration
        for source_table_info in tables_to_process:
            source_table = source_table_info['table']
            s3_base_folder = source_table_info['s3_folder']
            
            print(f"\n===== Processing table: {source_table} using S3 folder: {s3_base_folder} =====")

            try:
                # --- FIX: Use a fully qualified table name for the cross-database JOIN ---
                # This explicitly tells the query to look for the destination table
                # in the correct database (e.g., `legal_store.caselaw_enrichment_status`).
                query = f"""
                    SELECT
                        source.id
                    FROM
                        {source_table} AS source
                    LEFT JOIN
                        {dest_db_name}.{dest_table} AS dest ON source.id = dest.source_id
                    WHERE
                        dest.source_id IS NULL OR dest.{status_column} != 'pass'
                """
                cases_to_process_df = self.source_db.read_sql(query)
                print(f"Found {len(cases_to_process_df)} cases requiring text extraction in '{source_table}'.")

            except Exception as e:
                print(f"ERROR: Could not read from source table {source_table}. Skipping. Error: {e}")
                continue # Skip to the next table if the query fails

            # Iterate ONLY over the cases that require processing
            for index, row in cases_to_process_df.iterrows():
                source_id = str(row['id'])
                print(f"\n--- Processing case for text extraction: {source_id} ---")
                
                # We still need to check if a status row exists to decide whether to INSERT a new one.
                status_row = self.dest_db.get_status_by_source_id(dest_table, source_id)
                if not status_row:
                    print(f"No status record found for {source_id}. Creating new one.")
                    try:
                        self.dest_db.insert_initial_status(table_name=dest_table, source_id=source_id)
                    except Exception as e:
                        print(f"Failed to insert initial status for {source_id}. Skipping. Error: {e}")
                        continue # Skip this case if status insert fails

                # Construct the S3 paths for the HTML and the output text file
                case_folder = os.path.join(s3_base_folder, source_id)
                html_file_key = os.path.join(case_folder, filenames['source_html'])
                txt_file_key = os.path.join(case_folder, filenames['extracted_text'])
                
                # Perform the text extraction, save the result to S3, and update the database
                self._extract_and_save_text(s3_bucket, html_file_key, txt_file_key, dest_table, source_id)
            
        print("\n--- Text extraction check completed for all cases in all tables. ---")

    def _extract_and_save_text(self, bucket: str, html_key: str, txt_key: str, status_table: str, source_id: str):
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
            print(f"Successfully extracted text for {source_id}.")
            self.dest_db.update_step_result(
                status_table, source_id, 'text_extract', 'pass', duration, 
                start_time_utc, end_time_utc, step_columns_config
            )
        except Exception as e:
            end_time_utc = datetime.now(timezone.utc)
            duration = (end_time_utc - start_time_utc).total_seconds()
            print(f"Text extraction FAILED for {source_id}. Error: {e}")
            # Update the database to mark this step as 'failed' to prevent retrying on next run
            self.dest_db.update_step_result(
                status_table, source_id, 'text_extract', 'failed', duration,
                start_time_utc, end_time_utc, step_columns_config
            )
