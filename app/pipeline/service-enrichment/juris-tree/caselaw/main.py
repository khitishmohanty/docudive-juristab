import os
import sys
from src.config_manager import ConfigManager
from src.enrichment_processor import EnrichmentProcessor
from utils.audit_logger import AuditLogger # Import the new logger

def main():
    """
    Main entry point for the case law enrichment application, with audit logging.
    """
    print("Starting application...")
    
    # --- Configuration Loading ---
    config_path = './config/config.yaml'
    prompt_path = './config/prompt.txt'
    env_path = '.env'
    
    try:
        config_manager = ConfigManager(config_path=config_path, env_path=env_path)
        config = config_manager.get_config()
    except Exception as e:
        print(f"FATAL: Failed to load configuration. Aborting. Error: {e}")
        sys.exit(1) # Exit if config fails

    # --- Audit Logger Setup ---
    log_id = None
    try:
        # Read the audit config from the nested structure
        audit_config = config['tables']['audit_log_table'][0]
        
        # --- FIX: Find the correct database configuration by its 'name' property ---
        audit_db_name = audit_config['database']
        audit_db_config = None
        for db_key, db_properties in config['database'].items():
            if db_properties.get('name') == audit_db_name:
                audit_db_config = db_properties
                break
        
        if audit_db_config is None:
            raise KeyError(f"Database configuration for '{audit_db_name}' not found under the 'database' section.")
        # --- END FIX ---
        
        logger = AuditLogger(
            db_config=audit_db_config,
            table_name=audit_config['table']
        )
        # Get the job name from the audit config
        log_id = logger.log_start(job_name=audit_config['job_name'])

    except KeyError as e:
         print(f"FATAL: A required key was not found in the configuration. Please check config.yaml. Details: {e}")
         sys.exit(1)
    except Exception as e:
        # If logging fails to start, print error and exit.
        print(f"FATAL: Could not initialize and start audit logger. Aborting. Error: {e}")
        sys.exit(1)

    # --- Main Processing Logic ---
    try:
        processor = EnrichmentProcessor(config=config, prompt_path=prompt_path)
        processor.process_cases()
        
        # If we reach here, the job is considered complete
        logger.log_end(log_id, status='completed', message='Job finished successfully.')

    except Exception as e:
        print(f"An unhandled error occurred during processing: {e}")
        # Log the failure
        error_message = f"Job failed due to an unhandled exception: {str(e)}"
        logger.log_end(log_id, status='failed', message=error_message)
        sys.exit(1) # Exit with an error code

if __name__ == "__main__":
    main()

