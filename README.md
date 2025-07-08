# Autonomous Scraping Agent for PDF Retrieval

### A smart, AI-powered agent designed to autonomously navigate websites, identify potential document links, and download all relevant PDF files.

---

## Project Status

* **Phase:** Advanced Prototype
* **Current Goal:** Stabilize and optimize the performance of the local LLM-driven scraping process to achieve production-grade stability.
* **Progress:**
    * [x] **Initial Proof of Concept (Cloud Agent):** Successfully used the Gemini API via `browser-use` to create an effective agent that intelligently identified and downloaded PDFs.
    * [x] **Local Model Architecture:** Successfully replaced the cloud API with a local, self-hosted LLM (`microsoft/phi-2`) served via a FastAPI server, creating a fully private agentic system.
    * [x] **Full-Page Analysis:** Implemented an HTML chunking strategy to allow the local model to analyze the content of entire webpages, overcoming its context window limitations.
    * [x] **Advanced Scraping Features:** The agent now archives all visited HTML pages, keeps a detailed log of downloaded PDFs, and downloads files concurrently to improve speed.
    * [ ] **Production-Grade Performance:** Currently addressing performance bottlenecks (timeout errors) related to local hardware constraints when processing numerous HTML chunks.

---

## Overview

This project is an advanced **scraping agent** that goes beyond simple link extraction. It leverages a Large Language Model (LLM) to act as the "brain," analyzing the structure of webpages to intelligently decide which elements to interact with.

The primary goal is to deploy this agent on a target website and have it autonomously crawl through the pages, downloading every PDF document it can find. This is particularly useful for archiving documents from complex sites like government portals, legal databases, or academic archives where PDFs are not always available via direct links.

---

## Project Journey & Current Challenges

The development of this agent has been an iterative process focused on finding the right balance between intelligence, privacy, and performance.

1.  **Success with Cloud APIs:** The initial version of the agent used Google's Gemini Pro. This approach was highly successful and performant, proving that an LLM-driven agent could effectively navigate and extract documents from complex websites.

2.  **Success with Local Models:** To create a more private and self-contained system, the Gemini API was replaced with a locally hosted `microsoft/phi-2` model. This also worked successfully for basic scraping tasks, demonstrating the viability of using smaller, local LLMs for agentic control.

3.  **The Scaling Challenge:** The primary challenge arose when attempting to scale the local model approach to a "production-grade" level. To ensure the agent analyzed entire webpages, a chunking mechanism was introduced to feed the full HTML to the `phi-2` model. While this solved the model's 2048-token context limit, it revealed a performance bottleneck: processing dozens of HTML chunks for a single page on consumer hardware is slow and can lead to timeouts.

The current work is focused on solving this very fixable performance issue to create a truly robust and scalable local scraping agent.

---

## Architecture

The system operates on a robust **client-server model** to separate concerns and manage resources effectively.

1.  **The LLM Server (`phi3_server_api.py`)**
    * **Purpose:** To host a quantized, local Large Language Model.
    * **Technology:** Uses `FastAPI` to create a simple API endpoint.
    * **Model:** Currently configured to run `microsoft/phi-2`, a ~3B parameter model quantized to 4-bits using `bitsandbytes` to run efficiently on consumer GPUs.
    * **Function:** It receives chunks of HTML from the client, processes them with the LLM, and returns a list of potential CSS selectors that might lead to PDFs.

2.  **The Scraper Client (`scraper-agent.py`)**
    * **Purpose:** To navigate the web, communicate with the LLM server, and manage the scraping process.
    * **Technology:** Uses `Selenium` for headless browser automation and `asyncio` / `aiohttp` for high-performance, concurrent operations.
    * **Function:**
        * Crawls websites starting from a given URL.
        * Saves the HTML of every visited page for archival purposes.
        * Splits the HTML into chunks and sends them to the LLM Server for analysis.
        * Receives the list of intelligent selectors from the LLM.
        * Uses Selenium to click the identified elements.
        * Scans the page for any newly revealed PDF links.
        * Downloads all found PDFs concurrently.
        * Maintains a `download_log.csv` of all retrieved documents.

---

## Setup and Installation

This project requires two separate Python environments to manage dependencies correctly.

#### 1. The LLM Server Environment

This environment contains the heavy-duty AI and GPU libraries.

```bash
# 1. Create and activate a Conda environment (or venv)
conda create --name llm_server python=3.11
conda activate llm_server

# 2. Install all necessary packages
pip install "uvicorn[standard]" fastapi
pip install torch torchvision torchaudio --index-url [https://download.pytorch.org/whl/cu121](https://download.pytorch.org/whl/cu121)
pip install transformers accelerate bitsandbytes
```

#### 2. The Scraper Client Environment

This is a lighter environment for the Selenium browser and network requests.

```bash
# 1. Create and activate a separate environment
conda create --name scraper_client python=3.11
conda activate scraper_client

# 2. Install all necessary packages
pip install selenium requests aiohttp aiofiles
```

---

## How to Run

You must start the server first, then run the client in a separate terminal.

**Step 1: Start the LLM API Server**

In a terminal with the `llm_server` environment activated, run:

```bash
# Make sure your server script is named phi3_server_api.py
uvicorn phi3_server_api:app --host 0.0.0.0 --port 8000
```

The server will initialize the model and wait for requests.

**Step 2: Run the Scraper Agent**

In a second terminal with the `scraper_client` environment activated, run:

```bash
python scraper-agent.py
```

The scraper will begin its process, communicating with the running server to guide its actions.

---

## Future Work & Roadmap

While the core functionality has been successfully implemented, the journey to a truly production-grade product involves several key improvements. This serves as the future roadmap for the project.

* [ ] **Advanced Error Handling:** Implement more sophisticated retry logic for both network requests and LLM API calls.
* [ ] **Persistent State:** Read the `download_log.csv` on startup to prevent re-downloading files across multiple runs of the script.
* [ ] **Configuration Management:** Move hardcoded variables (like `START_URL`, `CHUNK_SIZE`) into a `config.yaml` file for easier management.
* [ ] **Scalability with a Message Queue:** Replace the local `deque` with a robust message queue like RabbitMQ or Redis to allow multiple scraper clients to run in parallel.
* [ ] **Database Integration:** Store all logs and metadata in a structured database (e.g., SQLite or PostgreSQL) for better querying and analysis.
* [ ] **Dockerization:** Containerize both the server and client applications with Docker for one-command deployment and perfect environment replication.
* [ ] **User Interface:** Develop a simple web UI (with Streamlit or Flask) or a polished Command-Line Interface (CLI) to allow non-developers to run and monitor the scraper.
