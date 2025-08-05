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

def fetch_caselaws_for_gcp_ingestion(conn, update_table_config):
    """
    Fetches records that are ready for ingestion into GCP.
    It joins metadata, enrichment status, and registry tables, and filters out
    records that have already been successfully ingested.
    
    Args:
        conn: The database connection object.
        update_table_config (dict): The write configuration from the YAML file.
        
    Returns:
        list: A list of dictionaries, where each dictionary is a record.
    """
    if not conn:
        return []
    
    cursor = conn.cursor(dictionary=True)
    status_column = update_table_config['columns']['processing_status']
    
    # This query joins the necessary tables to get all metadata for records
    # that have successfully passed the metadata extraction and text processing stages,
    # and have not yet been ingested into GCP.
    query = f"""
    SELECT 
        cm.id,
        cm.source_id,
        cm.count_char,
        cm.count_word,
        cm.file_no,
        cm.presiding_officer,
        cm.counsel,
        cm.law_firm_agency,
        cm.court_type,
        cm.hearing_location,
        cm.judgment_date,
        cm.hearing_dates,
        cm.incident_date,
        cm.keywords,
        cm.legislation_cited,
        cm.affected_sectors,
        cm.practice_areas,
        cm.citation,
        cm.key_issues,
        cm.panelist,
        cm.orders,
        cm.decision,
        cm.cases_cited,
        cm.matter_type,
        cm.parties,
        cm.representation,
        cm.category,
        cm.bjs_number,
        cr.neutral_citation,
        cr.jurisdiction_code,
        cr.decision_date,
        cr.book_name
    FROM legal_store.caselaw_metadata cm
    JOIN legal_store.caselaw_enrichment_status ces 
        ON cm.source_id = ces.source_id
    JOIN legal_store.caselaw_registry cr 
        ON cm.source_id = cr.source_id
    WHERE 
        ces.status_metadataextract = 'pass'
        AND ces.status_text_processor = 'pass'
        AND ces.`{status_column}` != 'pass';
    """

    try:
        cursor.execute(query)
        results = cursor.fetchall()
        logging.info(f"Fetched {len(results)} records for GCP ingestion.")
        return results
    except mysql.connector.Error as e:
        logging.error(f"Failed to fetch data for GCP ingestion: {e}")
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
        status (str): The processing status ('pass' or 'failed').
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
