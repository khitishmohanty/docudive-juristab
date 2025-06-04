import os
import aws_utils # Assuming aws_utils.py is in the same directory or PYTHONPATH
from sqlalchemy import text
from botocore.exceptions import ClientError
import xml.etree.ElementTree as ET
from urllib.robotparser import RobotFileParser
from io import StringIO
from datetime import datetime, timezone
import uuid
import re # Ensure re is imported

# Environment variables for S3 are expected to be loaded by aws_utils.py
# S3_BUCKET_NAME = aws_utils.S3_BUCKET_NAME
# S3_DEST_FOLDER = aws_utils.S3_DEST_FOLDER # e.g., "crawl_configs/"

def _add_audit_log_entry(connection, audit_data):
    """
    Inserts a new record into the audit_log table.
    Assumes connection is an active SQLAlchemy connection with a transaction started.
    """
    try:
        required_fields = ['id', 'job_name', 'start_time', 'job_status']
        for field in required_fields:
            if field not in audit_data:
                print(f"❌ Audit log missing required field for insert: {field} in data {audit_data}")
                return False
        
        if 'created_at' not in audit_data: 
             audit_data['created_at'] = audit_data.get('start_time', datetime.now(timezone.utc))

        columns = []
        values_placeholders = []
        
        for key in audit_data.keys():
            if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", key):
                print(f"❌ Invalid column name in audit_data for insert: {key}")
                return False
            columns.append(key)
            values_placeholders.append(f":{key}")

        stmt_sql = f"INSERT INTO audit_log ({', '.join(columns)}) VALUES ({', '.join(values_placeholders)})"
        stmt = text(stmt_sql)
        
        print(f"AUDIT_LOG DEBUG: Attempting to execute INSERT: {stmt_sql} with params {audit_data}")
        connection.execute(stmt, audit_data)
        print(f"✅ Audit log entry INSERTED for job_id: {audit_data['id']}, job_name: {audit_data['job_name']}")
        return True
    except Exception as e:
        print(f"❌ Error INSERTING audit log entry for job_id {audit_data.get('id')}: {e}")
        raise 

def get_s3_object_content(s3_client, bucket_name, object_key):
    """
    Retrieves the content of an object from S3.
    """
    try:
        print(f"Attempting to fetch s3://{bucket_name}/{object_key}")
        response = s3_client.get_object(Bucket=bucket_name, Key=object_key)
        content = response['Body'].read().decode('utf-8')
        print(f"Successfully fetched content from s3://{bucket_name}/{object_key}")
        return content
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
            print(f"❌ Error: Object not found in S3: s3://{bucket_name}/{object_key}")
        else:
            print(f"❌ AWS ClientError fetching s3://{bucket_name}/{object_key}: {e}")
        raise 
    except Exception as e:
        print(f"❌ An unexpected error occurred fetching s3://{bucket_name}/{object_key}: {e}")
        raise 

def handle_robots_txt_content(robots_content, base_url):
    """
    Parses and "handles" robots.txt content.
    """
    print("\n--- Handling robots.txt ---")
    if not robots_content:
        print("No robots.txt content to handle.")
        return

    parser = RobotFileParser()
    parser.parse(StringIO(robots_content).readlines())
    print(f"Robots.txt content (first 500 chars):\n{robots_content[:500]}...\n")
    user_agent = '*'
    print(f"Interpreting rules for User-agent: {user_agent}")
    disallowed_paths = []
    current_agents = []
    for line in StringIO(robots_content):
        line = line.strip()
        if not line or line.startswith('#'): continue
        parts = line.split(':', 1)
        if len(parts) == 2:
            key, value = parts[0].strip().lower(), parts[1].strip()
            if key == 'user-agent': current_agents.append(value)
            elif key == 'disallow' and (user_agent in current_agents or '*' in current_agents) and value:
                disallowed_paths.append(value)
    
    if disallowed_paths:
        print(f"Disallowed paths for relevant user-agents (including '*') found:")
        for path in disallowed_paths[:10]: print(f"  - {path}")
        if len(disallowed_paths) > 10: print(f"  ... and {len(disallowed_paths) - 10} more.")
    else:
        print("No specific disallow rules found for '*' or explicitly listed user-agents in this basic parse.")
    print("--- End robots.txt Handling ---")

def handle_sitemap_xml_content(sitemap_content):
    """
    Parses and "handles" sitemap.xml content.
    """
    print("\n--- Handling sitemap.xml ---")
    if not sitemap_content:
        print("No sitemap.xml content to handle.")
        return

    print(f"Sitemap.xml content (first 500 chars):\n{sitemap_content[:500]}...\n")
    urls = []
    try:
        root = ET.fromstring(sitemap_content)
        namespaces = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        loc_elements = root.findall('.//{*}loc') 
        if not loc_elements: loc_elements = root.findall('.//s:loc', namespaces)
        for loc_element in loc_elements:
            if loc_element.text: urls.append(loc_element.text.strip())
        
        if urls:
            print(f"Found {len(urls)} URLs in sitemap:")
            for url in urls[:10]: print(f"  - {url}")
            if len(urls) > 10: print(f"  ... and {len(urls) - 10} more.")
        else:
            print("No <loc> URLs found in the sitemap content.")
    except ET.ParseError as e:
        print(f"❌ Error parsing sitemap XML: {e}")
        raise 
    except Exception as e:
        print(f"❌ An unexpected error occurred during sitemap handling: {e}")
        raise 
    print("--- End sitemap.xml Handling ---")

