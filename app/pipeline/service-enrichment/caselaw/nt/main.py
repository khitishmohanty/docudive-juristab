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
        # --- START DEBUGGING BLOCK ---
        # Let's see what keys are actually in the 'tables' dictionary
        if 'tables' in config:
            print(f"DEBUG: Found 'tables' section. Keys are: {list(config['tables'].keys())}")
        else:
            print("DEBUG: 'tables' section not found in config.")
        # --- END DEBUGGING BLOCK ---

        # Read the audit config from the nested structure
        audit_config = config['tables']['audit_log_table'][0]
        
        # The audit logger needs the connection details for the database it writes to
        audit_db_name = audit_config['database']
        audit_db_config = config['database'][audit_db_name]
        
        logger = AuditLogger(
            db_config=audit_db_config,
            table_name=audit_config['table']
        )
        # Get the job name from the audit config
        log_id = logger.log_start(job_name=audit_config['job_name'])

    except KeyError:
         print(f"FATAL: 'audit_log_table' or 'job_name' not found in the config's 'tables' section. Aborting.")
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
