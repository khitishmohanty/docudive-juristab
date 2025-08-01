import mysql.connector
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)

def connect_db(db_config, db_user, db_password):
    """
    Establishes a connection to the MySQL database.
    
    Args:
        db_config (dict): Database configuration from the YAML file.
        db_user (str): Database username.
        db_password (str): Database password.
        
    Returns:
        mysql.connector.connection.MySQLConnection: The database connection object, or None on failure.
    """
    try:
        conn = mysql.connector.connect(
            host=db_config['host'],
            port=db_config['port'],
            user=db_user,
            password=db_password,
            database=db_config['name']
        )
        if conn.is_connected():
            logging.info("Successfully connected to the database.")
            return conn
        else:
            logging.error("Failed to connect to the database.")
            return None
    except mysql.connector.Error as e:
        logging.error(f"Database connection error: {e}")
        return None

def fetch_caselaw_registry(conn, table_registry_config, table_write_config):
    """
    Fetches records from the caselaw_registry table based on the configuration,
    only for records where 'status_gcpingestion' is not 'pass'.
    
    Args:
        conn: The database connection object.
        table_registry_config (dict): The registry configuration from the YAML file.
        table_write_config (dict): The write configuration from the YAML file.
        
    Returns:
        list: A list of dictionaries, where each dictionary is a record.
    """
    if not conn:
        return []
    
    cursor = conn.cursor(dictionary=True)
    registry_table_name = table_registry_config['table']
    enrichment_table_name = table_write_config['table']
    jurisdiction_codes = table_registry_config['jurisdiction_codes']
    processing_years = table_registry_config.get('processing_years', [])
    status_column = table_write_config['columns']['processing_status']

    # Base query
    query = f"""
    SELECT cr.id, cr.source_id, cr.jurisdiction_code
    FROM `{registry_table_name}` cr
    JOIN `{enrichment_table_name}` es ON cr.source_id = es.source_id
    WHERE es.`{status_column}` != 'pass'
    """
    
    # Values to be passed to the query
    query_values = []
    
    # Add the year filter if the list is not empty
    if processing_years:
        year_placeholders = ', '.join(['%s'] * len(processing_years))
        query += f" AND cr.year IN ({year_placeholders})"
        query_values.extend(processing_years)
    
    # Add the jurisdiction filter
    jurisdiction_placeholders = ', '.join(['%s'] * len(jurisdiction_codes))
    query += f" AND cr.jurisdiction_code IN ({jurisdiction_placeholders})"
    query_values.extend(jurisdiction_codes)

    try:
        cursor.execute(query, tuple(query_values))
        results = cursor.fetchall()
        logging.info(f"Fetched {len(results)} records from {registry_table_name} for processing.")
        return results
    except mysql.connector.Error as e:
        logging.error(f"Failed to fetch data from database: {e}")
        return []
    finally:
        cursor.close()


def update_enrichment_status(conn, update_config, source_id, status, duration, start_time, end_time):
    """
    Updates the caselaw_enrichment_status table.
    
    Args:
        conn: The database connection object.
        update_config (dict): The configuration for the table to write to.
        source_id (str): The source_id of the record to update.
        status (str): The processing status ('success' or 'failed').
        duration (float): The duration of the process in seconds.
        start_time (datetime): The start timestamp.
        end_time (datetime): The end timestamp.
        
    Returns:
        bool: True on success, False on failure.
    """
    if not conn:
        return False
        
    cursor = conn.cursor()
    
    table_name = update_config['table']
    columns = update_config['columns']
    
    try:
        # Construct the UPDATE query dynamically
        query = f"""
        UPDATE `{table_name}`
        SET
            `{columns['processing_status']}` = %s,
            `{columns['processing_duration']}` = %s,
            `{columns['start_time']}` = %s,
            `{columns['end_time']}` = %s
        WHERE source_id = %s
        """
        
        cursor.execute(query, (status, duration, start_time, end_time, source_id))
        conn.commit()
        logging.info(f"Successfully updated record with source_id {source_id} in {table_name}.")
        return True
    except mysql.connector.Error as e:
        logging.error(f"Failed to update record with source_id {source_id} in {table_name}: {e}")
        return False
    finally:
        cursor.close()
