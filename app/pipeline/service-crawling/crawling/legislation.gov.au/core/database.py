from sqlalchemy import text
import uuid
import os
import re
from datetime import datetime


NAVIGATION_PATH_DEPTH = int(os.getenv("NAVIGATION_PATH_DEPTH", 3)) # Duplicate checking

def get_parent_url_details(engine, parent_url_id):
    """Connects to the database and fetches the base_url for the given ID."""
    print(f"\nFetching base_url for parent_url_id: {parent_url_id}...")
    try:
        with engine.connect() as connection:
            query = text("SELECT base_url FROM parent_urls WHERE id = :id")
            result = connection.execute(query, {"id": parent_url_id}).fetchone()
            if result: return result[0]
            print(f"  - FATAL ERROR: No record found for id='{parent_url_id}'")
            return None
    except Exception as e:
        print(f"  - FATAL ERROR: Could not query database: {e}")
        return None

def save_scraped_data_to_db(engine, scraped_data, parent_url_id, navigation_path_parts, page_num, destination_table):
    """Saves a list of scraped data to the specified destination table with parsing."""
    if not scraped_data: return 0
    
    if not re.match(r"^[a-zA-Z0-9_]+$", destination_table):
        print(f"  - FATAL ERROR: Invalid destination_table name: '{destination_table}'. Aborting save.")
        return 0

    human_readable_path = "/".join(navigation_path_parts) + f"/Page/{page_num}"
    try:
        with engine.connect() as connection:
            with connection.begin():
                path_prefix_parts = navigation_path_parts[:NAVIGATION_PATH_DEPTH]
                path_prefix = "/".join(path_prefix_parts) + "%"
                
                existing_urls_query_str = f"SELECT book_url FROM {destination_table} WHERE parent_url_id = :parent_url_id AND navigation_path LIKE :path_prefix"
                existing_urls_query = text(existing_urls_query_str)
                
                existing_urls_result = connection.execute(existing_urls_query, {"parent_url_id": parent_url_id, "path_prefix": path_prefix}).fetchall()
                existing_urls = {row[0] for row in existing_urls_result}
                
                records_to_insert = []
                for item in scraped_data:
                    book_url = item.get('book_url')
                    if book_url and book_url not in existing_urls:
                        # --- Parsing Logic for legislation.gov.au ---
                        metadata_text = item.get('metadata_text') or ''
                        
                        version_match = re.search(r'(C[0-9A-Z]+)', metadata_text)
                        book_version = version_match.group(1) if version_match else None
                        
                        act_no_match = re.search(r'(Act No\. \d+, \d{4})', metadata_text)
                        book_act_no = act_no_match.group(1) if act_no_match else None
                        
                        reg_date_match = re.search(r'Registered: (\d{2}/\d{2}/\d{4})', metadata_text)
                        book_registered_date = None
                        if reg_date_match:
                            try:
                                book_registered_date = datetime.strptime(reg_date_match.group(1), '%d/%m/%Y')
                            except ValueError:
                                print(f"  - WARNING: Could not parse date '{reg_date_match.group(1)}'. Storing as NULL.")

                        record = {
                            "id": str(uuid.uuid4()), "parent_url_id": parent_url_id,
                            "book_name": item.get('book_name'),
                            "book_url": book_url,
                            "book_effective_date": item.get('book_effective_date'),
                            "book_version": book_version,
                            "book_act_no": book_act_no,
                            "book_registered_date": book_registered_date,
                            "navigation_path": human_readable_path,
                            "date_collected": datetime.now(), "is_active": 1,
                        }
                        records_to_insert.append(record)
                
                if not records_to_insert:
                    print(f"  - All {len(scraped_data)} scraped records for this page already exist. Nothing to insert.")
                    return 0
                print(f"  - Found {len(records_to_insert)} new records to insert.")

                insert_query_str = f"""
                    INSERT INTO {destination_table} (
                        id, parent_url_id, book_name, book_url, navigation_path, date_collected, is_active,
                        book_effective_date, book_act_no, book_registered_date, book_version
                    ) VALUES (
                        :id, :parent_url_id, :book_name, :book_url, :navigation_path, :date_collected, :is_active,
                        :book_effective_date, :book_act_no, :book_registered_date, :book_version
                    )
                """
                query = text(insert_query_str)
                connection.execute(query, records_to_insert)
                print(f"  - Successfully saved {len(records_to_insert)} new records to '{destination_table}'.")
                return len(records_to_insert)
    except Exception as e:
        print(f"  - FATAL ERROR: Failed during database save operation: {e}")
        raise e