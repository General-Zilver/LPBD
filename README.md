# Student Benefit Discovery & Privacy App

### CSCI 4390 Senior Project | University of Texas Rio Grande Valley

![Status](https://img.shields.io/badge/Status-Prototype-blue)
![UI](https://img.shields.io/badge/UI-CustomTkinter-orange)
![Privacy](https://img.shields.io/badge/Privacy-Local_First-green)

## 🎓 Project Overview

**The Problem:** Students miss out on thousands of dollars in benefits—scholarships, financial aid (FAFSA), university grants, and health resources—because the information is scattered across complex websites and privacy policies they rarely read. Using current AI tools 
to find these benefits often requires uploading sensitive personal data to third-party servers.

**The Solution:** We are building a **Local-First Student Benefit Analyzer**. Our application runs on the student's desktop, using an interactive form to collect profile data that is **encrypted and stored locally**. A companion browser extension identifies 
relevant university and scholarship domains, which are processed by a **stateless cloud worker** to find new opportunities without ever exposing the student's private profile.

## 👥 The Team

* **Josue Aranday**
* **John Payes** 
* **Alejandro Salinas** 
* **Kevin Gonzalez** 

**Faculty Adviser:** Pedro Fonseca

---

## 🏗️ Architecture: The "Weekly Sync" Model

We utilize a **Split-Architecture** that keeps user data local while offloading heavy web scraping to the cloud.

### 1. The Desktop Vault (CustomTkinter)
* **Interface:** A modern, high-DPI desktop application built with **CustomTkinter**.
* **Function:** Users fill out a secure profile (GPA, major, financial needs). This data is stored in an **encrypted SQLite database via SQLCipher**.
* **Analysis:** The app performs local matching against downloaded benefit data.

### 2. The Accumulator (Browser Extension)
* **Privacy-First Tracking:** The extension does not track full browsing history. It maintains a short-term local allowlist of **relevant domains** (e.g., `utrgv.edu`, `studentaid.gov`) identified using a user-maintained allowlist plus simple heuristics.
* **Native Messaging:** The extension communicates **only** with the local Desktop App via Chrome Native Messaging. No browsing data is sent to the cloud during standard browsing sessions.

### 3. The Ephemeral Worker (Cloud)
* **Weekly Sync:** The Desktop App sends a batch of relevant domains to our Cloud Worker **once a week by default**. Users can manually trigger an on-demand sync if needed.
* **Change Detection:** The worker scrapes the sites, hashes the content (SHA-256), and checks for updates. If the content is new, it processes the text into JSON and returns it.
* **Minimal Retention:** The worker is stateless and does not persist request payloads or scraped content beyond processing. Application-level logging is disabled or limited to aggregate operational metrics.

---

## 🛠️ Technology Stack

### Core Application
* **Language:** Python 3.10+
* **GUI Framework:** [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter)
* **Local Database:** SQLite (encrypted via SQLCipher)
* **Communication:** Standard Input/Output (Stdin/Stdout) for Native Messaging

### Browser Integration
* **Target:** Google Chrome / Chromium
* **Manifest:** V3
* **Mechanism:** Chrome Native Messaging API

### Cloud & AI
* **Compute:** Serverless Functions (Ephemeral/Stateless)
* **Scraping:** Headless Browsing (Playwright)
* **Processing:** Text Chunking & SHA-256 Hashing (Normalized)

---

## 🔒 Privacy Manifesto

We explicitly define the boundaries of our privacy claims:

1.  **No Long-Term Log:** We do not upload browsing history or store a long-term per-URL log. The extension keeps only a local, short-term list of candidate domains for the weekly sync.
2.  **Ephemeral Processing:** Cloud scraping is done by transient workers that exist only for the duration of the request.
3.  **Local Profiling:** The user's specific financial and academic profile (e.g., "GPA: 3.5", "Income: <$30k") **never** leaves the local device. The cloud only sees the *domains* to be scraped, not the *reason* why.

---

## 🚀 Getting Started

### Prerequisites
* Python 3.10 or higher
* Google Chrome (for extension testing)
* Git

### Installation

1.  **Clone the Repository**
    ```bash
    git clone [https://github.com/General-Zilver/LPBD.git](https://github.com/General-Zilver/LPBD.git)
    cd LPBD
    ```

2.  **Install Python Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Load the Extension (Developer Mode)**
    * Open Chrome and navigate to `chrome://extensions/`
    * Toggle "Developer mode" (top right).
    * Click "Load unpacked" and select the `extension/` folder in this repo.

4.  **Register Native Host**
    * Run the registration script to link the extension to the Python app:
    ```bash
    python register_host.py
    ```

5.  **Run the Desktop App**
    ```bash
    python main.py
    ```

---

## 📅 Roadmap

* [ ] **Phase 1: UI Prototype** - Build the CustomTkinter form for Student Profile creation.
* [ ] **Phase 2: Extension Link** - Establish Native Messaging between Chrome and Python.
* [ ] **Phase 3: UTRGV Scraper** - Build the first scraper module targeting UTRGV Financial Aid pages (MVP Scope).
* [ ] **Phase 4: Encryption** - Implement SQLCipher encryption for the local database.
* [ ] **Phase 5: Cloud Sync** - Connect the local app to the Ephemeral Cloud Worker.

---

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.