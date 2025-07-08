import os
import time
import asyncio
import logging
import json
import re
import aiohttp
import aiofiles
import requests
from urllib.parse import urlparse
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
SCRAPED_PAGES_DIR = "./scraped_pages"
LOG_LEVEL = logging.INFO
DOWNLOAD_LOG_FILE = "download_log.csv"
LLM_API_URL = "http://127.0.0.1:8000/generate_selectors"
# **FIX APPLIED HERE: Reduced chunk size to prevent token overflow**
CHUNK_SIZE = 4500  # Characters per chunk, fits safely within phi-2's context
CHUNK_OVERLAP = 400   # Characters of overlap to avoid splitting elements

# Ensure all necessary directories exist
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(SCRAPED_PAGES_DIR, exist_ok=True)

# -----------------------------
# LOGGER SETUP
# -----------------------------
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=LOG_LEVEL,
    handlers=[logging.StreamHandler()]
)
main_logger = logging.getLogger(__name__)

download_logger = logging.getLogger('downloads')
download_logger.setLevel(logging.INFO)
file_handler = logging.FileHandler(DOWNLOAD_LOG_FILE)
file_handler.setFormatter(logging.Formatter('%(asctime)s,%(message)s'))
download_logger.addHandler(file_handler)
if os.path.getsize(DOWNLOAD_LOG_FILE) == 0:
    download_logger.info("PDF_URL,SOURCE_URL")

# -----------------------------
# SELENIUM SETUP
# -----------------------------
options = Options()
options.add_argument("--headless")
options.add_argument("--disable-gpu")
options.add_argument("--window-size=1920,1080")
prefs = {
    "download.default_directory": os.path.abspath(DOWNLOAD_DIR),
    "download.prompt_for_download": False,
    "plugins.always_open_pdf_externally": True
}
options.add_experimental_option("prefs", prefs)
try:
    driver = webdriver.Chrome(options=options)
except Exception as e:
    main_logger.error(f"Failed to initialize Selenium WebDriver: {e}")
    exit()

# -----------------------------
# LLM API COMMUNICATION (CHUNK-BASED)
# -----------------------------
def chunk_html(html_content, size, overlap):
    """Splits HTML content into overlapping chunks."""
    chunks = []
    start = 0
    while start < len(html_content):
        end = start + size
        chunks.append(html_content[start:end])
        start += size - overlap
    return chunks

def call_llm_api(html_chunk):
    """(Synchronous) Calls the local LLM API for a single chunk."""
    try:
        response = requests.post(LLM_API_URL, json={"html": html_chunk}, timeout=120)
        response.raise_for_status()
        return response.json().get("result_text", "")
    except requests.exceptions.RequestException as e:
        main_logger.error(f"LLM API call failed: {e}")
        return None

async def detect_selectors_in_chunks(full_html):
    """
    Analyzes the entire HTML page by breaking it into chunks,
    sending them to the LLM concurrently, and combining the results.
    """
    main_logger.info(f"Analyzing full HTML ({len(full_html)} chars) in {CHUNK_SIZE}-char chunks...")
    html_chunks = chunk_html(full_html, CHUNK_SIZE, CHUNK_OVERLAP)
    main_logger.info(f"Split HTML into {len(html_chunks)} chunks for concurrent analysis.")
    
    loop = asyncio.get_running_loop()
    # Create a list of tasks to call the LLM API for each chunk
    tasks = [loop.run_in_executor(None, call_llm_api, chunk) for chunk in html_chunks]
    
    # Run all API calls concurrently
    api_responses = await asyncio.gather(*tasks)
    
    all_selectors = set() # Use a set to automatically handle duplicates
    for result_str in api_responses:
        if not result_str:
            continue
        try:
            json_match = re.search(r'\{[\s\S]*\}|\[[\s\S]*\]', result_str)
            if not json_match:
                continue
            
            data = json.loads(json_match.group(0))
            
            selectors_list = []
            if isinstance(data, dict):
                for key, value in data.items():
                    if isinstance(value, list):
                        selectors_list = value
                        break
            elif isinstance(data, list):
                selectors_list = data
            
            for selector in selectors_list:
                all_selectors.add(selector)
                
        except Exception as e:
            main_logger.error(f"Error parsing chunk response: {e}\nRaw response: {result_str}")
            
    main_logger.info(f"Reduced {len(all_selectors)} unique selectors from all chunks.")
    return list(all_selectors)

