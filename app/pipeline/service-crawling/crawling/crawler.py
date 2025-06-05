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