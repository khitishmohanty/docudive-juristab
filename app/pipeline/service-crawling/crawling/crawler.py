import json
import os
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# --- Configuration ---
CONFIG_FILE_PATH = os.path.join('config', 'sitemap.json')

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

def initialize_driver():
    """Initializes and returns the Selenium WebDriver."""
    print("Initializing Chrome WebDriver...")
    options = webdriver.ChromeOptions()
    driver = webdriver.Chrome(options=options)
    driver.implicitly_wait(5)
    return driver

def perform_click(driver, target):
    """
    Waits for an element to be clickable and then clicks it.
    This version includes scrolling the element into view first.
    """
    try:
        wait = WebDriverWait(driver, 10) # Reduced wait time for faster checks
        element_locator = (By.XPATH, target['value'])
        element = wait.until(EC.presence_of_element_located(element_locator))

        # Scroll the element into view before clicking
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        time.sleep(0.5) 

        element = wait.until(EC.element_to_be_clickable(element_locator))

        print(f"  - Clicking element with XPath: {target['value']}")
        element.click()
        return True
    except TimeoutException:
        print(f"  - ERROR: Timed out waiting for element to be clickable: {target['value']}")
        return False
    except NoSuchElementException:
        print(f"  - ERROR: Could not find element with XPath: {target['value']}")
        return False

def perform_input(driver, target, text):
    """Waits for an input element and types text into it."""
    try:
        wait = WebDriverWait(driver, 20)
        element_locator = (By.XPATH, target['value'])
        element = wait.until(EC.visibility_of_element_located(element_locator))
        print(f"  - Inputting text '{text}' into element with XPath: {target['value']}")
        element.clear()
        element.send_keys(text)
        return True
    except TimeoutException:
        print(f"  - ERROR: Timed out waiting for input element to be visible: {target['value']}")
        return False
    except NoSuchElementException:
        print(f"  - ERROR: Could not find input element with XPath: {target['value']}")
        return False

def process_step(driver, step):
    """Processes a single step from the configuration."""
    action = step.get('action')
    target = step.get('target')
    description = step.get('description', 'No description')
    
    print(f"\nProcessing Step: {description}")
    
    if action == 'navigate':
        print(f"  - Navigating to URL: {target}")
        driver.get(target)
    
    elif action == 'click':
        if not perform_click(driver, target):
            return False
            
    elif action == 'input':
        text_to_input = step.get('text', '')
        if not perform_input(driver, target, text_to_input):
            return False

    elif action == 'numeric_pagination_loop':
        loop_steps = step.get('loop_steps', [])
        next_button_fallback_xpath = step.get('next_button_fallback_xpath')
        page_number_xpath_template = step.get('page_number_xpath_template')

        current_page = 1
        while True:
            # 1. Process results on the current page
            print(f"\n--- Scraping results on page {current_page} ---")
            for loop_step in loop_steps:
                if not process_step(driver, loop_step):
                    print(f"--- Stopping pagination loop due to an error on page {current_page} ---")
                    return False

            # 2. Try to find and click the next sequential page number
            next_page_to_click = current_page + 1
            page_locator_value = page_number_xpath_template.format(page_num=next_page_to_click)
            page_locator = {"type": "xpath", "value": page_locator_value}
            
            print(f"  - Attempting to click page number {next_page_to_click}...")
            if perform_click(driver, page_locator):
                current_page += 1
                time.sleep(step.get('post_action_wait_seconds', 3))
                continue # Successfully clicked a page number, continue to next loop iteration
            
            # 3. If numeric click failed, try the fallback "Next" button
            print(f"  - Page {next_page_to_click} not found. Trying fallback 'Next' button.")
            if next_button_fallback_xpath:
                fallback_locator = {"type": "xpath", "value": next_button_fallback_xpath}
                if perform_click(driver, fallback_locator):
                    current_page += 1 # Assume we advanced one page
                    time.sleep(step.get('post_action_wait_seconds', 3))
                    continue # Successfully clicked 'Next', continue to next loop iteration
            
            # 4. If all attempts to advance fail, end the loop
            print("  - Could not find next page number or 'Next' button. Pagination complete.")
            break

        print("--- Numeric pagination loop finished ---")

    elif action == 'process_results':
        print(f"  - ACTION: Process results. Target container: {target.get('value')}")
        print("  - (Placeholder) Imagining we are scraping data...")
        
    else:
        print(f"  - WARNING: Unknown action type '{action}'. Skipping.")
        
    return True

def run_crawler():
    """Main function to initialize and run the crawler."""
    config = load_config(CONFIG_FILE_PATH)
    if not config:
        return

    driver = initialize_driver()
    
    try:
        journeys = config['crawler_config']['journeys']
        print(f"Found {len(journeys)} journeys to execute.")
        
        for i, journey in enumerate(journeys):
            print(f"\n=================================================")
            print(f"Starting Journey #{i+1}: {journey['description']}")
            print(f"=================================================")
            
            for step in journey['steps']:
                if not process_step(driver, step):
                    print(f"\n!!! Journey '{journey['journey_id']}' failed. Moving to next journey. !!!")
                    break
            
            print(f"\nJourney '{journey['journey_id']}' completed.")

    finally:
        print("\nAll journeys finished. Closing WebDriver in 10 seconds.")
        time.sleep(10)
        driver.quit()

if __name__ == "__main__":
    run_crawler()
