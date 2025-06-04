import datetime
import re
from urllib.parse import urlparse
from sqlalchemy import text
# import uuid # Not strictly needed here as DB generates UUIDs

# Ensure 'aws_utils.py' is in the same directory or included in your Lambda deployment package.
import aws_utils # This line assumes aws_utils.py can be imported.

# --- Helper function for filename generation ---
def generate_derived_filenames(input_url_str):
    """
    Generates robots_file_name and sitemap_file_name from the input URL's domain.
    Example: "https://www.example.co.uk/path" -> "example_co_uk.txt", "example_co_uk.xml"
    """
    parsed_url = urlparse(input_url_str)
    
    # Use hostname (netloc) for filename generation. e.g., "www.example.com"
    host_part = parsed_url.netloc
    
    # Remove port if present, e.g., "example.com:8080" -> "example.com"
    host_part = host_part.split(':')[0]

    # Remove "www." prefix if it exists at the beginning of the host_part
    if host_part.lower().startswith("www."):
        host_part = host_part[4:]
    
    # Replace all dots with underscores
    sanitized_base_name = host_part.replace('.', '_')
    
    # Further sanitize to remove any characters not suitable for filenames/S3 keys if necessary
    # For now, sticking to the prompt's "replace . with _"
    # Example: if host_part could be "my-site.com", it becomes "my-site_com"
    # If "my-site_com" is not desired and "my_site_com" is, add:
    # sanitized_base_name = sanitized_base_name.replace('-', '_')

    robots_file_name = f"{sanitized_base_name}.txt"
    sitemap_file_name = f"{sanitized_base_name}.xml"
    
    return robots_file_name, sitemap_file_name

