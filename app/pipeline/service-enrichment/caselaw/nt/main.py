import os
from src.config_manager import ConfigManager
from src.enrichment_processor import EnrichmentProcessor

def main():
    """
    Main entry point for the case law enrichment application.
    """
    print("Starting application...")
    
    # Define paths based on the project structure, relative to the root where main.py is run
    config_path = './config/config.yaml'
    prompt_path = './config/prompt.txt'
    env_path = '.env'
    
    # Load configuration and environment variables
    # The ConfigManager loads .env automatically, making os.getenv() work
    try:
        config_manager = ConfigManager(config_path=config_path, env_path=env_path)
        config = config_manager.get_config()
    except Exception as e:
        print(f"Failed to load configuration. Aborting. Error: {e}")
        return

    # Initialize and run the processor
    try:
        processor = EnrichmentProcessor(config=config, prompt_path=prompt_path)
        processor.process_cases()
    except Exception as e:
        print(f"An unhandled error occurred during processing: {e}")

if __name__ == "__main__":
    main()

