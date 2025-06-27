from selenium import webdriver

def initialize_driver():
    print("Initializing Chrome WebDriver...")
    options = webdriver.ChromeOptions()
    # options.add_argument("--headless") # Enable for production
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    return webdriver.Chrome(options=options)