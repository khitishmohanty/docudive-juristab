import json
import os
import time
import re
from sqlalchemy import text
from datetime import datetime
import uuid
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException, StaleElementReferenceException
from urllib.parse import urljoin, urlparse, parse_qs

# Import the database engine creator from your utils file
# Ensure you have a utils/aws_utils.py file with a create_db_engine function
from utils.aws_utils import create_db_engine


# --- Configuration ---
MAX_RETRIES = 3 # Maximum number of times to retry a failed journey
NAVIGATION_PATH_DEPTH = int(os.getenv("NAVIGATION_PATH_DEPTH", 3)) # Duplicate checking
PAGE_LOAD_TIMEOUT = 30 # Increased timeout for slow-loading pages

def create_audit_log_entry(engine, job_name):
    """Creates a new entry in the audit_log table and returns its ID."""
    audit_id = str(uuid.uuid4())
    print(f"\nCreating audit log entry for job: {job_name} (ID: {audit_id})")
    try:
        with engine.connect() as connection:
            with connection.begin():
                query = text("""
                    INSERT INTO audit_log (id, job_name, start_time, job_status)
                    VALUES (:id, :job_name, :start_time, 'running')
                """)
                params = {"id": audit_id, "job_name": job_name, "start_time": datetime.now()}
                connection.execute(query, params)
        return audit_id
    except Exception as e:
        print(f"  - FATAL ERROR: Could not create audit log entry: {e}")
        return None

def update_audit_log_entry(engine, audit_id, final_status, message):
    """Updates the audit_log entry with the final status and duration."""
    if not audit_id:
        print("  - WARNING: No audit_id provided, cannot update audit log.")
        return

    print(f"\nUpdating audit log entry {audit_id} with status: {final_status}")
    try:
        with engine.connect() as connection:
            with connection.begin():
                start_time_query = text("SELECT start_time FROM audit_log WHERE id = :id")
                start_time_result = connection.execute(start_time_query, {"id": audit_id}).fetchone()
                
                end_time = datetime.now()
                duration = (end_time - start_time_result[0]).total_seconds() if start_time_result else -1.0

                query = text("""
                    UPDATE audit_log 
                    SET end_time = :end_time, job_status = :status, job_duration = :duration, message = :message
                    WHERE id = :id
                """)
                params = {"id": audit_id, "end_time": end_time, "status": final_status, "duration": duration, "message": message}
                connection.execute(query, params)
        print("  - Audit log entry updated successfully.")
    except Exception as e:
        print(f"  - FATAL ERROR: Could not update audit log entry {audit_id}: {e}")
        
def load_config(path):
    """Loads the crawler configuration from a JSON file."""
    print(f"Loading configuration from: {path}")
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"ERROR: Configuration file not found at '{path}'. Please ensure it exists.")
        return None
    except json.JSONDecodeError:
        print(f"ERROR: The configuration file at '{path}' is not a valid JSON.")
        return None
    
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
    
def initialize_driver():
    """Initializes a more stable, production-ready Selenium WebDriver."""
    print("Initializing Chrome WebDriver with stability options...")
    options = webdriver.ChromeOptions()
    #options.add_argument("--headless") 
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-extensions")
    options.add_argument('--ignore-certificate-errors')
    return webdriver.Chrome(options=options)

