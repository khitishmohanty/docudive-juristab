import os
import pandas as pd
import uuid
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker

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

    def insert_initial_status(self, table_name: str, source_id: str) -> str:
        """
        Inserts a new record into the status table with a 'not started' status.

        Args:
            table_name (str): The name of the status table.
            source_id (str): The UUID of the source record.

        Returns:
            str: The new UUID of the created status record.
        """
        session = self.Session()
        try:
            new_id = str(uuid.uuid4())
            stmt = text(f"""
                INSERT INTO {table_name} (id, source_id, status_json_valid, status_text_extract)
                VALUES (:id, :source_id, 'not started', 'not started')
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

    def update_status(self, table_name: str, source_id: str, column: str, status: str):
        """
        Updates a status column for a given source_id.

        Args:
            table_name (str): The name of the status table.
            source_id (str): The source record's UUID.
            column (str): The column to update (e.g., 'status_text_extract').
            status (str): The new status ('pass' or 'failed').
        """
        session = self.Session()
        if column not in ['status_json_valid', 'status_text_extract']:
            raise ValueError("Invalid column name for status update.")
        if status not in ['pass', 'failed']:
             raise ValueError("Invalid status value. Must be 'pass' or 'failed'.")

        try:
            stmt = text(f"""
                UPDATE {table_name} SET {column} = :status WHERE source_id = :source_id
            """)
            session.execute(stmt, {"status": status, "source_id": source_id})
            session.commit()
            print(f"Updated {column} to '{status}' for source_id: {source_id}")
        except Exception as e:
            print(f"Error updating status for source_id {source_id}: {e}")
            session.rollback()
            raise
        finally:
            session.close()
