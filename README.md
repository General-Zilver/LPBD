# Student Benefit Discovery & Privacy App

### CSCI 4390 Senior Project | University of Texas Rio Grande Valley

![Status](https://img.shields.io/badge/Status-Prototype-blue)
![UI](https://img.shields.io/badge/UI-CustomTkinter-orange)
![Privacy](https://img.shields.io/badge/Privacy-Local_First-green)

## Project Overview

**The Problem:** Students miss out on thousands of dollars in benefits—scholarships, financial aid (FAFSA), university grants, and health resources—because the information is scattered across complex websites and privacy policies they rarely read. Using current AI tools to find these benefits often requires uploading sensitive personal data to third-party servers.

**The Solution:** We are building a **Local-First Student Benefit Analyzer**. Our application runs on the student's desktop, using an interactive form to collect profile data that is **encrypted and stored locally**. A companion browser extension identifies relevant university and scholarship domains, which are processed by **stateless cloud workers** (mapper and scraper) to find new opportunities without ever exposing the student's private profile. A local LLM matches scraped benefits against the student's profile entirely on-device.

## The Team

* **Josue Aranday**
* **John Payes**
* **Alejandro Salinas**
* **Kevin Gonzalez**

**Faculty Adviser:** Pedro Fonseca

---

## Architecture: Split-Architecture Model

We utilize a **Split-Architecture** that keeps user data local while offloading heavy web crawling and scraping to stateless workers designed for cloud deployment.

### 1. Desktop App (CustomTkinter)
* **Interface:** A modern, high-DPI desktop application built with **CustomTkinter**.
* **Function:** Users fill out a secure profile (GPA, major, financial needs, citizenship, etc.). This data is stored in an **encrypted local database**.
* **Matching:** A local LLM (**Ollama** with phi3:mini) compares the user's profile against scraped benefit data entirely on-device — personal data never leaves the machine.
* **Chat:** An AI chat page lets the user ask follow-up questions about their matched benefits using the same local LLM.

### 2. Browser Extension (Manifest V3)
* **Privacy-First Collection:** The extension does not track full browsing history. It passively collects **relevant `.edu` and `.gov` domains** from the user's browsing using simple heuristics.
* **Throttling:** Each domain has a 1-week cooldown to avoid redundant submissions, with a 200-item queue cap and periodic retry.
* **Native Messaging:** The extension communicates **only** with the local Desktop App via Chrome Native Messaging. No browsing data is sent to the cloud.

### 3. Native Host (Chrome NM Bridge)
* **Protocol:** Reads/writes length-prefixed JSON over stdin/stdout per the Chrome Native Messaging spec.
* **Storage:** Stores collected domains and browsing items in a local **SQLite** database (`local_benefits.db`).
* **Setup:** `setup_host.py` dynamically configures the NM manifest and registry entry for the current machine.

### 4. Mapper (`mapper/`)
* **Purpose:** Discovers all relevant pages on a given domain using a two-phase approach: **sitemap pre-seeding** (free URL discovery from sitemap.xml) followed by **BFS crawl** to find pages sitemaps missed.
* **Output:** Produces `mapped_pages.json` — a mapping of domains to their discovered page URLs.
* **Design:** Stateless worker with resource-aware tuning (CPU/RAM detection). Designed for cloud deployment; currently runs locally for development and testing.

### 5. Scraper (`worker_service/`)
* **Purpose:** A **FastAPI** app that scrapes mapped pages and extracts clean text content.
* **Change Detection:** Three-layer system — weekly pack cache, conditional HTTP headers (ETag / If-Modified-Since), and SHA-256 content hashing — so unchanged pages are skipped efficiently.
* **Design:** Ephemeral, stateless worker with minimal retention. Designed for cloud deployment as a serverless function; currently runs locally for development and testing.

### 6. Benefit Matcher (`match.py`)
* **Purpose:** Reads the user's profile from `answers.json` and all scraped text from `scraped_output/`, then sends chunks to the local **Ollama** LLM to identify matching benefits.
* **Output:** Produces `matched_benefits.json` — a deduplicated list of benefits with names, descriptions, eligibility, and source URLs.
* **Privacy:** The LLM runs entirely on-device via Ollama (localhost:11434). No personal data is transmitted.

---

## Full Pipeline

```
Browser Extension
    → Native Host (SQLite DB)
        → map.py (controller) → mapped_pages.json
            → scrape_all.py (controller) → scraped_output/
                → match.py (controller) → matched_benefits.json
                    → GUI chat (Ollama-powered)
```

Each stage communicates via files or databases — no direct imports between components.

---

## Technology Stack

### Core Application
* **Language:** Python 3.10+
* **GUI Framework:** [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter)
* **Local Database:** SQLite
* **Local LLM:** [Ollama](https://ollama.com/) with phi3:mini (2.3 GB)

### Browser Integration
* **Target:** Google Chrome / Chromium
* **Manifest:** V3
* **Mechanism:** Chrome Native Messaging API

### Web Scraping
* **API Framework:** FastAPI + uvicorn
* **HTML Parsing:** BeautifulSoup4
* **Page Discovery:** BFS crawl + sitemap XML parsing

---

## Privacy Manifesto

1. **Local Profiling:** The user's financial and academic profile **never** leaves the local device. The cloud workers only see domains and URLs to scrape, not the reason why.
2. **Local LLM:** Benefit matching and chat are powered by Ollama running on localhost. No data is sent to external AI services.
3. **Ephemeral Processing:** Cloud scraping workers are stateless and do not persist request payloads or scraped content beyond processing.
4. **No Long-Term Log:** The extension keeps only a local, short-term list of candidate domains. It does not upload browsing history.

---

## Getting Started

### Prerequisites
* Python 3.10 or higher
* Google Chrome (for extension)
* [Ollama](https://ollama.com/) installed with the phi3:mini model
* Git

### Installation

1. **Clone the Repository**
    ```bash
    git clone https://github.com/General-Zilver/LPBD.git
    cd LPBD
    ```

2. **Install Python Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

3. **Install Ollama and pull the model**
    ```bash
    ollama pull phi3:mini
    ```

4. **Set up the Native Host**
    ```bash
    python native_host/setup_host.py
    ```
    Follow the prompts to enter your Chrome extension ID.

5. **Load the Browser Extension**
    * Open Chrome → `chrome://extensions/`
    * Toggle "Developer mode" (top right)
    * Click "Load unpacked" and select the `browser_extension/` folder
    * Copy the Extension ID and use it in step 4 if you haven't already

### Running the Pipeline

Once the extension has collected some domains, run each stage in order:

```bash
# 1. Map domains from the extension's DB into page URLs
python map.py                        # maps all collected domains
python map.py --max-pages 50         # limit pages per domain for faster runs

# 2. Scrape all mapped pages (auto-starts the scraper API)
python scrape_all.py                 # default: 20 pages per domain
python scrape_all.py --all           # scrape everything
python scrape_all.py --max-pages 5   # limit for quick demo

# 3. Match scraped benefits against the user's profile
python match.py                      # requires answers.json from the GUI questionnaire

# 4. Launch the desktop app
python GUI/start.py
```

---

## Roadmap

- [x] **Phase 1: UI Prototype** — CustomTkinter desktop app with login, signup, questionnaire, and chat pages.
- [x] **Phase 2: Extension + Native Host** — Manifest V3 extension with Chrome Native Messaging bridge and SQLite storage.
- [x] **Phase 3: Mapper** — BFS + sitemap crawler for page discovery, with resource-aware worker tuning.
- [x] **Phase 4: Scraper** — FastAPI ephemeral worker with three-layer change detection and weekly pack caching.
- [x] **Phase 5: Local LLM Integration** — Ollama-powered benefit matching and chat, entirely on-device.
- [x] **Phase 6: Pipeline Controllers** — `map.py`, `scrape_all.py`, and `match.py` for end-to-end demo workflow.
- [ ] **Phase 7: Cloud Deployment** — Deploy mapper and scraper as serverless cloud workers with weekly sync scheduling.
- [ ] **Phase 8: Database Encryption** — Implement SQLCipher encryption for the local profile database.

---

## License

Distributed under the MIT License. See `LICENSE` for more information.
