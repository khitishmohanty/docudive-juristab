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
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
from urllib.parse import urljoin
import boto3

# Import the database engine creator from your utils file
# Ensure you have a utils/aws_utils.py file with a create_db_engine function
from utils.aws_utils import create_db_engine

# --- Configuration ---
MAX_RETRIES = 3
NAVIGATION_PATH_DEPTH = int(os.getenv("NAVIGATION_PATH_DEPTH", 3))
S3_BUCKET = "legal-store" # As specified in the request

# --- AWS Clients ---
s3_client = boto3.client('s3')

# --- Database & Audit Functions (from original script) ---
def create_audit_log_entry(engine, job_name):
    audit_id = str(uuid.uuid4())
    print(f"\nCreating audit log entry for job: {job_name} (ID: {audit_id})")
    try:
        with engine.connect() as connection:
            with connection.begin():
                query = text("INSERT INTO audit_log (id, job_name, start_time, job_status) VALUES (:id, :job_name, :start_time, 'running')")
                params = {"id": audit_id, "job_name": job_name, "start_time": datetime.now()}
                connection.execute(query, params)
        return audit_id
    except Exception as e:
        print(f"  - FATAL ERROR: Could not create audit log entry: {e}")
        return None

def update_audit_log_entry(engine, audit_id, final_status, message):
    if not audit_id: return
    print(f"\nUpdating audit log entry {audit_id} with status: {final_status}")
    try:
        with engine.connect() as connection:
            with connection.begin():
                start_time_query = text("SELECT start_time FROM audit_log WHERE id = :id")
                start_time_result = connection.execute(start_time_query, {"id": audit_id}).fetchone()
                end_time = datetime.now()
                duration = (end_time - start_time_result[0]).total_seconds() if start_time_result else -1.0
                query = text("UPDATE audit_log SET end_time = :end_time, job_status = :status, job_duration = :duration, message = :message WHERE id = :id")
                params = {"id": audit_id, "end_time": end_time, "status": final_status, "duration": duration, "message": message}
                connection.execute(query, params)
    except Exception as e:
        print(f"  - FATAL ERROR: Could not update audit log entry {audit_id}: {e}")

def load_config(path):
    print(f"Loading configuration from: {path}")
    try:
        with open(path, 'r') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"ERROR: Could not load or parse config file '{path}': {e}")
        return None

def get_parent_url_details(engine, parent_url_id):
    print(f"\nFetching base_url for parent_url_id: {parent_url_id}...")
    try:
        with engine.connect() as connection:
            query = text("SELECT base_url FROM parent_urls WHERE id = :id")
            result = connection.execute(query, {"id": parent_url_id}).fetchone()
            if result: return result[0]
            print(f"  - FATAL ERROR: No record found for id='{parent_url_id}'")
    except Exception as e:
        print(f"  - FATAL ERROR: Could not query database: {e}")
    return None

# --- New S3 and Data Saving Logic ---
def save_content_to_s3(content, bucket, key):
    """Saves string content to a file in S3."""
    try:
        s3_client.put_object(Bucket=bucket, Key=key, Body=content, ContentType='text/html')
        print(f"    - Successfully saved content to S3: s3://{bucket}/{key}")
    except Exception as e:
        print(f"    - ERROR: Failed to save to S3 bucket '{bucket}': {e}")
        raise

def save_record_and_get_id(engine, data, parent_url_id, navigation_path, table):
    """
    Checks if a record with the same book_name and book_context exists.
    If not, saves a new record and returns the new UUID. If it exists, returns None.
    """
    book_name_to_check = data.get('book_name')
    book_context_to_check = data.get('book_context')

    # A book name is required to check for duplicates.
    if not book_name_to_check:
        print("    - WARNING: Book name is missing, cannot check for duplicates or insert.")
        return None

    try:
        with engine.connect() as connection:
            with connection.begin():
                # Step 1: Check for an existing record with the same name and context.
                find_query = text(f"SELECT id FROM {table} WHERE book_name = :book_name AND book_context = :book_context")
                params_find = {"book_name": book_name_to_check, "book_context": book_context_to_check}
                existing_record = connection.execute(find_query, params_find).fetchone()

                if existing_record:
                    # Step 2a: If the record exists, print a message and return None to skip processing.
                    print(f"  - Record for '{book_name_to_check}' already exists. Skipping.")
                    return None
                else:
                    # Step 2b: If the record does not exist, proceed with inserting a new one.
                    record_id = str(uuid.uuid4())
                    print(f"  - Inserting new record for '{book_name_to_check}' into table '{table}'")

                    insert_query = text(f"""
                        INSERT INTO {table} (id, parent_url_id, book_name, book_context, book_url, navigation_path, date_collected, is_active)
                        VALUES (:id, :parent_url_id, :book_name, :book_context, :book_url, :navigation_path, :date_collected, 1)
                    """)
                    params_insert = {
                        "id": record_id,
                        "parent_url_id": parent_url_id,
                        "book_name": book_name_to_check,
                        "book_context": book_context_to_check,
                        "book_url": data.get('book_url'),
                        "navigation_path": navigation_path,
                        "date_collected": datetime.now()
                    }
                    connection.execute(insert_query, params_insert)
                    
                    print(f"    - DB insert successful. New record ID: {record_id}")
                    return record_id

    except Exception as e:
        print(f"    - FATAL ERROR during database check or insert: {e}")
        raise

