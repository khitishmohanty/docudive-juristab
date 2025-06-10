import json
import os
import time
import uuid
import re
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from pprint import pprint
from sqlalchemy import text
from urllib.parse import urlparse, parse_qs

# Import the database engine creator from your utils file
from aws_utils import create_db_engine

# --- Configuration ---
CONFIG_FILE_PATH = os.path.join('config', 'sitemap.json')
MAX_RETRIES = 3 # Maximum number of times to retry a failed journey
# --- NEW: Configurable depth for duplicate checking ---
NAVIGATION_PATH_DEPTH = int(os.getenv("NAVIGATION_PATH_DEPTH", 3))

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
    
# --- Lambda Handler: This is the entry point for AWS Lambda ---
def lambda_handler(event, context):
    """
    AWS Lambda handler function. Expects a 'parent_url_id' key.
    Resumption is now handled automatically by the crawler.
    """
    print("Lambda function invoked.")
    parent_url_id = event.get('parent_url_id')
    if not parent_url_id:
        print("FATAL ERROR: 'parent_url_id' not found in the Lambda event.")
        return {'statusCode': 400, 'body': json.dumps('Error: parent_url_id is required.')}

    print(f"Starting FULL crawler run for parent_url_id: {parent_url_id}")
    run_crawler(parent_url_id)
    
    return {'statusCode': 200, 'body': json.dumps(f'Successfully completed crawling for {parent_url_id}')}

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

def save_book_links_to_db(engine, scraped_data, parent_url_id, navigation_path_parts, page_num):
    """
    Saves a list of scraped book links to the database, checking for duplicates
    based on the parent_url_id and a configurable portion of the navigation path.
    This version uses a single transaction for the entire operation for robustness.
    """
    if not scraped_data:
        print("  - No data to save for this page.")
        return

    human_readable_path = "/".join(navigation_path_parts) + f"/Page/{page_num}"
    
    try:
        # --- NEW ROBUST TRANSACTION LOGIC ---
        # The entire check-and-insert operation is now wrapped in a single transaction
        with engine.connect() as connection:
            with connection.begin(): # Start one transaction for the whole operation
                # 1. Construct the path prefix for the duplicate check
                path_prefix_parts = navigation_path_parts[:NAVIGATION_PATH_DEPTH]
                path_prefix = "/".join(path_prefix_parts) + "%"
                print(f"  - Checking for existing records with path prefix: '{path_prefix}'")

                # 2. Get all existing book_urls within the same transaction
                existing_urls_query = text("SELECT book_url FROM book_links WHERE parent_url_id = :parent_url_id AND navigation_path LIKE :path_prefix")
                existing_urls_result = connection.execute(existing_urls_query, {"parent_url_id": parent_url_id, "path_prefix": path_prefix}).fetchall()
                existing_urls = {row[0] for row in existing_urls_result}
                print(f"  - Found {len(existing_urls)} existing records for this path context.")

                # 3. Filter out records that already exist
                records_to_insert = [item for item in scraped_data if item.get('link') not in existing_urls]

                if not records_to_insert:
                    print("  - All scraped records for this page already exist in this context. Nothing to insert.")
                    return

                print(f"  - Found {len(records_to_insert)} new records to insert.")
                
                # 4. Insert only the new records within the same transaction
                for item in records_to_insert:
                    query = text("""
                        INSERT INTO book_links (id, parent_url_id, book_name, book_number, book_url, navigation_path, date_collected, is_active)
                        VALUES (:id, :parent_url_id, :book_name, :book_number, :book_url, :navigation_path, :date_collected, :is_active)
                    """)
                    params = {
                        "id": str(uuid.uuid4()), "parent_url_id": parent_url_id,
                        "book_name": item.get('title'), "book_number": item.get('number'),
                        "book_url": item.get('link'), "navigation_path": human_readable_path,
                        "date_collected": datetime.now(), "is_active": 1
                    }
                    connection.execute(query, params)
                print(f"  - Successfully saved {len(records_to_insert)} new records with path: {human_readable_path}")

    except Exception as e:
        print(f"  - FATAL ERROR: Failed during database save operation: {e}")

def initialize_driver():
    """Initializes and returns a more stable, production-ready Selenium WebDriver."""
    print("Initializing Chrome WebDriver with stability options...")
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-application-cache")
    options.add_argument("--disk-cache-size=0")
    options.add_argument("--media-cache-size=0")
    return webdriver.Chrome(options=options)

