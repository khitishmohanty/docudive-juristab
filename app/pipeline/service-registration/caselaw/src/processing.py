import logging
import os
from datetime import datetime, timezone
import pandas as pd
from sqlalchemy import text
from utils.database import create_db_engine
from utils.parsing import load_config, load_json_config, parse_parties, parse_citation

def write_audit_log(engine, table_name, job_name, start_time, end_time, status, message):
    """
    Writes a final log entry to the audit_log table.

    Args:
        engine: The SQLAlchemy engine for the destination database.
        table_name (str): The name of the audit log table.
        job_name (str): A name for the job being logged.
        start_time (datetime): The start time of the job.
        end_time (datetime): The end time of the job.
        status (str): The final status of the job ('success' or 'fail').
        message (str): A summary message for the job run.
    """
    try:
        duration = (end_time - start_time).total_seconds()
        audit_record = {
            'job_name': job_name,
            'start_time': start_time,
            'end_time': end_time,
            'job_status': status,
            'created_at': end_time,
            'job_duration': duration,
            'message': message
        }
        audit_df = pd.DataFrame([audit_record])
        with engine.connect() as conn:
            audit_df.to_sql(table_name, conn, if_exists='append', index=False)
            conn.commit()
        logging.info(f"Successfully wrote audit log for job '{job_name}'.")
    except Exception as e:
        logging.error(f"Failed to write to audit_log table '{table_name}'. Error: {e}")

def process_caselaw_data():
    """
    Main ETL function to extract, transform, and load caselaw data.
    """
    logging.info("Starting caselaw data processing job.")
    program_start_time = datetime.now(timezone.utc)
    job_status = 'success'
    error_message = None
    
    # --- Load Configurations ---
    config = load_config('config/config.yaml')
    if not config:
        logging.critical("Could not load config.yaml. Aborting job.")
        return

    # --- Load Credentials ---
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")
    if not db_user or not db_password:
        logging.critical("DB_USER and DB_PASSWORD environment variables must be set. Aborting job.")
        return
    logging.info("Successfully loaded database credentials from environment.")

    # --- Database Connections ---
    dest_engine = create_db_engine(config['database']['destination'], db_user, db_password)
    if not dest_engine:
        logging.critical("Destination database connection failed. Aborting job.")
        return

    # --- Get Audit Log Config ---
    audit_log_config = config.get('audit_log_table', [{}])[0]
    audit_table_name = audit_log_config.get('table')

    try:
        # --- Main Processing Block ---
        aus_codes = load_json_config('config/australia_config.json')
        nz_codes = load_json_config('config/new_zealand_config.json')
        all_codes = pd.concat([aus_codes, nz_codes], ignore_index=True)

        source_engine = create_db_engine(config['database']['source'], db_user, db_password)
        if not source_engine:
            raise ConnectionError("Source database connection failed.")
            
        dest_table = config['tables']['tables_to_write'][0]['table']
        filepath = config.get('filepath', None)

        logging.info(f"Program run started at: {program_start_time.isoformat()}")

        for source_info in config['tables']['tables_to_read']:
            source_table = source_info['table']
            jurisdiction_hint = source_info.get('jurisdiction')
            logging.info(f"--- Processing source table: {source_table} (Jurisdiction Hint: {jurisdiction_hint or 'None'}) ---")
            
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
                        query = text(f"SELECT status_registry FROM {dest_table} WHERE source_id = :source_id")
                        result = connection.execute(query, {'source_id': source_id}).fetchone()

                    if result and result[0] == 'pass':
                        logging.info(f"{log_prefix}: Status is already 'pass'. Skipping.")
                        continue

                    logging.info(f"{log_prefix}: Requires processing (Current Status: {result[0] if result else 'not started'}).")
                    
                    primary_party, secondary_party = parse_parties(row['book_name'])
                    citation_details = parse_citation(row['book_context'], all_codes, jurisdiction_hint)

                    record_data = {
                        'source_id': source_id, 'primary_party': primary_party, 'secondary_party': secondary_party,
                        'neutral_citation': row['book_context'], 'jurisdiction_code': citation_details['jurisdiction_code'],
                        'decision_number': citation_details['decision_number'], 'year': citation_details['year'],
                        'decision_date': citation_details['decision_date'], 'members': citation_details['members'],
                        'file_path': filepath, 'source_url': row.get('book_url'), 'book_name': row['book_name'],
                        'tribunal_code': citation_details['tribunal_code'], 'panel_or_division': citation_details['panel_or_division'],
                        'registration_start_time': program_start_time,
                    }

                    final_status = 'pass'
                    mandatory_fields = [
                        'primary_party', 'neutral_citation', 'jurisdiction_code', 
                        'decision_number', 'year', 'decision_date', 'book_name', 'tribunal_code'
                    ]
                    missing_fields = [field for field in mandatory_fields if not record_data.get(field)]
                    if missing_fields:
                        final_status = 'fail'
                        logging.warning(f"{log_prefix}: Will be marked as 'fail'. Missing mandatory fields: {missing_fields}")
                    
                    record_end_time = datetime.now(timezone.utc)
                    record_duration = (record_end_time - record_start_time).total_seconds()

                    record_data.update({
                        'status_registry': final_status,
                        'registration_end_time': record_end_time,
                        'duration_registry': record_duration
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
                    # Individual record failure does not fail the whole job, but we log it as 'fail'
                    # ... (rest of the individual failure logic remains the same)

    except Exception as e:
        # This catches critical failures in the setup or main loop
        job_status = 'fail'
        error_message = str(e)
        logging.critical(f"A critical error occurred, terminating job. Error: {error_message}", exc_info=True)
    finally:
        # This block will always execute
        program_end_time = datetime.now(timezone.utc)
        message = f"Job finished with status: {job_status}."
        if error_message:
            message += f" Details: {error_message}"

        if audit_table_name:
            write_audit_log(
                engine=dest_engine,
                table_name=audit_table_name,
                job_name='caselaw_etl_job',
                start_time=program_start_time,
                end_time=program_end_time,
                status=job_status,
                message=message
            )
        else:
            logging.warning("audit_log_table not configured in config.yaml. Skipping audit log.")

        logging.info("Caselaw data processing job finished.")
