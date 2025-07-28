import yaml
import boto3
from sqlalchemy import create_engine, text
import os

# Environment variables for credentials
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")

def load_config(config_path='config/config.yaml'):
    """Loads the YAML configuration file."""
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

class DatabaseHandler:
    """Handles all database interactions."""
    def __init__(self, config):
        db_config = config['database']['destination']
        source_db_config = config['database']['source']
        
        # Connection string for the destination/status database
        conn_str = (
            f"{db_config['dialect']}+{db_config['driver']}://"
            f"{DB_USER}:{DB_PASSWORD}@"
            f"{db_config['host']}:{db_config['port']}/{db_config['name']}"
        )
        self.engine = create_engine(conn_str)

        # Connection string for the source database
        source_conn_str = (
            f"{source_db_config['dialect']}+{source_db_config['driver']}://"
            f"{DB_USER}:{DB_PASSWORD}@"
            f"{source_db_config['host']}:{source_db_config['port']}/{source_db_config['name']}"
        )
        self.source_engine = create_engine(source_conn_str)
        
        # Enrichment status table config
        status_config = config['tables']['tables_to_write'][0]
        self.status_table = status_config['table']
        self.status_column = status_config['columns']['processing_status']
        self.duration_column = status_config['columns']['processing_duration']
        self.start_time_column = status_config['columns']['start_time']
        self.end_time_column = status_config['columns']['end_time']

        # Metadata table config
        metadata_config = config['tables']['tables_to_write'][1]
        self.metadata_table = metadata_config['table']
        self.char_count_column = metadata_config['columns']['char_count']
        self.word_count_column = metadata_config['columns']['word_count']

        # Registry table config
        registry_config = config['tables_registry']
        self.registry_table = registry_config['table']
        self.registry_year_column = registry_config['column']
        # --- NEW: Jurisdiction column is assumed to be 'jurisdiction_code' as per your request ---
        self.registry_jurisdiction_column = 'jurisdiction_code'


    def get_cases_to_process(self, year, jurisdiction_code):
        """
        Fetches a list of source_ids for a specific year and jurisdiction that have passed 
        text processing but have not yet been successfully embedded.
        """
        query = text(f"""
            SELECT T1.source_id 
            FROM {self.status_table} AS T1
            JOIN {self.registry_table} AS T2 ON T1.source_id = T2.source_id
            WHERE T2.{self.registry_year_column} = :year
            AND T2.{self.registry_jurisdiction_column} = :jurisdiction_code
            AND T1.status_text_processor = 'pass'
            AND (T1.{self.status_column} != 'pass' OR T1.{self.status_column} IS NULL)
        """)
        with self.engine.connect() as connection:
            result = connection.execute(query, {"year": year, "jurisdiction_code": jurisdiction_code})
            return [row[0] for row in result]

    def find_s3_folder_for_ids(self, source_ids, tables_to_read_config):
        """
        Finds the correct s3_folder for a given list of source_ids by checking
        against all configured source tables.
        Returns a dictionary mapping source_id to its s3_folder.
        """
        id_to_folder_map = {}
        if not source_ids:
            return id_to_folder_map

        with self.source_engine.connect() as connection:
            for table_config in tables_to_read_config:
                table_name = table_config['table']
                s3_folder = table_config['s3_folder']
                
                # Create a query to find which of our IDs exist in this table
                # Ensure proper quoting for string IDs in the IN clause
                id_list_str = ','.join([f"'{_id}'" for _id in source_ids])
                if not id_list_str: continue

                query = text(f"SELECT id FROM {table_name} WHERE id IN ({id_list_str})")
                
                result = connection.execute(query)
                found_ids = [row[0] for row in result]
                
                for _id in found_ids:
                    id_to_folder_map[_id] = s3_folder
        
        return id_to_folder_map

    def update_embedding_status(self, source_id, status, duration=None):
        """Updates the embedding status for a given source_id."""
        update_query = f"""
            UPDATE {self.status_table}
            SET 
                {self.status_column} = :status,
                {self.duration_column} = :duration,
                {self.end_time_column} = NOW()
            WHERE source_id = :source_id
        """
        
        start_time_query = f"""
            UPDATE {self.status_table}
            SET {self.start_time_column} = NOW()
            WHERE source_id = :source_id AND {self.start_time_column} IS NULL
        """

        with self.engine.connect() as connection:
            # Set start time if it's the first attempt
            connection.execute(text(start_time_query), {"source_id": source_id})
            # Update final status and duration
            connection.execute(text(update_query), {
                "status": status,
                "duration": duration,
                "source_id": source_id
            })
            connection.commit()

    def update_metadata_counts(self, source_id, char_count, word_count):
        """Inserts or updates the character and word counts in the metadata table."""
        # This query will create a row if one doesn't exist for the source_id,
        # or update the existing one. Assumes `source_id` is a PRIMARY or UNIQUE key.
        query = text(f"""
            INSERT INTO {self.metadata_table} (source_id, {self.char_count_column}, {self.word_count_column})
            VALUES (:source_id, :char_count, :word_count)
            ON DUPLICATE KEY UPDATE
                {self.char_count_column} = :char_count,
                {self.word_count_column} = :word_count
        """)
        
        with self.engine.connect() as connection:
            connection.execute(query, {
                "source_id": source_id,
                "char_count": char_count,
                "word_count": word_count
            })
            connection.commit()


class S3Handler:
    """Handles all S3 interactions."""
    def __init__(self, config):
        aws_config = config['aws']
        self.s3_client = boto3.client(
            's3',
            region_name=aws_config['default_region'],
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY
        )
        self.bucket_name = aws_config['s3']['bucket_name']

    def get_caselaw_text(self, s3_key):
        """Downloads and returns the content of a text file from S3."""
        try:
            obj = self.s3_client.get_object(Bucket=self.bucket_name, Key=s3_key)
            return obj['Body'].read().decode('utf-8')
        except Exception as e:
            print(f"Error reading from S3 key {s3_key}: {e}")
            raise

    def upload_embedding(self, s3_key, data):
        """Uploads a file-like object to a specific S3 key."""
        try:
            self.s3_client.put_object(Bucket=self.bucket_name, Key=s3_key, Body=data)
        except Exception as e:
            print(f"Error uploading to S3 key {s3_key}: {e}")
            raise