# -----------------------------
# CONCURRENT PDF DOWNLOADER
# -----------------------------
async def download_pdf_concurrently(session, pdf_url, source_url):
    """Asynchronously downloads a single PDF and logs the result."""
    try:
        async with session.get(pdf_url, timeout=60) as response:
            response.raise_for_status()
            content = await response.read()
            
            file_name = pdf_url.split('/')[-1].split('?')[0] # Clean query params
            if not file_name: file_name = "downloaded_file.pdf"
            if not file_name.lower().endswith('.pdf'): file_name += ".pdf"
            file_path = os.path.join(DOWNLOAD_DIR, re.sub(r'[\\/*?:"<>|]', "_", file_name))

            async with aiofiles.open(file_path, 'wb') as f:
                await f.write(content)
            
            main_logger.info(f"SUCCESS downloading {pdf_url}")
            download_logger.info(f"{pdf_url},{source_url}")
            return pdf_url
    except Exception as e:
        main_logger.error(f"FAILED downloading {pdf_url}: {e}")
        return None

# -----------------------------
# MAIN SCRAPER LOOP
# -----------------------------
async def main():
    base_domain = urlparse(START_URL).netloc
    main_logger.info(f"Scraping initiated. Staying within domain: {base_domain}")

    visited_pages = set()
    downloaded_pdf_urls = set()
    queue = deque([START_URL])

    async with aiohttp.ClientSession() as session:
        while queue:
            url = queue.popleft()
            if url in visited_pages:
                continue
            
            try:
                main_logger.info(f"Visiting: {url} (Queue size: {len(queue)})")
                driver.get(url)
                visited_pages.add(url)
                time.sleep(5) 
                
                html = driver.page_source
                safe_filename = re.sub(r'[\\/*?:"<>|]', "_", url) + ".html"
                async with aiofiles.open(os.path.join(SCRAPED_PAGES_DIR, safe_filename), 'w', encoding='utf-8') as f:
                    await f.write(html)
                
                # --- Get selectors from LLM using the new chunking method ---
                selectors = await detect_selectors_in_chunks(html)
                
                # --- Click links and discover PDFs ---
                pdf_links_on_page = set()
                main_logger.info(f"Attempting to click {len(selectors)} selectors on {url}")
                for selector in selectors:
                    try:
                        element = driver.find_element(By.CSS_SELECTOR, selector)
                        driver.execute_script("arguments[0].scrollIntoView(true);", element)
                        time.sleep(0.5)
                        element.click()
                        time.sleep(2)
                    except Exception as e:
                        main_logger.warning(f"Could not click selector '{selector}': {e}")
                
                pdf_elements = driver.find_elements(By.CSS_SELECTOR, "a[href$='.pdf' i]")
                for element in pdf_elements:
                    href = element.get_attribute('href')
                    if href:
                        pdf_links_on_page.add(href)
                
                # --- Create and run PDF download tasks concurrently ---
                download_tasks = []
                for pdf_url in pdf_links_on_page:
                    if pdf_url not in downloaded_pdf_urls:
                        downloaded_pdf_urls.add(pdf_url)
                        task = download_pdf_concurrently(session, pdf_url, url)
                        download_tasks.append(task)
                
                if download_tasks:
                    main_logger.info(f"Starting concurrent download of {len(download_tasks)} PDFs...")
                    await asyncio.gather(*download_tasks)

                # --- Discover new links to crawl (domain-scoped) ---
                link_elements = driver.find_elements(By.TAG_NAME, 'a')
                for link in link_elements:
                    href = link.get_attribute('href')
                    if href and href.startswith('http'):
                        if urlparse(href).netloc == base_domain:
                            if href not in visited_pages and href not in queue:
                                queue.append(href)

            except Exception as e:
                main_logger.error(f"A critical error occurred while processing {url}: {e}")

    main_logger.info("="*50)
    main_logger.info("Scraping queue is empty. Process complete.")
    driver.quit()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        main_logger.info("Scraping interrupted by user.")
    finally:
        if 'driver' in locals() and driver:
            driver.quit()
