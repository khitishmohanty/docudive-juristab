from selenium.webdriver.support.ui import WebDriverWait
import time
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from urllib.parse import urljoin

from core.database import save_scraped_data_to_db


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