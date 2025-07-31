import os
import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def get_db_connection(config_path='config/config.yaml'):
    """
    Creates a database connection using credentials from config and .env files.
    """
    with open(config_path, 'r') as file:
        config = yaml.safe_load(file)

    db_config = config['database']['destination']
    
    # Get credentials from environment variables
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")

    if not db_user or not db_password:
        raise ValueError("DB_USER and DB_PASSWORD must be set in the .env file")

    # Construct the database URL
    db_url = (
        f"{db_config['dialect']}+{db_config['driver']}://"
        f"{db_user}:{db_password}@"
        f"{db_config['host']}:{db_config['port']}/{db_config['name']}"
    )
    
    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)
    return Session()

def get_table_name(config_path, table_key):
    """
    Gets a table name from the config file.
    """
    with open(config_path, 'r') as file:
        config = yaml.safe_load(file)
    
    for table_info in config['tables']['tables_to_write']:
        if table_info['table'] == table_key:
            return table_info['table']
    
    for table_info in config['tables']['tables_to_read']:
        if table_info['table'] == table_key:
            return table_info['table']

    if config['tables_registry']['table'] == table_key:
        return table_key

    raise ValueError(f"Table key '{table_key}' not found in config file.")

def get_column_names(config_path, table_key):
    """
    Gets column names for a specific table from the config file.
    """
    with open(config_path, 'r') as file:
        config = yaml.safe_load(file)
    
    for table_info in config['tables']['tables_to_write']:
        if table_info['table'] == table_key:
            return table_info.get('columns', {})
            
    return {}
