import mysql.connector
import logging
from utils.config_loader import load_config

def get_db_connection():
    """Establishes a connection to the database using loaded credentials."""
    config = load_config()
    db_config = config.get('database', {})
    
    try:
        connection = mysql.connector.connect(
            host=db_config.get('host'),
            port=db_config.get('port'),
            database=db_config.get('name'),
            user=db_config.get('user'),
            password=db_config.get('password')
        )
        if connection.is_connected():
            logging.info("Successfully connected to the database")
            return connection
    except mysql.connector.Error as e:
        logging.error(f"Error while connecting to MySQL: {e}")
        logging.error("Please ensure your .env file is in the project root and contains the correct DB_USER and DB_PASSWORD.")
        return None

def get_urls_to_crawl(table_name):
    """Fetches URLs and book names from a table where l3_scan_status is not 'pass'."""
    connection = get_db_connection()
    if connection is None:
        return []

    cursor = connection.cursor(dictionary=True)
    # --- MODIFIED: Added 'book_name' to the SELECT statement ---
    query = f"SELECT id, book_url, book_name FROM {table_name} WHERE l3_scan_status != 'pass' OR l3_scan_status IS NULL"
    
    try:
        cursor.execute(query)
        records = cursor.fetchall()
        return records
    except mysql.connector.Error as e:
        logging.error(f"Error fetching records from {table_name}: {e}")
        return []
    finally:
        if connection and connection.is_connected():
            cursor.close()
            connection.close()

def update_scan_status(table_name, record_id, status):
    """Updates the l3_scan_status for a given record."""
    connection = get_db_connection()
    if connection is None:
        return

    cursor = connection.cursor()
    query = f"UPDATE {table_name} SET l3_scan_status = %s WHERE id = %s"
    
    try:
        cursor.execute(query, (status, record_id))
        connection.commit()
    except mysql.connector.Error as e:
        logging.error(f"Error updating status for record {record_id} in {table_name}: {e}")
    finally:
        if connection and connection.is_connected():
            cursor.close()
            connection.close()
