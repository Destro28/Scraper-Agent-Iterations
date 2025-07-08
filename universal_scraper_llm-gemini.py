import os
import time
import asyncio
import logging
from collections import deque
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from browser_use import Agent
from langchain_google_genai import ChatGoogleGenerativeAI
from selenium.webdriver.common.by import By
# -----------------------------
# CONFIGURATION
# -----------------------------
API_KEY = "<YOUR_API_KEY>"  # Replace with your Gemini API key
START_URL = "https://www.govinfo.gov/app/collection/cfr/"
DOWNLOAD_DIR = "./pdfs"
MAX_PAGES = 100        # safety limit on pages to visit
MAX_PDFS = 500         # safety limit on pdfs to download
LOG_LEVEL = logging.INFO

# Ensure download directory exists
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# -----------------------------
# LOGGER SETUP
# -----------------------------
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=LOG_LEVEL
)
logger = logging.getLogger(__name__)

# -----------------------------
# SELENIUM SETUP
# -----------------------------
options = Options()
options.add_argument("--headless")
options.add_argument("--disable-gpu")
prefs = {"download.default_directory": os.path.abspath(DOWNLOAD_DIR),
         "download.prompt_for_download": False}
options.add_experimental_option("prefs", prefs)
driver = webdriver.Chrome(options=options)

# -----------------------------
# SELENIUM DOWNLOAD FUNCTION
# -----------------------------
def click_and_download(selectors, page_url):
    """
    Given a list of CSS selectors and the current URL,
    click each element and download any revealed PDFs.
    Returns set of any new PDF URLs downloaded.
    """
    driver.get(page_url)
    time.sleep(1)
    for selector in selectors:
        try:
            el = driver.find_element_by_css_selector(selector)
            el.click()
            logger.info(f"Clicked selector {selector} on {page_url}")
            time.sleep(2)
        except Exception as e:
            logger.warning(f"Failed to click {selector}: {e}")

    # find visible PDF links
    pdf_links = set()
    for a in driver.find_elements_by_css_selector("a[href$='.pdf']"):
        href = a.get_attribute('href')
        if href:
            pdf_links.add(href)
            local_name = href.split('/')[-1]
            path = os.path.join(DOWNLOAD_DIR, local_name)
            if not os.path.exists(path):
                try:
                    import requests
                    r = requests.get(href, timeout=10)
                    with open(path, 'wb') as f:
                        f.write(r.content)
                    logger.info(f"Downloaded PDF: {href}")
                except Exception as e:
                    logger.error(f"Error downloading {href}: {e}")
    return pdf_links

# -----------------------------
# AGENT SELECTOR DETECTION
# -----------------------------
async def detect_selectors(html_snippet):
    """
    Uses Gemini via LangChain to detect relevant CSS selectors
    that likely lead to PDF documents on the page.
    """
    llm = ChatGoogleGenerativeAI(
        model="gemini-1.5-pro",
        google_api_key=API_KEY,
        temperature=0.2,
        convert_system_message_to_human=True
    )
    task = (
        f"Here is the HTML content of the page:\n"  
        f"{html_snippet}\n"  
        "Identify up to 30 CSS selectors (divs, links, buttons, table rows, etc.) "
        "that are likely to lead to PDF documents when clicked. "
        "Return a JSON array of the selectors only."
    )
    agent = Agent(
        task=task,
        llm=llm,
        max_actions_per_step=1,
    )
    result = await agent.run()
    try:
        selectors = json.loads(result)
        if isinstance(selectors, list):
            return selectors
    except Exception:
        logger.warning(f"Could not parse selectors: {result}")
    return []

# -----------------------------
# MAIN SCRAPER LOOP
# -----------------------------
async def main():
    visited_pages = set()
    downloaded_pdfs = set()
    queue = deque([START_URL])

    while queue and len(visited_pages) < MAX_PAGES and len(downloaded_pdfs) < MAX_PDFS:
        url = queue.popleft()
        if url in visited_pages:
            continue
        visited_pages.add(url)
        logger.info(f"Visiting: {url} (Queue: {len(queue)})")

        # load page and get HTML snippet
        driver.get(url)
        time.sleep(1)
        html = driver.page_source[:20000]  # truncate to fit token limits

        # detect selectors via LLM
        selectors = await detect_selectors(html)
        logger.info(f"Detected selectors on {url}: {selectors}")

        # click and download any PDFs
        new_pdfs = click_and_download(selectors, url)
        downloaded_pdfs.update(new_pdfs)

        # discover new URLs to visit (exclude PDFs)
        for a in driver.find_elements_by_css_selector('a[href]'):
            href = a.get_attribute('href')
            if href and href.startswith('http') and not href.lower().endswith('.pdf'):
                if href not in visited_pages:
                    queue.append(href)

    # Summary
    logger.info(f"Scraping complete. Pages visited: {len(visited_pages)}. PDFs downloaded: {len(downloaded_pdfs)}")

if __name__ == '__main__':
    asyncio.run(main())
