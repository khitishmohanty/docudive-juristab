from selenium.webdriver.support.ui import WebDriverWait
import time
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from urllib.parse import urljoin

from core.database import save_record_and_get_id, save_content_to_s3
from core.navigation import process_navigation_loop, process_and_paginate


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


