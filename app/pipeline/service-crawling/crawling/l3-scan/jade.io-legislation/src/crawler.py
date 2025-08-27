import logging
from utils.config_loader import load_config
from utils.db_utils import get_urls_to_crawl, update_scan_status
from utils.scraper import scrape_content, upload_to_s3

def run_crawler():
    """Main function to run the web crawler."""
    config = load_config()

    s3_config = config.get('s3', {})
    s3_bucket = s3_config.get('bucket_name')
    output_filename = s3_config.get('output_filename', 'full_book_content.html')
    
    if not s3_bucket:
        logging.error("S3 bucket name not found in configuration. Exiting.")
        return

    for table_info in config.get('tables_to_crawl', []):
        if table_info.get('enabled'):
            table_name = table_info.get('table_name')
            subfolder_name = table_info.get('subfolder_name')
            # Get jurisdiction from config for logging
            jurisdiction = table_info.get('jurisdiction', 'Unknown')
            
            if not all([table_name, subfolder_name]):
                logging.warning(f"Skipping incomplete table configuration: {table_info}")
                continue

            logging.info(f"--- Processing Jurisdiction: {jurisdiction} (Table: {table_name}) ---")
            
            records_to_crawl = get_urls_to_crawl(table_name)
            
            if not records_to_crawl:
                logging.info(f"No new records to crawl for {jurisdiction}.")
                continue

            for record in records_to_crawl:
                record_id = record.get('id')
                url = record.get('book_url')
                # Get book_name from the record for logging
                book_name = record.get('book_name', 'Unknown Title')
                
                if not url or not record_id:
                    logging.warning(f"Skipping record with missing ID or URL: {record}")
                    continue

                # More detailed logging for each record
                logging.info(f"STARTING scrape for '{book_name}' (ID: {record_id})")
                
                content = scrape_content(url)
                
                if content:
                    s3_key = f"{subfolder_name}/{record_id}/{output_filename}"
                    success = upload_to_s3(content, s3_bucket, s3_key)
                    
                    if success:
                        update_scan_status(table_name, record_id, 'pass')
                        logging.info(f"SUCCESS scraping '{book_name}' (ID: {record_id})")
                    else:
                        update_scan_status(table_name, record_id, 'fail')
                        logging.error(f"FAILED to upload for '{book_name}' (ID: {record_id})")
                else:
                    update_scan_status(table_name, record_id, 'fail')
                    logging.error(f"FAILED to scrape content for '{book_name}' (ID: {record_id})")
