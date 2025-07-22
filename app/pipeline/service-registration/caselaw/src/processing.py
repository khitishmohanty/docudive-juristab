import logging
import os
from datetime import datetime, timezone
import pandas as pd
import boto3
from botocore.exceptions import ClientError
from sqlalchemy import text
from utils.database import create_db_engine
from utils.parsing import load_config, load_json_config, parse_citation
from utils.audit import write_audit_log

def verify_content_files(s3_path, source_id):
    """
    Verifies the existence and content of required HTML files for a given source_id in S3.

    Args:
        s3_path (str): The S3 path (e.g., 's3://legal-store/case-laws/nt/').
        source_id (str): The unique identifier for the case.

    Returns:
        str: 'pass' if all files exist and are non-empty, 'fail' otherwise.
    """
    if not s3_path.startswith('s3://'):
        logging.error(f"Invalid S3 path provided to verify_content_files: {s3_path}")
        return 'fail'

    s3 = boto3.client('s3')
    files_to_check = ['excerpt.html', 'miniviewer.html', 'summary.html']
    
    # Parse bucket and prefix from the S3 path
    parts = s3_path.replace('s3://', '').split('/')
    bucket_name = parts[0]
    base_prefix = '/'.join(parts[1:]) if len(parts) > 1 else ''
    
    # Ensure base_prefix ends with a slash if it's not empty
    if base_prefix and not base_prefix.endswith('/'):
        base_prefix += '/'

    try:
        for file_name in files_to_check:
            # Construct the full S3 key for the object
            s3_key = f"{base_prefix}{source_id}/{file_name}"
            
            try:
                # Use head_object to check for existence and size without downloading
                response = s3.head_object(Bucket=bucket_name, Key=s3_key)
                
                # Check if the file is empty
                if response['ContentLength'] == 0:
                    logging.warning(f"S3 file check failed for s3://{bucket_name}/{s3_key}. Object is empty.")
                    return 'fail'
            
            except ClientError as e:
                # If the error code is 404 (Not Found), the file is missing
                if e.response['Error']['Code'] == '404':
                    logging.warning(f"S3 file check failed for s3://{bucket_name}/{s3_key}. Object is missing.")
                    return 'fail'
                else:
                    # Handle other potential AWS errors (e.g., permissions)
                    logging.error(f"An unexpected AWS error occurred checking {s3_key}: {e}")
                    raise

        logging.info(f"All content files verified in S3 for source_id {source_id}.")
        return 'pass'
    
    except Exception as e:
        logging.error(f"Error during S3 file verification for source_id {source_id}. Error: {e}")
        return 'fail'