def scrape_page_details_and_save(driver, config, db_engine, parent_url_id, nav_path_parts, job_state):
    """Scrapes details for each result on the current page."""
    wait = WebDriverWait(driver, 20)
    try:
        rows = wait.until(EC.presence_of_all_elements_located((By.XPATH, config['row_xpath'])))
        print(f"  - Found {len(rows)} result rows to process.")
    except TimeoutException:
        print("  - No result rows found on this page.")
        return True

    records_processed_this_page = 0
    for i, row in enumerate(rows):
        try:
            # 1. Extract basic data from the row
            row_data = {}
            for col in config['columns']:
                try:
                    element = row.find_element(By.XPATH, col['xpath'])
                    row_data[col['name']] = element.get_attribute('href') if col['type'] == 'href' else element.text
                except NoSuchElementException:
                    row_data[col['name']] = None
            
            # 2. Save to DB to get ID
            human_readable_path = "/".join(nav_path_parts)
            record_id = save_record_and_get_id(db_engine, row_data, parent_url_id, human_readable_path, config['destination_table'])
            if not record_id: continue

            # 3. Process content tabs and save to S3
            jurisdiction_folder = nav_path_parts[2].lower().replace(" ", "_")
            base_s3_path = f"case-laws/{jurisdiction_folder}/{record_id}"

            for tab in config['content_tabs']['tabs']:
                try:
                    # STEP 1: Find and click the tab to make its content visible
                    print(f"    - Locating tab: '{tab['name']}'")
                    tab_button = row.find_element(By.XPATH, tab['click_xpath'])
                    
                    print(f"    - Found tab, clicking now...")
                    driver.execute_script("arguments[0].click();", tab_button)
                    
                    # STEP 2: Wait for the tab content to load dynamically
                    # INCREASED WAIT TIME to give AJAX content more time to appear.
                    time.sleep(3) 

                    # STEP 3: Find the content container for the now-active tab
                    # This is the likely point of failure if the wait is too short or the XPath is wrong.
                    content_container = row.find_element(By.XPATH, tab['content_xpath'])
                    
                    # STEP 4: Get the Outer HTML of the content, print it, and save it
                    content_html = content_container.get_attribute('outerHTML')
                    
                    # Print the Outer HTML of the content as requested
                    #print("\n    -----------------------------------------")
                    #print(f"    Outer HTML for '{tab['name']}' content:")
                    #print(content_html)
                    #print("    -----------------------------------------\n")

                    s3_key = f"{base_s3_path}/{tab['name'].lower()}.html"
                    save_content_to_s3(content_html, config['s3_bucket'], s3_key)
                
                except NoSuchElementException:
                    # If the tab button OR content isn't found, print a warning and the HTML of the entire row for debugging.
                    print(f"    - WARNING: Could not find tab button or content for '{tab['name']}' in row {i+1}. Skipping.")
                    print("    - DEBUG: Printing the outer HTML of the entire row to help find the correct XPath.")
                    try:
                        # This will show you the exact HTML Selenium is seeing for the row.
                        row_html = row.get_attribute('outerHTML')
                        print(row_html)
                    except Exception as e:
                        print(f"    - DEBUG: Could not get row HTML. It might be stale. Error: {e}")

                except Exception as e:
                    print(f"    - ERROR: An unexpected error occurred while processing tab '{tab['name']}': {e}")


            records_processed_this_page += 1
            job_state['records_saved'] += 1

        except StaleElementReferenceException:
            print(f"  - ERROR: Stale element reference on row {i+1}. Re-finding rows and retrying this page.")
            return "retry_page"
        except Exception as e:
            print(f"  - FATAL ERROR processing row {i+1}: {e}")
            raise

    print(f"  - Finished processing {records_processed_this_page} records for this page.")
    return True

# --- New Action Handlers ---