def process_crawl_item(item_id: str):
    """
    Processes a crawl item based on its ID with audit logging and error handling.
    """
    print(f"🚀 Starting processing for ID: {item_id}")
    
    audit_job_id = str(uuid.uuid4())
    job_name = "crawling_service" 
    start_time = datetime.now(timezone.utc)
    
    db_engine = aws_utils.create_db_engine()
    s3_client = aws_utils.get_s3_client()

    record = None 
    initial_audit_log_succeeded = False

    if not db_engine:
        print(f"❌ Database engine could not be created for audit_job_id {audit_job_id}. Aborting. Cannot log to audit table.")
        return
    
    if not s3_client:
        print(f"❌ S3 client could not be created for audit_job_id {audit_job_id}. Aborting.")
        current_time = datetime.now(timezone.utc)
        s3_fail_audit_data = {
            'id': audit_job_id, 'job_name': job_name, 
            'start_time': start_time, 'end_time': current_time,
            'job_status': 'failed', 
            'job_duration': (current_time - start_time).total_seconds(),
            'created_at': start_time 
        }
        try:
            with db_engine.connect() as conn:
                with conn.begin():
                    print(f"AUDIT_LOG DEBUG: Attempting S3_CLIENT_FAILURE audit log.")
                    _add_audit_log_entry(conn, s3_fail_audit_data)
        except Exception as db_err:
            print(f"❌ Critical: Failed to initialize S3 client AND also failed to log this to audit_log for audit_job_id {audit_job_id}: {db_err}")
        return

    overall_job_status = 'success' 
    parent_crawl_status_update = None 

    try:
        with db_engine.connect() as connection:
            with connection.begin(): 
                initial_audit_data = {
                    'id': audit_job_id, 'job_name': job_name,
                    'start_time': start_time, 'job_status': 'running',
                    'created_at': start_time 
                }
                print(f"AUDIT_LOG DEBUG: Attempting INITIAL 'running' audit log.")
                if _add_audit_log_entry(connection, initial_audit_data):
                    initial_audit_log_succeeded = True
                    print(f"AUDIT_LOG DEBUG: Initial 'running' audit log SUCCEEDED.")
                else:
                    # This path is unlikely if _add_audit_log_entry raises on DB error and only returns False on field check fail
                    print(f"❌ Critical: _add_audit_log_entry returned False for initial log, job {audit_job_id}. Forcing job status to failed.")
                    initial_audit_log_succeeded = False # Ensure it's false
                    overall_job_status = 'failed' 
                    raise Exception("Initial audit log entry failed (returned False).") # This will be caught by outer except

                stmt = text("""
                    SELECT id, base_url, crawl_status, robots_file_status, robots_file_name, sitemap_file_status, sitemap_file_name
                    FROM parent_urls
                    WHERE id = :item_id
                """)
                result_proxy = connection.execute(stmt, {"item_id": item_id})
                record = result_proxy.fetchone() 

                if not record:
                    print(f"ℹ️ No record found in parent_urls for ID: {item_id}. Marking job as successful (no action).")
                elif record.crawl_status not in ('pending', 'failed'): 
                    print(f"ℹ️ Crawl status for ID {item_id} is '{record.crawl_status}', which is not 'pending' or 'failed'. Skipping S3 processing. Marking job as successful.")
                else: 
                    print(f"✅ Crawl status is '{record.crawl_status}'. Proceeding with S3 file checks and processing for ID {item_id}.")
                    base_url_for_robots = record.base_url if record.base_url else ""

                    if record.robots_file_status == 'success' and record.robots_file_name:
                        s3_robots_key = f"{aws_utils.S3_DEST_FOLDER.strip('/')}/{item_id}/{record.robots_file_name}"
                        robots_content = get_s3_object_content(s3_client, aws_utils.S3_BUCKET_NAME, s3_robots_key)
                        if robots_content: handle_robots_txt_content(robots_content, base_url_for_robots)
                    elif record.robots_file_status == 'failed':
                        print(f"ℹ️ Robots file status is 'failed' for ID {item_id}.")
                    else: 
                        print(f"ℹ️ Robots file status is '{record.robots_file_status}' or name is missing for ID {item_id}. Skipping robots.txt processing.")

                    if record.sitemap_file_status == 'success' and record.sitemap_file_name:
                        s3_sitemap_key = f"{aws_utils.S3_DEST_FOLDER.strip('/')}/{item_id}/{record.sitemap_file_name}"
                        sitemap_content = get_s3_object_content(s3_client, aws_utils.S3_BUCKET_NAME, s3_sitemap_key)
                        if sitemap_content: handle_sitemap_xml_content(sitemap_content)
                    elif record.sitemap_file_status == 'failed':
                        print(f"ℹ️ Sitemap file status is 'failed' for ID {item_id}.")
                    else: 
                        print(f"ℹ️ Sitemap file status is '{record.sitemap_file_status}' or name is missing for ID {item_id}. Skipping sitemap.xml processing.")
                    
                    parent_crawl_status_update = 'success' 
    except Exception as e:
        print(f"❌ An unhandled error occurred during main processing for audit_job_id {audit_job_id} (item_id: {item_id}): {e}")
        overall_job_status = 'failed'
        initial_audit_log_succeeded = False # If main processing fails, assume initial log (if made) might not be committed or is rolled back.
        if record and record.crawl_status in ('pending', 'failed'): 
             parent_crawl_status_update = 'failed'
        
    finally:
        print(f"AUDIT_LOG DEBUG: Entering FINALLY block. initial_audit_log_succeeded = {initial_audit_log_succeeded}, overall_job_status = {overall_job_status}")
        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()
        
        final_log_data_for_insert = {
            'id': audit_job_id, 'job_name': job_name,
            'start_time': start_time, 'end_time': end_time,
            'job_status': overall_job_status, 'job_duration': duration,
            'created_at': start_time 
        }
        
        update_payload_for_audit = {
            'end_time': end_time, 
            'job_status': overall_job_status,
            'job_duration': duration
        }
        
        parent_update_payload = {}
        if parent_crawl_status_update:
            parent_update_payload['crawl_status'] = parent_crawl_status_update
            parent_update_payload['updated_at'] = datetime.now(timezone.utc)

        if db_engine: 
            try:
                with db_engine.connect() as final_conn:
                    with final_conn.begin(): 
                        if initial_audit_log_succeeded:
                            print(f"AUDIT_LOG DEBUG: In FINALLY, attempting to UPDATE audit log for job {audit_job_id} with data: {update_payload_for_audit}")
                            if not aws_utils.update_db_record(final_conn, "audit_log", "id", audit_job_id, update_payload_for_audit):
                                print(f"❌ Critical: Failed to UPDATE final audit log (aws_utils.update_db_record returned False) for job {audit_job_id}.")
                            else:
                                print(f"✅ Final audit log UPDATED for job {audit_job_id} with status: {overall_job_status}")
                        else: 
                            print(f"AUDIT_LOG DEBUG: In FINALLY, initial_audit_log_succeeded is False. Attempting to INSERT final audit log for job {audit_job_id} with data: {final_log_data_for_insert}")
                            # _add_audit_log_entry will raise on DB error, or return True/False
                            add_result = _add_audit_log_entry(final_conn, final_log_data_for_insert)
                            if add_result:
                                print(f"✅ Final audit log INSERTED (after earlier failure/no initial log) for job {audit_job_id} with status: {overall_job_status}")
                            else: # This means _add_audit_log_entry returned False (e.g. field check failed, though unlikely here)
                                print(f"❌ Critical: Failed to INSERT final audit log (after earlier failure, _add_audit_log_entry returned False) for job {audit_job_id}.")

                        if parent_update_payload and record: 
                            if not aws_utils.update_db_record(final_conn, "parent_urls", "id", item_id, parent_update_payload):
                                print(f"❌ Failed to update parent_urls.crawl_status for ID {item_id} to {parent_crawl_status_update}.")
                            else:
                                print(f"✅ parent_urls.crawl_status updated for ID {item_id} to {parent_crawl_status_update}.")
            except Exception as final_log_err:
                print(f"❌ Critical: Exception during final database updates in FINALLY block for audit_job_id {audit_job_id}: {final_log_err}")

    print(f"🏁 Finished processing for ID: {item_id}. Overall job status for audit_job_id {audit_job_id}: {overall_job_status}")

