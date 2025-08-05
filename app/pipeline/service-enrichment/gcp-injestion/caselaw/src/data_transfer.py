import yaml
import os
import time
import datetime
import logging
import json
import uuid
from dotenv import load_dotenv, find_dotenv
from utils.aws_s3 import get_s3_client, download_file_to_memory
from utils.gcp_storage import get_gcp_client, upload_file_from_memory
from utils.database import connect_db, fetch_caselaws_for_gcp_ingestion, update_enrichment_status
from utils.secrets_manager import get_secret 

# Configure logging
logging.basicConfig(level=logging.INFO)

class DataTransfer:
    def __init__(self, config_path):
        """
        Initializes the DataTransfer class by loading configuration files and credentials.
        """
        self.config = self._load_config(config_path)
        self.env = self._load_env()
        
        if not self.config or not self.env:
            raise ValueError("Failed to load configuration or environment variables.")
        
        self.db_conn = None
        self.s3_client = None
        self.gcp_client = None

    def _load_config(self, config_path):
        """
        Loads and parses the YAML configuration file.
        """
        try:
            with open(config_path, 'r') as file:
                return yaml.safe_load(file)
        except FileNotFoundError:
            logging.error(f"Configuration file not found at {config_path}")
            return None
        except yaml.YAMLError as e:
            logging.error(f"Error parsing YAML file: {e}")
            return None

    def _load_env(self):
        """
        Loads environment variables.
        """
        load_dotenv(find_dotenv())

        env_vars = {
            "DB_USER": os.getenv("DB_USER"),
            "DB_PASSWORD": os.getenv("DB_PASSWORD"),
            "AWS_ACCESS_KEY_ID": os.getenv("AWS_ACCESS_KEY_ID"),
            "AWS_SECRET_ACCESS_KEY": os.getenv("AWS_SECRET_ACCESS_KEY"),
            "GOOGLE_APPLICATION_CREDENTIALS_JSON": os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
        }
        
        if not all(env_vars.values()):
            logging.warning("Some environment variables are missing.")
        return env_vars

    def _initialize_connections(self):
        """
        Initializes connections to the database, AWS S3, and GCP Storage.
        """
        db_config = self.config['database']
        self.db_conn = connect_db(
            db_config,
            self.env['DB_USER'],
            self.env['DB_PASSWORD']
        )
        
        aws_config = self.config['aws']
        self.s3_client = get_s3_client(
            self.env['AWS_ACCESS_KEY_ID'],
            self.env['AWS_SECRET_ACCESS_KEY'],
            aws_config['default_region']
        )
        
        gcp_credentials_json_string = None
        if os.getenv("RUNNING_LOCAL"):
            try:
                with open('path/to/your/local/credentials.json', 'r') as f:
                    gcp_credentials_json_string = f.read()
            except FileNotFoundError:
                logging.error("Local GCP credentials file not found.")
                self.gcp_client = None
                return False
        else:
            aws_region = self.config['aws']['default_region']
            try:
                gcp_credentials_json_string = get_secret(
                    "juristab-gcp-credentials",
                    aws_region
                )
            except Exception as e:
                logging.error(f"Failed to retrieve GCP credentials from Secrets Manager: {e}")
                self.gcp_client = None
                return False

        if gcp_credentials_json_string:
            self.gcp_client = get_gcp_client(gcp_credentials_json_string)
        else:
            self.gcp_client = None

        return all([self.db_conn, self.s3_client, self.gcp_client])

    def _close_connections(self):
        """
        Closes all open connections.
        """
        if self.db_conn and self.db_conn.is_connected():
            self.db_conn.close()
            logging.info("Database connection closed.")

    def _create_and_upload_jsonl_files(self, records_data):
        """
        Creates JSONL files from a list of records and uploads them to GCP Storage.
        Each file contains a maximum number of records defined in the config and has a unique name.
        """
        if not records_data:
            logging.info("No successful records to process for JSONL creation.")
            return

        logging.info(f"Starting JSONL file creation for {len(records_data)} records.")
        
        jsonl_config = self.config.get('json_line', {}) #
        if not jsonl_config:
            logging.error("JSONL configuration ('json_line') not found in config. Exiting JSONL creation.") #
            return

        bucket_name = jsonl_config.get('storage', {}).get('bucket_name') #
        folder_name = jsonl_config.get('storage', {}).get('folder_name', '') #

        if not bucket_name:
            logging.error("Bucket name for JSONL storage not found in config.") #
            return

        # Read chunk_size from config, with a default of 1000 for safety
        chunk_size = jsonl_config.get('chunk_size', 1000) #

        for i in range(0, len(records_data), chunk_size): #
            chunk = records_data[i:i + chunk_size] #
            
            # Create JSONL content: each JSON object is a line, joined by a newline
            # This creates the correct JSON Lines format.
            jsonl_content = '\n'.join([json.dumps(record) for record in chunk]) #
            jsonl_data_bytes = jsonl_content.encode('utf-8') #

            # Generate a unique identifier and get the current date for the filename
            file_uuid = uuid.uuid4() #
            current_date_str = datetime.datetime.now().strftime('%Y%m%d') #

            # Define the destination blob name for the JSONL file with the new format
            destination_file_name = f"legal-store-repo-{current_date_str}-{file_uuid}.jsonl" #
            gcp_blob_name = os.path.join(folder_name, destination_file_name) #

            logging.info(f"Uploading file to gs://{bucket_name}/{gcp_blob_name}") #

            # Upload the JSONL data to GCP
            if not upload_file_from_memory(self.gcp_client, bucket_name, gcp_blob_name, jsonl_data_bytes): #
                logging.error(f"Failed to upload JSONL file {destination_file_name} to GCP Storage.") #
            else:
                logging.info(f"Successfully uploaded {destination_file_name}.") #


    def run(self):
        """
        Main method to orchestrate the entire data transfer process.
        """
        if not self._initialize_connections():
            logging.error("Failed to establish all required connections. Exiting.")
            return

        successful_records_data = []

        try:
            # 1. Fetch data from the database
            registry_config = self.config['tables_registry']
            update_table_config = self.config['tables']['tables_to_write'][0]
            
            records = fetch_caselaws_for_gcp_ingestion(self.db_conn, update_table_config)
            
            if not records:
                logging.info("No new records to process. Exiting.")
                return

            jurisdiction_codes = registry_config['jurisdiction_codes']
            sub_folders = registry_config['sub_folders']
            jurisdiction_map = dict(zip(jurisdiction_codes, sub_folders))

            # 2. Iterate and transfer individual files as JSON
            aws_s3_bucket = self.config['aws']['s3']['bucket_name']
            aws_s3_folder = self.config['aws']['s3']['folder_name']
            gcp_storage_bucket = self.config['gcp']['storage']['bucket_name']
            gcp_storage_folder = self.config['gcp']['storage']['folder_name']
            source_content_file = self.config['enrichment_filenames']['source_file']
            
            for record in records:
                source_id = record['source_id']
                jurisdiction = record['jurisdiction_code']
                sub_folder = jurisdiction_map.get(jurisdiction, jurisdiction.lower())

                start_time = datetime.datetime.now()
                status = 'failed'
                duration = 0.0

                try:
                    # Fetch the caselaw content from S3
                    s3_object_key = os.path.join(aws_s3_folder, sub_folder, source_id, source_content_file)
                    file_content_bytes = download_file_to_memory(self.s3_client, aws_s3_bucket, s3_object_key)
                    if file_content_bytes is None:
                        raise ValueError(f"Failed to download content file from S3: {s3_object_key}")
                    
                    file_content_str = file_content_bytes.decode('utf-8')

                    # Create the JSON object with a flat structure
                    json_output = {}
                    for key, value in record.items():
                        if value is not None:
                            if isinstance(value, (datetime.datetime, datetime.date)):
                                json_output[key] = value.isoformat()
                            else:
                                json_output[key] = value
                    
                    json_output["document_type"] = "caselaw"
                    json_output["content"] = file_content_str
                    
                    # For the individual file, we still use indented JSON for readability
                    json_data_bytes_indented = json.dumps(json_output, indent=4).encode('utf-8')

                    # Define the destination blob name for the individual JSON file
                    destination_file_name = f"{source_id}.json"
                    gcp_blob_name = os.path.join(gcp_storage_folder, sub_folder, source_id, destination_file_name)

                    # Upload the individual JSON data to GCP
                    if not upload_file_from_memory(self.gcp_client, gcp_storage_bucket, gcp_blob_name, json_data_bytes_indented):
                        raise ValueError("Failed to upload JSON file to GCP Storage.")
                        
                    status = 'pass'
                    # For the JSONL file, we append the non-indented JSON object
                    successful_records_data.append(json_output) 
                    logging.info(f"Successfully processed and uploaded JSON for source_id: {source_id}")

                except Exception as e:
                    logging.error(f"Error processing record source_id {source_id}: {e}")
                finally:
                    end_time = datetime.datetime.now()
                    duration = (end_time - start_time).total_seconds()
                    
                    update_enrichment_status(
                        self.db_conn,
                        update_table_config,
                        source_id,
                        status,
                        duration,
                        start_time,
                        end_time
                    )
            
            # 3. After processing all records, create and upload the batched JSONL files
            self._create_and_upload_jsonl_files(successful_records_data)

        finally:
            self._close_connections()