def process_pagination_loop(driver, step, db_engine, parent_url_id, navigation_path_parts, job_state, destination_table):
    """Handles pagination by repeatedly scraping and clicking 'next'."""
    next_button_xpath = step.get('next_button_xpath')
    container_xpath = step.get('target', {}).get('value')
    scraping_config = step.get('scraping_config')
    page_num = 1
    
    while True:
        print(f"\n--- Scraping Page {page_num} ---")
        
        try:
            WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
                EC.presence_of_element_located((By.XPATH, container_xpath))
            )
        except TimeoutException:
            print(f"  - ERROR: Could not find the results container on page {page_num}. Ending pagination.")
            break

        scrape_configured_data(driver, container_xpath, scraping_config, db_engine, parent_url_id, navigation_path_parts, page_num, job_state, destination_table)
        
        # Check for and click the next button
        try:
            wait = WebDriverWait(driver, 10)
            
            # Find the 'Next' button's parent list item to check if it's disabled
            next_button_li = driver.find_element(By.XPATH, f"{next_button_xpath}/ancestor::li[1]")
            if "disabled" in next_button_li.get_attribute("class"):
                print("  - Pagination complete. 'Next' button is disabled.")
                break

            next_button = wait.until(EC.element_to_be_clickable((By.XPATH, next_button_xpath)))
            
            print("  - Found active 'Next' button. Clicking...")
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_button)
            time.sleep(1)
            next_button.click()
            
            # Wait for the next page's number to become the active one.
            next_page_num = page_num + 1
            print(f"  - Waiting for Page {next_page_num} to load...")
            wait.until(EC.presence_of_element_located(
                (By.XPATH, f"//li[contains(@class, 'active') and @aria-label='page {next_page_num}']")
            ))
            page_num += 1
            
        except (NoSuchElementException, TimeoutException, StaleElementReferenceException):
            # If the button is not found, disabled, or stale, we assume pagination is complete.
            print("  - Pagination complete. No more active 'Next' buttons or page indicator not found.")
            break
            
    return True

def process_step(driver, step, db_engine, parent_url_id, navigation_path_parts, job_state, destination_table, current_page=1, journey_state=None):
    """Main dispatcher function. Passes journey_state down to relevant actions."""
    action = step.get('action')
    print(f"\nProcessing Step: {step.get('description', 'No description')}")

    if action == 'click':
        perform_click(driver, step.get('target'))
        time.sleep(3) 
        return True
    
    elif action == 'pagination_loop':
        return process_pagination_loop(driver, step, db_engine, parent_url_id, navigation_path_parts, job_state, destination_table)
    
    elif action == 'process_results':
        scraping_config = step.get('scraping_config')
        if not scraping_config:
            print("  - FATAL ERROR: 'process_results' action requires a 'scraping_config' object.")
            return False
        return scrape_configured_data(driver, step.get('target', {}).get('value'), scraping_config, db_engine, parent_url_id, navigation_path_parts, current_page, job_state, destination_table)
    else:
        print(f"  - WARNING: Unknown action type '{action}'. Skipping.")
    return True

def scrape_configured_data(driver, container_xpath, scraping_config, db_engine, parent_url_id, navigation_path_parts, page_num, job_state, destination_table):
    """
    Generic scraping function that waits for data to load and saves it to the database.
    This version uses an indexed loop to prevent StaleElementReferenceException.
    """
    try:
        wait = WebDriverWait(driver, PAGE_LOAD_TIMEOUT)
        
        print(f"  - Waiting for container to be present ({container_xpath})...")
        wait.until(EC.presence_of_element_located((By.XPATH, container_xpath)))

        row_xpath = scraping_config['row_xpath']
        print(f"  - Waiting for rows to be present ({row_xpath})...")
        wait.until(EC.presence_of_element_located((By.XPATH, row_xpath)))
        
        # Get the total count of rows to iterate by index
        num_rows = len(driver.find_elements(By.XPATH, row_xpath))
        print(f"  - Found {num_rows} result rows to process.")
        if not num_rows: 
            return True

        scraped_data = []
        # Iterate by index to avoid stale element issues
        for i in range(num_rows):
            row_data = {}
            # This loop attempts to process one row at a time.
            # If a stale element error occurs, it will be caught by the outer journey's retry mechanism.
            try:
                # Re-find all rows and select the one for the current iteration
                # This ensures we always have a fresh element reference
                row = driver.find_elements(By.XPATH, row_xpath)[i]
                
                for column_config in scraping_config['columns']:
                    col_name, col_xpath, col_type = column_config['name'], column_config['xpath'], column_config.get('type', 'text')
                    try:
                        element = row.find_element(By.XPATH, col_xpath) if col_xpath != '.' else row
                        if col_type == 'text':
                            row_data[col_name] = element.text
                        elif col_type == 'href':
                            row_data[col_name] = urljoin(driver.current_url, element.get_attribute('href'))
                    except NoSuchElementException:
                        row_data[col_name] = None
                scraped_data.append(row_data)
            except IndexError:
                # This can happen if the number of rows changes mid-scrape
                print(f"  - WARNING: Table content changed during scraping. Number of rows is now less than {num_rows}. Ending scrape for this page.")
                break # Exit the loop

        if scraped_data:
            print(f"  - Successfully processed {len(scraped_data)} rows.")
            new_records = save_scraped_data_to_db(db_engine, scraped_data, parent_url_id, navigation_path_parts, page_num, destination_table)
            job_state['records_saved'] += new_records
        return True
    except TimeoutException:
        print(f"  - INFO: No data rows found in container for page {page_num}.")
        return True
    
