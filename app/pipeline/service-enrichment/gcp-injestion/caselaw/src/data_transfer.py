import yaml
import os
import time
import datetime
import logging
from dotenv import load_dotenv, find_dotenv
from utils.aws_s3 import get_s3_client, download_file_to_memory
from utils.gcp_storage import get_gcp_client, upload_file_from_memory
from utils.database import connect_db, fetch_caselaw_registry, update_enrichment_status
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
        Loads environment variables. This version is simplified to work with
        standard environment variable injection, as is the case in Fargate.
        The multi-line JSON string must be provided as a single, escaped line.
        """
        # Load environment variables. This is a no-op in Fargate.
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
        # Check if running locally (e.g., via an environment variable)
        if os.getenv("RUNNING_LOCAL"):
            # Read credentials from a local file
            try:
                with open('path/to/juris-tab-1ceff74390dc.json', 'r') as f:
                    gcp_credentials_json_string = f.read()
            except FileNotFoundError:
                logging.error("Local GCP credentials file not found.")
                self.gcp_client = None
                return False
        else:
            # Code for Fargate (as you've configured it)
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

    def run(self):
        """
        Main method to orchestrate the entire data transfer process.
        """
        if not self._initialize_connections():
            logging.error("Failed to establish all required connections. Exiting.")
            return

        try:
            # 1. Fetch data from caselaw_registry
            registry_config = self.config['tables_registry']
            update_table_config = self.config['tables']['tables_to_write'][0]
            jurisdiction_codes = registry_config['jurisdiction_codes']
            sub_folders = registry_config['sub_folders']
            
            records = fetch_caselaw_registry(self.db_conn, registry_config, update_table_config)
            
            if not records:
                logging.info("No records to process. Exiting.")
                return

            # Create a mapping for jurisdiction_code to sub_folder
            jurisdiction_map = dict(zip(jurisdiction_codes, sub_folders))

            # 2. Iterate and transfer files
            aws_s3_bucket = self.config['aws']['s3']['bucket_name']
            aws_s3_folder = self.config['aws']['s3']['folder_name']
            gcp_storage_bucket = self.config['gcp']['storage']['bucket_name']
            gcp_storage_folder = self.config['gcp']['storage']['folder_name']
            source_file_name = self.config['enrichment_filenames']['source_file']
            
            for record in records:
                source_id = record['source_id']
                jurisdiction = record['jurisdiction_code']
                sub_folder = jurisdiction_map.get(jurisdiction, jurisdiction.lower())

                start_time = datetime.datetime.now()
                status = 'failed'
                duration = 0.0

                try:
                    s3_object_key = os.path.join(aws_s3_folder, sub_folder, source_id, source_file_name)
                    gcp_blob_name = os.path.join(gcp_storage_folder, sub_folder, source_id, source_file_name)

                    file_data = download_file_to_memory(self.s3_client, aws_s3_bucket, s3_object_key)
                    if file_data is None:
                        raise ValueError("Failed to download file from S3.")
                    
                    if not upload_file_from_memory(self.gcp_client, gcp_storage_bucket, gcp_blob_name, file_data):
                        raise ValueError("Failed to upload file to GCP Storage.")
                        
                    status = 'pass'
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
        finally:
            self._close_connections()
