import os
import pandas as pd
import uuid
from sqlalchemy import create_engine, text, Row
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker
from typing import Optional, Dict

class DatabaseConnector:
    """Handles all database interactions."""
    
    def __init__(self, db_config: dict):
        self.db_config = db_config
        self.engine = self._create_db_engine()
        self.Session = sessionmaker(bind=self.engine)
        
    def _create_db_engine(self):
        try:
            connection_url = URL.create(
                drivername=f"{self.db_config['dialect']}+{self.db_config['driver']}",
                username=os.getenv("DB_USER"),
                password=os.getenv("DB_PASSWORD"),
                host=self.db_config['host'],
                port=self.db_config['port'],
                database=self.db_config['name']
            )
            print(f"Creating database engine for: {self.db_config['name']}")
            return create_engine(connection_url)
        except Exception as e:
            print(f"Error creating database engine: {e}")
            raise
    
    def read_sql(self, query: str) -> pd.DataFrame:
        print(f"Executing query...")
        try:
            return pd.read_sql_query(query, self.engine)
        except Exception as e:
            print(f"Error executing query: {e}")
            raise

    def get_status_by_source_id(self, table_name: str, source_id: str) -> Optional[Row]:
        session = self.Session()
        try:
            stmt = text(f"SELECT * FROM {table_name} WHERE source_id = :source_id LIMIT 1")
            result = session.execute(stmt, {"source_id": source_id}).fetchone()
            return result
        except Exception as e:
            print(f"Error getting status for source_id {source_id}: {e}")
            raise
        finally:
            session.close()

    def get_records_for_ai_processing(self, table_name: str, column_config: Dict[str, str]) -> pd.DataFrame:
        """
        Queries the status table for records that are ready for AI processing.
        A record is ready if text extraction has passed, but either the JSON
        or HTML steps have not passed.
        """
        print(f"Querying for records ready for AI processing in table: {table_name}")
        try:
            # Use column names from config
            text_status_col = column_config['text_extract_status']
            json_status_col = column_config['json_valid_status']
            html_status_col = column_config['jurismap_html_status']
            
            query = text(f"""
                SELECT source_id, {json_status_col}, {html_status_col}
                FROM {table_name}
                WHERE {text_status_col} = 'pass' 
                AND ({json_status_col} != 'pass' OR {html_status_col} != 'pass')
            """)
            return pd.read_sql_query(query, self.engine)
        except Exception as e:
            print(f"Error querying for AI-ready records: {e}")
            raise

    def insert_initial_status(self, table_name: str, source_id: str, column_config: Dict[str, str]):
        session = self.Session()
        try:
            new_id = str(uuid.uuid4())
            # Dynamically build query with column names from config
            cols = column_config
            stmt = text(f"""
                INSERT INTO {table_name} (
                    id, source_id, 
                    {cols['text_extract_status']}, {cols['text_extract_duration']},
                    {cols['json_valid_status']}, {cols['json_valid_duration']},
                    {cols['jurismap_html_status']}, {cols['jurismap_html_duration']}
                )
                VALUES (:id, :source_id, 'not started', 0, 'not started', 0, 'not started', 0)
            """)
            session.execute(stmt, {"id": new_id, "source_id": source_id})
            session.commit()
            print(f"Inserted initial status for source_id: {source_id}")
        except Exception as e:
            print(f"Error inserting initial status for source_id {source_id}: {e}")
            session.rollback()
            raise
        finally:
            session.close()

    def update_step_result(self, table_name: str, source_id: str, step: str, status: str, duration: float, column_config: Dict[str, str]):
        session = self.Session()
        
        # Map step names to the keys in the column_config dictionary
        step_to_config_keys = {
            'text_extract': ('text_extract_status', 'text_extract_duration'),
            'json_valid': ('json_valid_status', 'json_valid_duration'),
            'jurismap_html': ('jurismap_html_status', 'jurismap_html_duration')
        }

        if step not in step_to_config_keys:
            raise ValueError(f"Invalid step name provided: {step}")
        
        status_key, duration_key = step_to_config_keys[step]
        status_col = column_config[status_key]
        duration_col = column_config[duration_key]

        if status not in ['pass', 'failed']:
            raise ValueError("Invalid status value. Must be 'pass' or 'failed'.")

        try:
            stmt = text(f"""
                UPDATE {table_name} 
                SET {status_col} = :status, {duration_col} = :duration 
                WHERE source_id = :source_id
            """)
            session.execute(stmt, {"status": status, "duration": duration, "source_id": source_id})
            session.commit()
            print(f"Updated {step} to '{status}' with duration {duration:.2f}s for source_id: {source_id}")
        except Exception as e:
            print(f"Error updating step result for source_id {source_id}: {e}")
            session.rollback()
            raise
        finally:
            session.close()
