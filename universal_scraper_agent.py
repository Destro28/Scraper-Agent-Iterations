import os
import time
import asyncio
import logging
import json
import re
import requests
from collections import deque
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, ElementClickInterceptedException

# -----------------------------
# CONFIGURATION
# -----------------------------
START_URL = "https://www.govinfo.gov/app/collection/cfr/"
DOWNLOAD_DIR = "./pdfs"
MAX_PAGES = 100        # Safety limit on pages to visit
MAX_PDFS = 500         # Safety limit on pdfs to download
LOG_LEVEL = logging.INFO
LLM_API_URL = "http://127.0.0.1:8000/generate_selectors" # The URL for your local model server

# Ensure download directory exists
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# -----------------------------
# LOGGER SETUP
# -----------------------------
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=LOG_LEVEL
)
logger = logging.getLogger(__name__)

# -----------------------------
# SELENIUM SETUP
# -----------------------------
options = Options()
# Running headless is more efficient for scraping
options.add_argument("--headless")
options.add_argument("--disable-gpu")
options.add_argument("--window-size=1920,1080") # Specify window size for consistency
prefs = {
    "download.default_directory": os.path.abspath(DOWNLOAD_DIR),
    "download.prompt_for_download": False,
    "plugins.always_open_pdf_externally": True # Important for downloading PDFs instead of viewing them
}
options.add_experimental_option("prefs", prefs)
# Use a try-except block for robust driver initialization
try:
    driver = webdriver.Chrome(options=options)
except Exception as e:
    logger.error(f"Failed to initialize Selenium WebDriver: {e}")
    exit()

# -----------------------------
# LLM API COMMUNICATION
# -----------------------------
def call_llm_api(html_snippet):
    """
    (Synchronous) Calls the local LLM API to get selectors.
    Sends the HTML and expects a JSON response containing the model's raw text.
    """
    try:
        # Make a POST request to the running FastAPI server
        response = requests.post(LLM_API_URL, json={"html": html_snippet}, timeout=120)
        response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
        # Extract the generated text from the JSON response
        return response.json().get("result_text", "")
    except requests.exceptions.RequestException as e:
        logger.error(f"Could not connect to the LLM API at {LLM_API_URL}. Is it running? Error: {e}")
        return ""

async def detect_selectors(html_snippet):
    """
    (Asynchronous) Gets selectors by calling the LLM API in an executor.
    This prevents the synchronous network request from blocking the main async loop.
    """
    loop = asyncio.get_running_loop()
    
    # Run the synchronous network request in a separate thread
    result_str = await loop.run_in_executor(
        None, call_llm_api, html_snippet
    )
    
    if not result_str:
        return []

    # Robustly parse the JSON from the model's raw text output
    try:
        # Use regex to find the first valid JSON object or array in the response string
        json_match = re.search(r'\{[\s\S]*\}|\[[\s\S]*\]', result_str)
        if not json_match:
            logger.warning(f"No JSON object or array found in API response: {result_str}")
            return []

        json_str = json_match.group(0)
        data = json.loads(json_str)

        # The model might return an object like {"selectors": [...]} or just the list [...]
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, list):
                    logger.info(f"Successfully parsed {len(value)} selectors from API.")
                    return value
            logger.warning(f"Parsed a JSON object from API, but no list was found.")
            return []
        elif isinstance(data, list):
            logger.info(f"Successfully parsed a direct list of {len(data)} selectors from API.")
            return data
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode JSON from API response. Error: {e}\nRaw response: {result_str}")
    except Exception as e:
        logger.error(f"An unexpected error occurred while parsing API response: {e}")

    return []