def process_and_paginate(driver, step_config, db_engine, parent_url_id, nav_path_parts, job_state):
    """Handles scraping multiple pages of results."""
    scraping_config = step_config['scraping_config']
    page_num = 1
    while True:
        print(f"\n--- Processing Page {page_num} ---")
        page_nav_path = nav_path_parts + [f"Page-{page_num}"]
        
        result = scrape_page_details_and_save(driver, scraping_config, db_engine, parent_url_id, page_nav_path, job_state)
        if result == "retry_page":
            print("  - Retrying current page due to stale elements...")
            time.sleep(2)
            continue # Retry the while loop for the same page

        # Find and click next page button
        try:
            next_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, step_config['next_page_xpath']))
            )
            print("  - Found 'Next Page' button. Clicking...")
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_button)
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", next_button)
            page_num += 1
            time.sleep(2) # Wait for next page to load
        except TimeoutException:
            print("  - 'Next Page' button not found or disabled. Ending pagination for this section.")
            break # Exit the while loop
    return True

def process_navigation_loop(driver, step, db_engine, parent_url_id, nav_path_parts, job_state, journey_state):
    """Handles looping over a set of navigation elements (e.g., jurisdiction buttons)."""
    target_xpath = step.get('target_xpath')
    wait = WebDriverWait(driver, 30)

    print(f"  - Directly attempting to find navigation links ({target_xpath})...")
    time.sleep(2)
    
    nav_links = driver.find_elements(By.XPATH, target_xpath)
    num_links = len(nav_links)

    if num_links == 0:
        print(f"  - FATAL ERROR: Found 0 navigation links. The XPath did not match any elements.")
        # Included debugging from original script
        try:
            page_source = driver.page_source
            print("  - Page Source at time of failure:")
            print(page_source)
            driver.save_screenshot('/tmp/jade_failure_screenshot.png')
            print("  - Screenshot saved to /tmp/jade_failure_screenshot.png")
        except Exception as e:
            print(f"  - Could not get page source or screenshot: {e}")
        return False

    print(f"  - Found {num_links} navigation links to process.")

    start_index = journey_state.get('last_completed_index', -1) + 1
    if start_index > 0:
        print(f"  - Resuming navigation loop from index {start_index}.")

    for i in range(start_index, num_links):
        try:
            # Re-finding elements in each iteration is crucial to avoid stale elements
            current_nav_links = driver.find_elements(By.XPATH, target_xpath)
            link_to_click = current_nav_links[i]
            link_text = link_to_click.text.strip()
            print(f"\n--- Processing Navigation Link {i+1}/{num_links} (Text: '{link_text}') ---")
            
            print("  - Scrolling to and clicking button using JavaScript...")
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", link_to_click)
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", link_to_click)
            
            # --- CORRECTED LOGIC FOR SAME-PAGE NAVIGATION ---
            print("  - Waiting for search results page to load...")
            # Wait for a unique element of the results page, like the breadcrumb
            wait.until(EC.presence_of_element_located((By.XPATH, "//p[@class='breadcrumb' and contains(text(), 'Search results')]")))
            print("  - Search results page loaded successfully.")
            time.sleep(2) # Allow dynamic content to load

            item_path_parts = nav_path_parts + [link_text]
            for loop_step in step['loop_steps']:
                if not process_step(driver, loop_step, db_engine, parent_url_id, item_path_parts, job_state, journey_state):
                    raise Exception(f"Step failed for navigation item '{link_text}'")
            
            # --- CORRECTED LOGIC TO RETURN TO HOME PAGE ---
            print(f"  - Navigating back to the home page for the next jurisdiction...")
            driver.back()
            # Wait for a key element on the home page to ensure it's reloaded
            wait.until(EC.presence_of_element_located((By.XPATH, "//h3[normalize-space()='Case Law']")))
            time.sleep(1)

            journey_state['last_completed_index'] = i
            print(f"  - Successfully completed processing for '{link_text}'. State updated.")

        except Exception as e:
            print(f"  - An error occurred processing navigation index {i}. Last successful index was {journey_state.get('last_completed_index', -1)}.")
            raise e
            
    return True

# --- Core Crawler Logic ---
def initialize_driver():
    print("Initializing Chrome WebDriver...")
    options = webdriver.ChromeOptions()
    # options.add_argument("--headless") # Enable for production
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    return webdriver.Chrome(options=options)