if __name__ == '__main__':
    print("Starting script example...")
    
    # IMPORTANT: Replace "your-test-uuid" with an actual ID from your parent_urls table for testing.
    test_item_id = "df8edd0e-0f69-484a-930b-67dc6072013b" 
    # test_item_id = "actual-id-from-db" # Example
    
    if test_item_id == "your-test-uuid":
        s3_bucket = getattr(aws_utils, 'S3_BUCKET_NAME', 'S3_BUCKET_NAME_NOT_SET')
        s3_folder = getattr(aws_utils, 'S3_DEST_FOLDER', 'S3_DEST_FOLDER_NOT_SET','S3_DEST_FOLDER_NOT_SET').strip('/')
        
        print("\n⚠️ PLEASE REPLACE 'your-test-uuid' with an actual ID from your database for testing.")
        print("   If 'your-test-uuid' is used, process_crawl_item will NOT be called.")
        print("Ensure your .env file is set up for database and AWS S3 access via aws_utils.py.")
        print(f"Example S3 path for robots.txt: s3://{s3_bucket}/{s3_folder}/{test_item_id}/<robots_file_name_from_db>")
        print(f"Example S3 path for sitemap.xml: s3://{s3_bucket}/{s3_folder}/{test_item_id}/<sitemap_file_name_from_db>")
    else:
        process_crawl_item(test_item_id)