# -----------------------------
# SELENIUM ACTION & DOWNLOAD
# -----------------------------
def click_and_download(selectors, page_url):
    """
    Given a list of CSS selectors from the LLM, clicks each element
    and then scours the page for any new PDF links to download.
    """
    logger.info(f"Attempting to click {len(selectors)} selectors on {page_url}")
    for selector in selectors:
        try:
            element = driver.find_element(By.CSS_SELECTOR, selector)
            # Scroll element into view to ensure it's clickable
            driver.execute_script("arguments[0].scrollIntoView(true);", element)
            time.sleep(0.5) # Brief pause to allow UI to settle
            element.click()
            logger.info(f"Successfully clicked selector: {selector}")
            # Wait for potential new content to load after click
            time.sleep(2)
        except NoSuchElementException:
            logger.warning(f"Selector not found: {selector}")
        except ElementClickInterceptedException:
            logger.warning(f"Could not click selector (another element is in the way): {selector}")
        except Exception as e:
            logger.error(f"An error occurred clicking selector {selector}: {e}")

    # After clicking, find all visible PDF links on the page
    pdf_links = set()
    try:
        # This selector finds any `<a>` tag whose `href` attribute ends with '.pdf' (case-insensitive)
        pdf_elements = driver.find_elements(By.CSS_SELECTOR, "a[href$='.pdf' i]")
        for element in pdf_elements:
            href = element.get_attribute('href')
            if href:
                pdf_links.add(href)
    except Exception as e:
        logger.error(f"Error finding PDF links on page: {e}")
    
    return pdf_links

# -----------------------------
# MAIN SCRAPER LOOP
# -----------------------------
async def main():
    """
    Main asynchronous loop to manage the crawling process.
    """
    visited_pages = set()
    downloaded_pdfs = set()
    queue = deque([START_URL])

    while queue and len(visited_pages) < MAX_PAGES and len(downloaded_pdfs) < MAX_PDFS:
        url = queue.popleft()
        if url in visited_pages:
            continue
        
        try:
            logger.info(f"Visiting: {url} (Queue: {len(queue)})")
            driver.get(url)
            visited_pages.add(url)
            # Wait for the page to load its initial content
            time.sleep(2)
            
            # Truncate HTML to respect model's context window and reduce payload size
            html = driver.page_source[:8000]

            # 1. Get intelligent selectors from the local LLM API
            selectors = await detect_selectors(html)
            
            # 2. Use Selenium to click those selectors and find any revealed PDFs
            new_pdfs = click_and_download(selectors, url)

            # 3. Download the newly found PDFs
            for pdf_url in new_pdfs:
                if pdf_url not in downloaded_pdfs:
                    logger.info(f"Downloading PDF: {pdf_url}")
                    # Use requests for reliable file downloading
                    try:
                        pdf_response = requests.get(pdf_url, timeout=30)
                        pdf_response.raise_for_status()
                        file_name = pdf_url.split('/')[-1]
                        # Ensure filename is valid
                        if not file_name.lower().endswith('.pdf'):
                            file_name += ".pdf"
                        file_path = os.path.join(DOWNLOAD_DIR, file_name)
                        with open(file_path, 'wb') as f:
                            f.write(pdf_response.content)
                        downloaded_pdfs.add(pdf_url)
                    except requests.exceptions.RequestException as e:
                        logger.error(f"Failed to download {pdf_url}: {e}")

            # 4. Discover new URLs on the page to crawl next
            link_elements = driver.find_elements(By.TAG_NAME, 'a')
            for link in link_elements:
                href = link.get_attribute('href')
                if href and href.startswith('http') and not href.lower().endswith(('.pdf', '.zip', '.jpg', '.png')):
                    if href not in visited_pages and href not in queue:
                        queue.append(href)

        except Exception as e:
            logger.error(f"A critical error occurred while processing {url}: {e}")

    # Final summary
    logger.info("="*50)
    logger.info(f"Scraping complete.")
    logger.info(f"Pages visited: {len(visited_pages)}")
    logger.info(f"PDFs downloaded: {len(downloaded_pdfs)}")
    logger.info("="*50)
    driver.quit()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Scraping interrupted by user.")
    finally:
        if 'driver' in locals() and driver:
            driver.quit()
