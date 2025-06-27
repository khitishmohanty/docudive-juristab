from sqlalchemy import text
import uuid
import os
import re
from datetime import datetime
import boto3

NAVIGATION_PATH_DEPTH = int(os.getenv("NAVIGATION_PATH_DEPTH", 3)) # Duplicate checking

# --- AWS Clients ---
s3_client = boto3.client('s3')

def get_parent_url_details(engine, parent_url_id):
    print(f"\nFetching base_url for parent_url_id: {parent_url_id}...")
    try:
        with engine.connect() as connection:
            query = text("SELECT base_url FROM parent_urls WHERE id = :id")
            result = connection.execute(query, {"id": parent_url_id}).fetchone()
            if result: return result[0]
            print(f"  - FATAL ERROR: No record found for id='{parent_url_id}'")
    except Exception as e:
        print(f"  - FATAL ERROR: Could not query database: {e}")
    return None

# --- New S3 and Data Saving Logic ---
def save_content_to_s3(content, bucket, key):
    """Saves string content to a file in S3."""
    try:
        s3_client.put_object(Bucket=bucket, Key=key, Body=content, ContentType='text/html')
        print(f"    - Successfully saved content to S3: s3://{bucket}/{key}")
    except Exception as e:
        print(f"    - ERROR: Failed to save to S3 bucket '{bucket}': {e}")
        raise
    
def save_record_and_get_id(engine, data, parent_url_id, navigation_path, table):
    """
    Checks if a record with the same book_name and book_context exists.
    If not, saves a new record and returns the new UUID. If it exists, returns None.
    """
    book_name_to_check = data.get('book_name')
    book_context_to_check = data.get('book_context')

    # A book name is required to check for duplicates.
    if not book_name_to_check:
        print("    - WARNING: Book name is missing, cannot check for duplicates or insert.")
        return None

    try:
        with engine.connect() as connection:
            with connection.begin():
                # Step 1: Check for an existing record with the same name and context.
                find_query = text(f"SELECT id FROM {table} WHERE book_name = :book_name AND book_context = :book_context")
                params_find = {"book_name": book_name_to_check, "book_context": book_context_to_check}
                existing_record = connection.execute(find_query, params_find).fetchone()

                if existing_record:
                    # Step 2a: If the record exists, print a message and return None to skip processing.
                    print(f"  - Record for '{book_name_to_check}' already exists. Skipping.")
                    return None
                else:
                    # Step 2b: If the record does not exist, proceed with inserting a new one.
                    record_id = str(uuid.uuid4())
                    print(f"  - Inserting new record for '{book_name_to_check}' into table '{table}'")

                    insert_query = text(f"""
                        INSERT INTO {table} (id, parent_url_id, book_name, book_context, book_url, navigation_path, date_collected, is_active)
                        VALUES (:id, :parent_url_id, :book_name, :book_context, :book_url, :navigation_path, :date_collected, 1)
                    """)
                    params_insert = {
                        "id": record_id,
                        "parent_url_id": parent_url_id,
                        "book_name": book_name_to_check,
                        "book_context": book_context_to_check,
                        "book_url": data.get('book_url'),
                        "navigation_path": navigation_path,
                        "date_collected": datetime.now()
                    }
                    connection.execute(insert_query, params_insert)
                    
                    print(f"    - DB insert successful. New record ID: {record_id}")
                    return record_id

    except Exception as e:
        print(f"    - FATAL ERROR during database check or insert: {e}")
        raise