def perform_click(driver, target, is_pagination=False):
    """Waits for an element to be clickable, clicks it, and returns the element's text."""
    try:
        wait = WebDriverWait(driver, 10 if is_pagination else 20)
        element_locator = (By.XPATH, target['value'])
        element = wait.until(EC.presence_of_element_located(element_locator))
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        time.sleep(0.5) 
        element_to_click = wait.until(EC.element_to_be_clickable(element_locator))
        element_text = element_to_click.text.strip()
        print(f"  - Clicking element with XPath: {target['value']} (Text: '{element_text}')")
        element_to_click.click()
        return element_text
    except (TimeoutException, NoSuchElementException):
        if is_pagination: return None
        print(f"  - ERROR: Click target not found or not clickable: {target['value']}")
        return None
    except WebDriverException as e:
        if "invalid session id" in str(e) or "browser has closed" in str(e):
            print(f"  - FATAL BROWSER CRASH during click: {e}")
            return "browser_crash"
        raise

def scrape_configured_data(driver, container_xpath, scraping_config, db_engine, parent_url_id, navigation_path_parts, page_num):
    """Generic scraping function that saves results directly to the database."""
    try:
        wait = WebDriverWait(driver, 30)
        print(f"  - Waiting for main results container ({container_xpath})...")
        wait.until(EC.presence_of_element_located((By.XPATH, container_xpath)))
        loading_spinner_xpath = f"{container_xpath}//div[contains(@class, 'rpl-search-results__loading')]"
        print(f"  - Waiting for loading spinner to disappear ({loading_spinner_xpath})...")
        wait.until(EC.invisibility_of_element_located((By.XPATH, loading_spinner_xpath)))
        print("  - Loading spinner gone. Content should be loaded.")
        time.sleep(1)

        row_xpath = scraping_config['row_xpath']
        rows = driver.find_elements(By.XPATH, row_xpath)
        print(f"  - Found {len(rows)} result rows to scrape using XPath: {row_xpath}")
        if not rows: return True

        scraped_data = []
        for row in rows:
            row_data = {}
            for column_config in scraping_config['columns']:
                col_name, col_xpath, col_type = column_config['name'], column_config['xpath'], column_config.get('type', 'text')
                try:
                    element = row.find_element(By.XPATH, col_xpath)
                    row_data[col_name] = element.text if col_type == 'text' else element.get_attribute('href')
                except NoSuchElementException:
                    row_data[col_name] = None
            scraped_data.append(row_data)
        
        if scraped_data:
            save_book_links_to_db(db_engine, scraped_data, parent_url_id, navigation_path_parts, page_num)
        return True
    except TimeoutException:
        print(f"  - INFO: Loading spinner did not appear or timed out. Assuming no results and continuing.")
        return True
    except WebDriverException as e:
        if "invalid session id" in str(e) or "browser has closed" in str(e):
            print(f"  - FATAL BROWSER CRASH during scraping: {e}")
            return False
        raise
    except Exception as e:
        print(f"  - An unexpected error occurred during scraping: {e}")
        return False

def process_pagination_loop(driver, step, db_engine, parent_url_id, navigation_path_parts, start_page):
    """Dedicated function to handle the pagination loop, including fast-forwarding."""
    page_counter = start_page
    
    if page_counter > 1:
        print(f"\n--- Fast-forwarding to resume from page {page_counter} ---")
        for page_num_to_click in range(2, page_counter):
            print(f"  - Clicking to page {page_num_to_click}...")
            page_locator = {"type": "xpath", "value": step['page_number_xpath_template'].format(page_num=page_num_to_click)}
            click_result = perform_click(driver, page_locator, is_pagination=True)
            if click_result == "browser_crash": return False
            if click_result is None:
                fallback_locator = {"type": "xpath", "value": step['next_button_fallback_xpath']}
                if perform_click(driver, fallback_locator, is_pagination=True) == "browser_crash": return False
            time.sleep(1)

    while True:
        print(f"\n--- Scraping results on page {page_counter} ---")
        for loop_step in step['loop_steps']:
            if not scrape_configured_data(driver, loop_step['target']['value'], loop_step['scraping_config'], db_engine, parent_url_id, navigation_path_parts, page_counter):
                print(f"--- Stopping pagination loop due to a scraping error on page {page_counter} ---")
                return False

        next_page_to_click = page_counter + 1
        page_locator = {"type": "xpath", "value": step['page_number_xpath_template'].format(page_num=next_page_to_click)}
        clicked_text = perform_click(driver, page_locator, is_pagination=True)
        
        if clicked_text == "browser_crash": return False
        if clicked_text is not None:
            page_counter += 1
            continue
        
        fallback_locator = {"type": "xpath", "value": step['next_button_fallback_xpath']}
        clicked_text = perform_click(driver, fallback_locator, is_pagination=True)
        
        if clicked_text == "browser_crash": return False
        if clicked_text is not None:
            page_counter += 1
            continue
        
        print("  - Could not find next page number or 'Next' button. Pagination complete.")
        break
    print("--- Numeric pagination loop finished ---")
    return True

