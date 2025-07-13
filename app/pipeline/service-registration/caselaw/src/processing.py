import logging
import os
from datetime import datetime, timezone
import pandas as pd
from sqlalchemy import text
from utils.database import create_db_engine
from utils.parsing import load_config, load_json_config, parse_parties, parse_citation

def process_caselaw_data():
    """
    Main ETL function to extract, transform, and load caselaw data.
    - Connects to source and destination databases using credentials from environment variables.
    - Reads records from multiple source tables.
    - For each record, checks if it needs processing based on its status.
    - Transforms the data by parsing party names and citation details.
    - Inserts or updates the record in the destination table.
    - Logs timing and status for each operation.
    """
    logging.info("Starting caselaw data processing job.")
    
    # --- Load Configurations ---
    config = load_config('config/config.yaml')
    if not config:
        logging.critical("Could not load config.yaml. Aborting job.")
        return

    # --- Load Credentials Securely from Environment Variables ---
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")

    if not db_user or not db_password:
        logging.critical("DB_USER and DB_PASSWORD environment variables must be set. Aborting job.")
        return
    
    logging.info("Successfully loaded database credentials from environment.")

    aus_codes = load_json_config('config/australia_config.json')
    nz_codes = load_json_config('config/new_zealand_config.json')
    all_codes = pd.concat([aus_codes, nz_codes], ignore_index=True)

    # --- Database Connections ---
    source_engine = create_db_engine(config['database']['source'], db_user, db_password)
    dest_engine = create_db_engine(config['database']['destination'], db_user, db_password)
    if not source_engine or not dest_engine:
        logging.critical("Database connection failed. Aborting job.")
        return
        
    dest_table = config['tables']['tables_to_write'][0]['table']
    filepath = config.get('filepath', None)

    program_start_time = datetime.now(timezone.utc)
    logging.info(f"Program run started at: {program_start_time.isoformat()}")

    # --- Iterate through source tables ---
    for source_info in config['tables']['tables_to_read']:
        source_table = source_info['table']
        jurisdiction_hint = source_info.get('jurisdiction')
        logging.info(f"--- Processing source table: {source_table} (Jurisdiction Hint: {jurisdiction_hint or 'None'}) ---")
        
        try:
            source_df = pd.read_sql_table(source_table, source_engine)
            logging.info(f"Read {len(source_df)} records from {source_table}.")
        except Exception as e:
            logging.error(f"Could not read from table {source_table}. Skipping. Error: {e}")
            continue

        # --- Process each record ---
        total_records = len(source_df)
        for index, row in source_df.iterrows():
            record_num = index + 1
            source_id = row['id']
            log_prefix = f"Record {record_num}/{total_records} (ID: {source_id})"
            
            logging.info(f"{log_prefix}: Starting processing.")
            
            record_start_time = datetime.now(timezone.utc)
            
            try:
                # Check if record exists and its status
                with dest_engine.connect() as connection:
                    query = text(f"SELECT status_registry FROM {dest_table} WHERE source_id = :source_id")
                    result = connection.execute(query, {'source_id': source_id}).fetchone()

                # Skip if status is 'pass'. Process 'fail', 'not started', or NULL.
                if result and result[0] == 'pass':
                    logging.info(f"{log_prefix}: Status is already 'pass'. Skipping.")
                    continue

                logging.info(f"{log_prefix}: Requires processing (Current Status: {result[0] if result else 'not started'}).")
                
                # --- Transformation ---
                primary_party, secondary_party = parse_parties(row['book_name'])
                citation_details = parse_citation(row['book_context'], all_codes, jurisdiction_hint)

                record_data = {
                    'source_id': source_id,
                    'primary_party': primary_party,
                    'secondary_party': secondary_party,
                    'neutral_citation': row['book_context'],
                    'jurisdiction_code': citation_details['jurisdiction_code'],
                    'decision_number': citation_details['decision_number'],
                    'year': citation_details['year'],
                    'decision_date': citation_details['decision_date'],
                    'members': citation_details['members'],
                    'file_path': filepath,
                    'source_url': row.get('book_url'),
                    'book_name': row['book_name'],
                    'tribunal_code': citation_details['tribunal_code'],
                    'panel_or_division': citation_details['panel_or_division'],
                    'registration_start_time': program_start_time,
                }

                # --- Determine Final Status ---
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

                record_data['status_registry'] = final_status
                record_data['registration_end_time'] = record_end_time
                record_data['duration_registry'] = record_duration

                # --- Load (Upsert Logic) ---
                with dest_engine.connect() as conn:
                    if result: # UPDATE existing record
                        logging.info(f"{log_prefix}: Updating existing record with status '{final_status}'")
                        update_cols = ", ".join([f"{key} = :{key}" for key in record_data])
                        update_query = text(f"UPDATE {dest_table} SET {update_cols} WHERE source_id = :source_id")
                        conn.execute(update_query, record_data)
                    else: # INSERT new record
                        logging.info(f"{log_prefix}: Inserting new record with status '{final_status}'")
                        insert_df = pd.DataFrame([record_data])
                        insert_df.to_sql(dest_table, conn, if_exists='append', index=False)
                    
                    conn.commit()
                logging.info(f"{log_prefix}: Successfully processed in {record_duration:.4f} seconds. Final status: {final_status}")

            except Exception as e:
                logging.error(f"{log_prefix}: Failed to process. Error: {e}", exc_info=True)
                record_end_time = datetime.now(timezone.utc)
                record_duration = (record_end_time - record_start_time).total_seconds()
                
                # More robust failure handling
                try:
                    with dest_engine.connect() as conn:
                        q_check = text(f"SELECT id FROM {dest_table} WHERE source_id = :source_id")
                        exists = conn.execute(q_check, {'source_id': source_id}).fetchone()
                        
                        if exists:
                            # If record exists, just update its status and timing to 'fail'
                            failure_update_data = {
                                'status_registry': 'fail',
                                'registration_end_time': record_end_time,
                                'duration_registry': record_duration,
                                'source_id': source_id
                            }
                            q = text(f"""UPDATE {dest_table} SET status_registry = :status_registry, 
                                                 registration_end_time = :registration_end_time, 
                                                 duration_registry = :duration_registry 
                                                 WHERE source_id = :source_id""")
                            conn.execute(q, failure_update_data)
                        else:
                            # If record is new, insert a complete record with 'fail' status
                            primary_party, secondary_party = parse_parties(row.get('book_name'))
                            failure_insert_data = {
                                'source_id': source_id,
                                'primary_party': primary_party,
                                'secondary_party': secondary_party,
                                'neutral_citation': row.get('book_context'),
                                'jurisdiction_code': None, 'decision_number': None, 'year': None,
                                'decision_date': None, 'members': None, 'file_path': filepath,
                                'source_url': row.get('book_url'), 'book_name': row.get('book_name'),
                                'tribunal_code': None, 'panel_or_division': None,
                                'status_registry': 'fail',
                                'registration_start_time': program_start_time,
                                'registration_end_time': record_end_time,
                                'duration_registry': record_duration,
                            }
                            insert_df = pd.DataFrame([failure_insert_data])
                            insert_df.to_sql(dest_table, conn, if_exists='append', index=False)
                        conn.commit()
                    logging.warning(f"{log_prefix}: Marked as 'fail' in the database due to exception.")
                except Exception as db_err:
                    logging.error(f"{log_prefix}: Could not even mark as 'fail'. DB Error: {db_err}")

    logging.info("Caselaw data processing job finished.")
