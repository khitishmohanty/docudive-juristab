import os
import pandas as pd
import uuid
from sqlalchemy import create_engine, text, Row
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker
from typing import Optional

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

    def insert_initial_status(self, table_name: str, source_id: str) -> str:
        session = self.Session()
        try:
            new_id = str(uuid.uuid4())
            stmt = text(f"""
                INSERT INTO {table_name} (
                    id, source_id, 
                    status_text_extract, duration_file_miniviewer_text,
                    status_json_valid, duration_file_jurismap_json,
                    status_jurismap_html, duration_jurismap_html
                )
                VALUES (:id, :source_id, 'not started', 0, 'not started', 0, 'not started', 0)
            """)
            session.execute(stmt, {"id": new_id, "source_id": source_id})
            session.commit()
            print(f"Inserted initial status for source_id: {source_id}")
            return new_id
        except Exception as e:
            print(f"Error inserting initial status for source_id {source_id}: {e}")
            session.rollback()
            raise
        finally:
            session.close()

    def update_step_result(self, table_name: str, source_id: str, step: str, status: str, duration: float):
        session = self.Session()
        
        # FIX: Added 'jurismap_html' as a valid step
        step_to_columns = {
            'text_extract': ('status_text_extract', 'duration_file_miniviewer_text'),
            'json_valid': ('status_json_valid', 'duration_file_jurismap_json'),
            'jurismap_html': ('status_jurismap_html', 'duration_jurismap_html')
        }

        if step not in step_to_columns:
            raise ValueError(f"Invalid step name provided: {step}")
        
        status_col, duration_col = step_to_columns[step]

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
