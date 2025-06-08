XXXX<<<<<<< HEAD
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
=======
import time
import string
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

def get_links_on_page(page_source):
    """Parses the HTML of the results page to extract legislation links."""
    soup = BeautifulSoup(page_source, 'html.parser')
    links = []
    table_body = soup.find('tbody')
    if not table_body:
        return []
    for row in table_body.find_all('tr'):
        first_cell = row.find('td')
        if first_cell and first_cell.find('a'):
            link = first_cell.find('a')['href']
            full_link = f"https://www.legislation.qld.gov.au{link}"
            links.append(full_link)
    return links

def scrape_all_links(url="https://www.legislation.qld.gov.au/browse/inforce"):
    """
    Initializes a browser to scrape all legislation links from the URL.
    This script runs in a VISIBLE browser window to bypass anti-scraping measures.
    """
    print("🚀 Starting the scraper in VISIBLE mode to ensure compatibility...")

    chrome_options = Options()
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--log-level=3")
    
    # Headless mode is intentionally disabled as this site blocks it.
    # chrome_options.add_argument("--headless")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    all_found_links = set()
    driver.get(url)

    # These are the XPaths that you confirmed work for clicking the letter buttons.
    section_xpaths = {
        "Acts": '//*[@id="main"]/div[2]/div[1]/div/div/div',
        "Subordinate Legislation": '//*[@id="main"]/div[2]/div[3]/div/div/div'
    }

    try:
        for section_name, container_xpath in section_xpaths.items():
            print("\n" + "="*50)
            print(f"🔍 Scraping Section: {section_name}")
            print("="*50)

            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.XPATH, container_xpath))
            )

            alphabet = string.ascii_uppercase
            for i, letter in enumerate(alphabet):
                xpath_index = i + 1
                
                print(f"  - Clicking on letter '{letter}'...")
                try:
                    letter_button_xpath = f"{container_xpath}/a[{xpath_index}]"
                    letter_button = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, letter_button_xpath))
                    )
                    driver.execute_script("arguments[0].click();", letter_button)

                    page_count = 1
                    while True:
                        # --- *** KEY CHANGE HERE *** ---
                        # Instead of just waiting for the table's wrapper, we now wait for the
                        # FIRST ROW of data to appear in the table. This is a much better guarantee
                        # that the data we want to scrape is actually ready.
                        print(f"    > Waiting for results to load for letter '{letter}'...")
                        WebDriverWait(driver, 20).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, "#results-table tbody tr"))
                        )

                        links_on_page = get_links_on_page(driver.page_source)
                        if links_on_page:
                            print(f"    > Page {page_count}: Found {len(links_on_page)} links.")
                            all_found_links.update(links_on_page)
                        else:
                            print(f"    > Page {page_count}: No results found on the page.")
                            break

                        try:
                            next_button = driver.find_element(By.ID, "results-table_next")
                            if "disabled" in next_button.find_element(By.XPATH, "./..").get_attribute("class"):
                                print("    > Reached the last page for this letter.")
                                break
                            else:
                                driver.execute_script("arguments[0].click();", next_button)
                                page_count += 1
                        except NoSuchElementException:
                            print("    > No 'Next' button found. Assuming single page of results.")
                            break

                except TimeoutException:
                    print(f"  - No button or results found for letter '{letter}'. Skipping.")
                    continue

    finally:
        print("\n✅ Scraping complete. Closing browser.")
        driver.quit()

    return list(all_found_links)


if __name__ == "__main__":
    final_links = scrape_all_links()
    print("\n" + "="*50)
    print(f"Total Unique Links Found: {len(final_links)}")
    print("="*50)
    if final_links:
        print("\nSample of scraped links:")
        for link in final_links[:15]:
            print(link)
>>>>>>> c11d9573f468e93a6922a33fbfc0c74b42eab167