def perform_click(driver, target):
    """Waits for an element to be clickable and clicks it."""
    wait = WebDriverWait(driver, PAGE_LOAD_TIMEOUT)
    element_locator = (By.XPATH, target['value'])
    element = wait.until(EC.presence_of_element_located(element_locator))
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
    time.sleep(0.5) 
    element_to_click = wait.until(EC.element_to_be_clickable(element_locator))
    element_text = element_to_click.text.strip()
    print(f"  - Clicking element with XPath: {target['value']} (Text: '{element_text}')")
    element_to_click.click()

# --- Lambda Handler & Main Execution ---
def lambda_handler(event, context):
    """AWS Lambda handler function."""
    print("Lambda function invoked.")
    parent_url_id = event.get('parent_url_id')
    sitemap_file_name = event.get('sitemap_file_name')
    destination_table = event.get('destination_table')
    if not all([parent_url_id, sitemap_file_name, destination_table]):
        error_msg = 'Error: parent_url_id, sitemap_file_name, and destination_table are required.'
        print(f"FATAL ERROR: {error_msg}")
        return {'statusCode': 400, 'body': json.dumps(error_msg)}

    print(f"Starting FULL crawler run for parent_url_id: {parent_url_id} using sitemap: {sitemap_file_name}")
    run_crawler(parent_url_id, sitemap_file_name, destination_table)
    
    return {'statusCode': 200, 'body': json.dumps(f'Successfully completed crawling for {parent_url_id}')}

