import time
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from core.scraping import scrape_page_details_and_save, process_step
from core.database import save_record_and_get_id


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