def process_step(driver, step, db_engine, parent_url_id, nav_path_parts, job_state, journey_state):
    """Main dispatcher function for processing a single step."""
    action = step.get('action')
    print(f"\nProcessing Step: {step.get('description', 'No description')}")

    if action == 'click':
        wait = WebDriverWait(driver, 10) # Shorter wait for potentially optional elements
        try:
            element = wait.until(EC.element_to_be_clickable((By.XPATH, step['target']['value'])))
            print(f"  - Clicking element: {step['description']}")
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", element)
            time.sleep(1) # Wait for action to complete
        except TimeoutException:
            print(f"  - INFO: Element for '{step['description']}' not found or not clickable. Might be optional. Continuing.")
        return True
    elif action == 'pause':
        duration = step.get('duration', 1)
        print(f"  - Pausing for {duration} second(s)...")
        time.sleep(duration)
        return True
    elif action == 'navigation_loop':
        return process_navigation_loop(driver, step, db_engine, parent_url_id, nav_path_parts, job_state, journey_state)
    elif action == 'process_and_paginate':
        return process_and_paginate(driver, step, db_engine, parent_url_id, nav_path_parts, job_state)
    else:
        print(f"  - WARNING: Unknown action type '{action}'. Skipping.")
        return True

def run_crawler(parent_url_id, sitemap_file_name, destination_table=None): # destination_table is now in sitemap
    config_file_path = os.path.join('config', sitemap_file_name)
    config = load_config(config_file_path)
    if not config: return

    db_engine = create_db_engine()
    if not db_engine: return

    base_url = get_parent_url_details(db_engine, parent_url_id)
    # FIX: Corrected the typo from base__url to base_url
    if not base_url: return

    job_name = f"crawling-jade-{parent_url_id}"
    audit_log_id = create_audit_log_entry(db_engine, job_name)
    if not audit_log_id: return

    job_state = {'records_saved': 0}
    final_status, final_error_message = 'success', ""
    
    for i, journey in enumerate(config['crawler_config']['journeys']):
        retries = 0
        journey_succeeded = False
        journey_state = {'last_completed_index': -1} # For resuming loops

        while retries <= MAX_RETRIES and not journey_succeeded:
            driver = None
            try:
                if retries > 0: print(f"\n--- Retrying Journey '{journey['description']}' (Attempt {retries + 1}) ---")
                
                driver = initialize_driver()
                print(f"Navigating to base URL: {base_url}")
                driver.get(base_url)

                nav_path_parts = ["Home", journey.get('description', f'Journey-{i+1}')]
                
                print(f"\n=================================================\nStarting Journey: {journey['description']}\n=================================================")
                
                for step in journey['steps']:
                    if not process_step(driver, step, db_engine, parent_url_id, nav_path_parts, job_state, journey_state):
                        raise Exception(f"Step failed in Journey '{journey['journey_id']}'")
                
                journey_succeeded = True
                print(f"\n✅ Journey '{journey['description']}' completed successfully.")

            except Exception as e:
                retries += 1
                print(f"\n!!! EXCEPTION during Journey '{journey['description']}': {e}")
                if retries > MAX_RETRIES:
                    final_status = 'failed'
                    final_error_message += f"Journey '{journey['description']}' failed after {MAX_RETRIES} retries. Last error: {e}\n"
                else:
                    time.sleep(5)
            
            finally:
                if driver: driver.quit()

    message = f"Successfully processed {job_state['records_saved']} new records."
    if final_status == 'failed':
        message = f"Job failed. Processed {job_state['records_saved']} records. Errors: {final_error_message}"
    update_audit_log_entry(db_engine, audit_log_id, final_status, message)
    print("\nAll journeys finished.")

# --- Lambda Handler & Local Test ---
def lambda_handler(event, context):
    parent_url_id = event.get('parent_url_id')
    sitemap_file_name = event.get('sitemap_file_name')
    if not all([parent_url_id, sitemap_file_name]):
        return {'statusCode': 400, 'body': json.dumps('Error: parent_url_id and sitemap_file_name are required.')}
    
    run_crawler(parent_url_id, sitemap_file_name)
    return {'statusCode': 200, 'body': json.dumps(f'Successfully completed crawling for {parent_url_id}')}

if __name__ == "__main__":
    # The parent_url_id for 'https://jade.io/t/home'
    parent_url_id_for_testing = "dde888c6-7b5a-4731-b627-502f9404f910" # <--- IMPORTANT: REPLACE with the actual ID from your DB
    sitemap_for_testing = "sitemap_jade_io.json"
    
    print(f"--- Running in local test mode for parent_url_id: {parent_url_id_for_testing} ---")
    
    if "your_jade_io_parent_url_id_here" in parent_url_id_for_testing:
        print("\nWARNING: Please replace 'your_jade_io_parent_url_id_here' with a valid ID from your database.")
    else:
        run_crawler(parent_url_id_for_testing, sitemap_for_testing)