def run_crawler(parent_url_id, sitemap_file_name, destination_table):
    """Main function to initialize and run the crawler."""
    config_file_path = os.path.join('config', sitemap_file_name)
    config = load_config(config_file_path)
    if not config: return

    db_engine = create_db_engine()
    if not db_engine: 
        print("Database engine creation failed. Aborting crawler run.")
        return

    base_url = get_parent_url_details(db_engine, parent_url_id)
    if not base_url: return

    job_name = f"crawling-{parent_url_id}-{sitemap_file_name}"
    audit_log_id = create_audit_log_entry(db_engine, job_name)
    if not audit_log_id: return

    job_state = {'records_saved': 0}
    final_status = 'success'
    final_error_message = ""
    
    for i, journey in enumerate(config['crawler_config']['journeys']):
        retries = 0
        journey_succeeded = False
        journey_state = {} 

        while retries <= MAX_RETRIES and not journey_succeeded:
            driver = None
            try:
                if retries > 0:
                    print(f"\n--- Retrying Journey '{journey['description']}' (Attempt {retries + 1}/{MAX_RETRIES + 1}) ---")

                driver = initialize_driver()
                
                print(f"\nNavigating to base URL for journey: {base_url}")
                driver.get(base_url)

                navigation_path_parts = ["Home", journey.get('description', f'Journey-{i+1}')]
                
                print(f"\n=================================================")
                print(f"Starting Journey: {journey['description']} ({journey['journey_id']})")
                print(f"=================================================")
                
                for step in journey['steps']:
                    if not process_step(driver, step, db_engine, parent_url_id, navigation_path_parts, job_state, destination_table, journey_state=journey_state):
                        raise Exception(f"Step failed in Journey '{journey['journey_id']}'")
                
                journey_succeeded = True
                print(f"\n✅ Journey '{journey['description']}' completed successfully on attempt {retries + 1}.")

            except Exception as e:
                retries += 1
                print(f"\n!!! An exception occurred during Journey '{journey['description']}': {e}")
                print(f"  - This was attempt {retries}. Retrying if possible.")
                if retries > MAX_RETRIES:
                    print(f"  - Max retries exceeded for this journey. Marking as failed.")
                    final_status = 'failed'
                    final_error_message += f"Journey '{journey['description']}' failed after {MAX_RETRIES} retries. Last error: {e}\n"
                else:
                    time.sleep(5)
            
            finally:
                if driver:
                    print(f"Closing WebDriver for attempt {retries}.")
                    driver.quit()

    message = f"Successfully processed {job_state['records_saved']} new records."
    if final_status == 'failed':
        message = f"Job failed. Processed {job_state['records_saved']} new records. Last errors: {final_error_message}"
    update_audit_log_entry(db_engine, audit_log_id, final_status, message)
    print("\nAll journeys finished.")

if __name__ == "__main__":
    # This block is for local testing. It simulates the Lambda event.
    # --- REPLACE these values for your local test ---
    parent_url_id_for_testing = "493df9a1-e971-451e-8bf0-de5092019ef1" 
    sitemap_for_testing = "sitemap_legislation_gov_au.json"
    destination_table_for_testing = "l1_scan_legislation_gov_au"
    
    print(f"--- Running in local test mode for parent_url_id: {parent_url_id_for_testing} ---")
    
    if "your_legislation_gov_au_parent_url_id" in parent_url_id_for_testing:
        print("\nWARNING: Please replace 'your_legislation_gov_au_parent_url_id' in the script with a valid ID from your parent_urls table for testing.")
    else:
        # Create a dummy config directory for local testing
        if not os.path.exists('config'):
            os.makedirs('config')
        # This assumes the sitemap json content is available to be written
        sitemap_content = {
          "crawler_config": { "journeys": [ { "journey_id": "acts_principal_in_force_au", "description": "Scrapes all principal Acts currently in force from legislation.gov.au.", "steps": [ { "action": "click", "description": "Click the 'Acts' button in the main navigation.", "target": { "type": "xpath", "value": "//nav//a[normalize-space(.)='Acts']" } }, { "action": "click", "description": "Click the 'Principal in force' link from the dropdown.", "target": { "type": "xpath", "value": "//a[normalize-space(.)='Principal in force']" } }, { "action": "pagination_loop", "description": "Iterate through each page of the results table.", "target": { "type": "xpath", "value": "//ngx-datatable" }, "next_button_xpath": "//a[@aria-label='go to next page']", "scraping_config": { "row_xpath": ".//datatable-row-wrapper", "columns": [ { "name": "book_name", "xpath": ".//datatable-body-cell[1]//a", "type": "text" }, { "name": "book_url", "xpath": ".//datatable-body-cell[1]//a", "type": "href" }, { "name": "metadata_text", "xpath": ".//datatable-body-cell[1]/div/div[2]", "type": "text" }, { "name": "book_effective_date", "xpath": ".//datatable-body-cell[2]", "type": "text" } ] } } ] } ] }
        }
        with open(os.path.join('config', sitemap_for_testing), 'w') as f:
            json.dump(sitemap_content, f)

        run_crawler(parent_url_id_for_testing, sitemap_for_testing, destination_table_for_testing)