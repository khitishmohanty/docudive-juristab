import os
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.engine import URL


class DatabaseConnector:
    """Handles all database interactions."""
    
    def __init__(self, config: dict):
        """
        Initializes the connector with database configuration.
        
        Args:
            config: A dictionary containing database connection details.
        """
        self.config = config
        self.engine = self._create_db_engine()
        
    def _create_db_engine(self):
        """Creates a SQLAlchemy engine from the configuration."""
        try:
            connection_url = URL.create(
                drivername=f"{self.config['dialect']}+{self.config['driver']}",
                username=os.getenv("DB_USER"),  # Securely get user from .env
                password=os.getenv("DB_PASSWORD"), # Securely get password from .env
                host=self.config['host'],
                port=self.config['port'],
                database=self.config['name']
            )
            return create_engine(connection_url)
        except Exception as e:
            print(f"Error creating database engine: {e}")
            raise
    
    def read_table(self, table_name: str) -> pd.DataFrame:
        """
        Reads a single table from the database into a pandas DataFrame.

        Args:
            table_name: The name of the table to read.

        Returns:
            A pandas DataFrame containing the table's data.
        """
        print(f"Reading table: {table_name}...")
        try:
            return pd.read_sql_table(table_name, self.engine)
        except Exception as e:
            print(f"Error reading table {table_name}: {e}")
            raise
        
    