import time
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException, StaleElementReferenceException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from core.scraping import perform_click, scrape_configured_data


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