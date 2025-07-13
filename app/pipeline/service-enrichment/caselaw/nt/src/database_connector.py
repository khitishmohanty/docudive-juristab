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
        """
        Initializes the connector with database configuration.
        
        Args:
            db_config: A dictionary containing database connection details.
        """
        self.db_config = db_config
        self.engine = self._create_db_engine()
        self.Session = sessionmaker(bind=self.engine)
        
    def _create_db_engine(self):
        """Creates a SQLAlchemy engine from the configuration."""
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
        """
        Reads data from the database using a SQL query into a pandas DataFrame.

        Args:
            query: The SQL query to execute.

        Returns:
            A pandas DataFrame containing the query's result.
        """
        print(f"Executing query...")
        try:
            return pd.read_sql_query(query, self.engine)
        except Exception as e:
            print(f"Error executing query: {e}")
            raise

    def get_status_by_source_id(self, table_name: str, source_id: str) -> Optional[Row]:
        """
        Retrieves the status record for a given source_id.

        Args:
            table_name (str): The name of the status table.
            source_id (str): The source record's UUID.

        Returns:
            A SQLAlchemy Row object with the status record, or None if not found.
        """
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
        """
        Inserts a new record into the status table with 'not started' status and 0 duration.
        """
        session = self.Session()
        try:
            new_id = str(uuid.uuid4())
            # NOTE: Updated to include new duration columns with an initial value of 0.
            stmt = text(f"""
                INSERT INTO {table_name} (id, source_id, status_json_valid, duration_file_jurismap_json, status_text_extract, duration_file_miniviewer_text)
                VALUES (:id, :source_id, 'not started', 0, 'not started', 0)
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
        """
        Updates the status and duration for a specific processing step.

        Args:
            table_name (str): The name of the status table.
            source_id (str): The source record's UUID.
            step (str): The processing step ('text_extract' or 'json_valid').
            status (str): The new status ('pass' or 'failed').
            duration (float): The time taken for the step in seconds.
        """
        session = self.Session()
        
        if step == 'text_extract':
            status_col = 'status_text_extract'
            duration_col = 'duration_file_miniviewer_text'
        elif step == 'json_valid':
            status_col = 'status_json_valid'
            duration_col = 'duration_file_jurismap_json'
        else:
            raise ValueError("Invalid step name provided.")

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