def process_caselaw_data():
    """
    Main ETL function to extract, transform, and load caselaw data.
    """
    logging.info("Starting caselaw data processing job.")
    program_start_time = datetime.now(timezone.utc)
    job_status = 'success'
    error_message = None
    
    config = load_config('config/config.yaml')
    if not config:
        logging.critical("Could not load config.yaml. Aborting job.")
        return

    job_name_from_config = config.get('job_name', 'caselaw_etl_job')
    job_id_from_config = config.get('job_id', 'unknown')

    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")
    if not db_user or not db_password:
        logging.critical("DB_USER and DB_PASSWORD environment variables must be set. Aborting job.")
        return
    logging.info("Successfully loaded database credentials from environment.")

    dest_engine = create_db_engine(config['database']['destination'], db_user, db_password)
    if not dest_engine:
        logging.critical("Destination database connection failed. Aborting job.")
        return

    audit_log_config = config.get('audit_log_table', [{}])[0]
    audit_table_name = audit_log_config.get('table')

    try:
        aus_codes = load_json_config('config/australia_config.json')
        nz_codes = load_json_config('config/new_zealand_config.json')
        all_codes = pd.concat([aus_codes, nz_codes], ignore_index=True)

        source_engine = create_db_engine(config['database']['source'], db_user, db_password)
        if not source_engine:
            raise ConnectionError("Source database connection failed.")
            
        dest_table = config['tables']['tables_to_write'][0]['table']
        
        filepath_from_config = config.get('filepath', 's3://legal-store/case-laws/')
        base_s3_path = "/".join(filepath_from_config.split('/')[:-2]) if 's3://' in filepath_from_config else filepath_from_config
        
        logging.info(f"Program run started at: {program_start_time.isoformat()}")

        for source_info in config['tables']['tables_to_read']:
            source_table = source_info['table']
            jurisdiction_code = source_info.get('jurisdiction')
            storage_folder = source_info.get('storage_folder')

            if not storage_folder:
                logging.warning(f"'storage_folder' not configured for table {source_table}. Skipping this table.")
                continue

            logging.info(f"--- Processing source table: {source_table} (Jurisdiction: {jurisdiction_code}, Storage Folder: {storage_folder}) ---")
            
            source_df = pd.read_sql_table(source_table, source_engine)
            logging.info(f"Read {len(source_df)} records from {source_table}.")

            total_records = len(source_df)
            for index, row in source_df.iterrows():
                record_num = index + 1
                source_id = row['id']
                log_prefix = f"Record {record_num}/{total_records} (ID: {source_id})"
                
                logging.info(f"{log_prefix}: Starting processing.")
                record_start_time = datetime.now(timezone.utc)
                
                try:
                    with dest_engine.connect() as connection:
                        query = text(f"SELECT status_registration FROM {dest_table} WHERE source_id = :source_id")
                        result = connection.execute(query, {'source_id': source_id}).fetchone()

                    if result and result[0] == 'pass':
                        logging.info(f"{log_prefix}: Status is already 'pass'. Skipping.")
                        continue

                    logging.info(f"{log_prefix}: Requires processing (Current Status: {result[0] if result else 'not started'}).")
                    
                    citation_details = parse_citation(row['book_context'], all_codes, jurisdiction_code)

                    file_path = f"{base_s3_path}/{storage_folder}/{source_id}"
                    storage_folder_s3_path = f"{base_s3_path}/{storage_folder}/"
                    content_download_status = verify_content_files(storage_folder_s3_path, source_id)

                    record_data = {
                        'source_id': source_id,
                        'neutral_citation': row['book_context'],
                        'jurisdiction_code': jurisdiction_code,
                        'year': citation_details['year'],
                        'decision_date': citation_details['decision_date'],
                        'file_path': file_path,
                        'source_url': row.get('book_url'),
                        'book_name': row['book_name'],
                        'status_content_download': content_download_status,
                    }

                    mandatory_fields = ['neutral_citation', 'jurisdiction_code', 'year', 'decision_date', 'book_name']
                    missing_fields = [field for field in mandatory_fields if not record_data.get(field) and record_data.get(field) != 0]
                    
                    if content_download_status == 'pass' and not missing_fields:
                        final_status = 'pass'
                    else:
                        final_status = 'fail'
                        if content_download_status == 'fail':
                            logging.warning(f"{log_prefix}: Marking as 'fail' due to missing or empty content files.")
                        if missing_fields:
                            logging.warning(f"{log_prefix}: Marking as 'fail'. Missing mandatory fields: {missing_fields}")
                    
                    record_end_time = datetime.now(timezone.utc)
                    record_duration = (record_end_time - record_start_time).total_seconds()

                    record_data.update({
                        'status_registration': final_status,
                        'start_time_registration': program_start_time,
                        'end_time_registration': record_end_time,
                        'duration_registration': record_duration
                    })

                    with dest_engine.connect() as conn:
                        if result:
                            update_cols = ", ".join([f"{key} = :{key}" for key in record_data])
                            update_query = text(f"UPDATE {dest_table} SET {update_cols} WHERE source_id = :source_id")
                            conn.execute(update_query, record_data)
                        else:
                            insert_df = pd.DataFrame([record_data])
                            insert_df.to_sql(dest_table, conn, if_exists='append', index=False)
                        conn.commit()
                    logging.info(f"{log_prefix}: Successfully processed in {record_duration:.4f} seconds. Final status: {final_status}")

                except Exception as e:
                    logging.error(f"{log_prefix}: Failed to process. Error: {e}", exc_info=True)

    except Exception as e:
        job_status = 'fail'
        error_message = str(e)
        logging.critical(f"A critical error occurred, terminating job. Error: {error_message}", exc_info=True)
    finally:
        program_end_time = datetime.now(timezone.utc)
        message = f"Job finished with status: {job_status}."
        if error_message:
            message += f" Details: {error_message}"

        if audit_table_name:
            write_audit_log(
                engine=dest_engine,
                table_name=audit_table_name,
                job_name=job_name_from_config,
                job_id=job_id_from_config,
                start_time=program_start_time,
                end_time=program_end_time,
                status=job_status,
                message=message
            )
        else:
            logging.warning("audit_log_table not configured in config.yaml. Skipping audit log.")

        logging.info("Caselaw data processing job finished.")