# --- Lambda Handler ---
def lambda_handler(event, context):
    """
    AWS Lambda handler function.
    Processes an input URL to add a record to parent_urls and logs the job in audit_log.
    """
    job_name = "add_parent_url_job" 
    start_time = datetime.datetime.utcnow() # UTC is recommended for server environments
    end_time = None
    job_status = "failed" # Default to failed; will be set to 'success' on successful completion
    
    input_url = event.get('url')
    engine = None  # Initialize database engine variable

    # For logging and detailed response (optional, main output is "success"/"failure")
    log_messages = []
    log_messages.append(f"Job '{job_name}' started at {start_time.isoformat()}Z for URL: {input_url}")

    try:
        # 1. Input Validation
        if not input_url:
            log_messages.append("❌ Error: 'url' not provided in the event.")
            print("\n".join(log_messages)) # Print accumulated logs
            return "failure"

        parsed_url = urlparse(input_url)
        if not parsed_url.scheme or not parsed_url.netloc:
            log_messages.append(f"❌ Error: Invalid URL '{input_url}'. Must have a scheme (e.g., http, https) and a domain.")
            print("\n".join(log_messages))
            return "failure"
        
        # The input URL itself is stored as 'base_url' in the parent_urls table
        db_base_url = input_url

        # 2. Generate Filenames
        robots_fn, sitemap_fn = generate_derived_filenames(db_base_url)
        log_messages.append(f"⚙️ Generated filenames: robots='{robots_fn}', sitemap='{sitemap_fn}'")

        # 3. Database Connection
        # This uses create_db_engine from your aws_utils.py
        engine = aws_utils.create_db_engine()
        if not engine:
            log_messages.append("❌ Error: Failed to create database engine. Check DB credentials, connectivity, and aws_utils.py.")
            print("\n".join(log_messages))
            return "failure"
        log_messages.append("✅ Database engine created successfully.")

        # 4. Create Record in parent_urls Table
        parent_urls_data = {
            "base_url": db_base_url,
            "crawl": "Y",
            "robots_file_name": robots_fn,
            "sitemap_file_name": sitemap_fn,
            "config_file_fetch_status": "pending" # UPDATED column name and value
            # Assuming other columns like 'id', 'created_at' are auto-generated or allow NULLs
        }

        with engine.connect() as connection:
            # Use a transaction for the insert operation
            with connection.begin():
                table_name_parent_urls = "parent_urls"
                
                # Basic validation for table name (fixed in this context)
                if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table_name_parent_urls):
                    raise ValueError(f"FATAL: Invalid hardcoded table name '{table_name_parent_urls}'.")

                # Prepare columns and placeholders for the SQL query
                columns = []
                placeholders = []
                for col_name in parent_urls_data.keys():
                    # Basic validation for column names (fixed keys of parent_urls_data)
                    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", col_name):
                        raise ValueError(f"FATAL: Invalid hardcoded column name '{col_name}' for table '{table_name_parent_urls}'.")
                    columns.append(f"`{col_name}`") # Use backticks for column names for safety with reserved words
                    placeholders.append(f":{col_name}")
                
                columns_str = ", ".join(columns)
                placeholders_str = ", ".join(placeholders)

                # Construct and execute the INSERT query using SQLAlchemy's text() for parameter binding
                insert_query_str = f"INSERT INTO `{table_name_parent_urls}` ({columns_str}) VALUES ({placeholders_str})"
                query = text(insert_query_str)
                
                connection.execute(query, parent_urls_data)
                log_messages.append(f"✅ Record successfully inserted into '{table_name_parent_urls}' for URL: {db_base_url}")
            
            # If the transaction committed successfully
            job_status = "success"

    except Exception as e:
        job_status = "failed" 
        error_type = type(e).__name__
        log_messages.append(f"❌ An error occurred during main processing: {error_type} - {str(e)}")
        # The full stack trace will be available in AWS CloudWatch Logs by default.

    finally:
        end_time = datetime.datetime.utcnow()
        log_messages.append(f"⚙️ Job '{job_name}' finished at {end_time.isoformat()}Z with status: {job_status}")

        if engine: # Attempt to log to audit_log table only if DB engine was available
            try:
                with engine.connect() as connection:
                    with connection.begin(): # Transaction for audit log insertion
                        audit_log_data = {
                            "job_name": job_name,
                            "start_time": start_time,
                            "end_time": end_time,
                            "job_status": job_status
                            # The 'id' (uuid) and 'created_at' (timestamp) columns are expected to be auto-generated by the database
                        }
                        
                        table_name_audit_log = "audit_log"
                        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table_name_audit_log):
                             raise ValueError(f"FATAL: Invalid hardcoded table name '{table_name_audit_log}'.")

                        audit_columns = []
                        audit_placeholders = []
                        for col_name in audit_log_data.keys():
                            if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", col_name):
                                raise ValueError(f"FATAL: Invalid hardcoded column name '{col_name}' for table '{table_name_audit_log}'.")
                            audit_columns.append(f"`{col_name}`") # Use backticks
                            audit_placeholders.append(f":{col_name}")
                        
                        audit_columns_str = ", ".join(audit_columns)
                        audit_placeholders_str = ", ".join(audit_placeholders)
                        
                        audit_insert_query_str = f"INSERT INTO `{table_name_audit_log}` ({audit_columns_str}) VALUES ({audit_placeholders_str})"
                        audit_query = text(audit_insert_query_str)
                        
                        connection.execute(audit_query, audit_log_data)
                        log_messages.append(f"✅ Audit log record created successfully for job '{job_name}'.")
            except Exception as audit_e:
                error_type = type(audit_e).__name__
                log_messages.append(f"❌ CRITICAL: Failed to write to audit_log for job '{job_name}'. Error: {error_type} - {str(audit_e)}")
            finally:
                # Dispose of the engine to release database connections, especially important in Lambda.
                try:
                    engine.dispose()
                    log_messages.append("ℹ️ Database engine disposed.")
                except Exception as dispose_e:
                    log_messages.append(f"⚠️ Warning: Error disposing database engine: {str(dispose_e)}")
        else:
            log_messages.append(f"ℹ️ Audit Log to DB skipped: DB engine was not available or not initialized.")
        
        # Print all accumulated log messages to CloudWatch
        print("\n".join(log_messages))
        
        return job_status # Return "success" or "failure"

# Example usage (for local testing, not part of Lambda deployment normally):
if __name__ == '__main__':
    # Before running locally, ensure environment variables for aws_utils.py are set
    # (DB_USER, DB_PASSWORD, DB_HOST, DB_NAME, DB_DIALECT, DB_DRIVER)

    mock_event_success = {
        'url': 'https://legislation.nsw.gov.au/'
    }

    print("--- Testing with a valid URL (updated column) ---")
    result = lambda_handler(mock_event_success, None)
    print(f"Lambda handler returned: {result}\n")