def get_page_from_url(url):
    """Parses a URL to extract the 'page' query parameter."""
    try:
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        page = query_params.get('page', [1])[0]
        return int(page)
    except (ValueError, IndexError):
        return 1

def process_step(driver, step, db_engine, parent_url_id, navigation_path_parts, is_resuming, current_page=1):
    """
    Main dispatcher function. Processes a single step from the configuration.
    """
    action = step.get('action')
    print(f"\nProcessing Step: {step.get('description', action)}")

    if action == 'click':
        if is_resuming:
            print("  - In resume mode, skipping initial navigation click.")
            return True
        clicked_text = perform_click(driver, step.get('target'))
        if clicked_text == "browser_crash": return False
        return True

    elif action == 'numeric_pagination_loop':
        return process_pagination_loop(driver, step, db_engine, parent_url_id, navigation_path_parts, current_page)

    elif action == 'process_results':
        scraping_config = step.get('scraping_config')
        if not scraping_config:
            print("  - FATAL ERROR: 'process_results' action requires a 'scraping_config' object.")
            return False
        return scrape_configured_data(driver, step['target']['value'], scraping_config, db_engine, parent_url_id, navigation_path_parts, current_page)
    else:
        print(f"  - WARNING: Unknown action type '{action}'. Skipping.")
    return True

def run_crawler(parent_url_id):
    """Main function to initialize and run the crawler."""
    config = load_config(CONFIG_FILE_PATH)
    if not config: return
    db_engine = create_db_engine()
    if not db_engine: return
    base_url = get_parent_url_details(db_engine, parent_url_id)
    if not base_url: return

    for i, journey in enumerate(config['crawler_config']['journeys']):
        retries = 0
        journey_id = journey['journey_id']
        resume_from_url = None
        
        while retries < MAX_RETRIES:
            driver = None
            try:
                navigation_path_parts = ["Home"]
                for step in journey['steps']:
                    if step.get('is_breadcrumb'):
                        navigation_path_parts.append(step.get('description', ''))
                navigation_path_parts.append(journey_id)

                driver = initialize_driver()
                
                start_url_for_attempt = resume_from_url or base_url
                is_resuming = bool(resume_from_url)
                
                print(f"\n=================================================")
                print(f"Starting Journey: {journey['description']} ({journey_id})")
                print(f"Attempt #{retries + 1}. Starting from URL: {start_url_for_attempt}")
                print(f"=================================================")
                
                driver.get(start_url_for_attempt)
                
                start_page = get_page_from_url(start_url_for_attempt) if is_resuming else 1
                
                journey_succeeded = True
                
                if is_resuming:
                    pagination_step = next((s for s in journey['steps'] if s['action'] == 'numeric_pagination_loop'), None)
                    if pagination_step:
                        if not process_pagination_loop(driver, pagination_step, db_engine, parent_url_id, navigation_path_parts, start_page):
                            resume_from_url = driver.current_url
                            print(f"  - Recording resume URL for next attempt: {resume_from_url}")
                            journey_succeeded = False
                    else:
                        print("  - ERROR: In resume mode but could not find a pagination loop step in sitemap.")
                        journey_succeeded = False
                else:
                    for step in journey['steps']:
                        if not process_step(driver, step, db_engine, parent_url_id, navigation_path_parts, False, 1):
                            resume_from_url = driver.current_url
                            print(f"  - Recording resume URL for next attempt: {resume_from_url}")
                            journey_succeeded = False
                            break
                
                if journey_succeeded:
                    print(f"\n✅ Journey '{journey_id}' completed successfully.")
                    break
                else:
                    retries += 1
                    print(f"  - Incrementing retry count to {retries} for journey '{journey_id}'.")

            except WebDriverException as e:
                print(f"\n!!! A fatal WebDriverException occurred: {e}")
                if driver: resume_from_url = driver.current_url
                retries += 1
                print(f"!!! This may be a browser crash. Incrementing retry count to {retries}. !!!")
            
            finally:
                if driver:
                    print(f"Closing WebDriver for attempt #{retries} of Journey '{journey_id}'.")
                    driver.quit()
            
            if retries < MAX_RETRIES:
                print(f"  - Waiting 10 seconds before retrying journey '{journey_id}'...")
                time.sleep(10)
        
        if retries >= MAX_RETRIES:
            print(f"\n❌ FATAL: Journey '{journey_id}' failed after {MAX_RETRIES} attempts. Moving to next journey.")

    print("\nAll journeys finished.")

if __name__ == "__main__":
    parent_url_id_for_testing = "d4886db7-3a22-4ec5-9943-c71bebe7878c"
    print(f"--- Running in FULL test mode for parent_url_id: {parent_url_id_for_testing} ---")
    run_crawler(parent_url_id_for_testing)
