# Local Privacy Benefit Discovery (LPBD)

### CSCI 4390 Senior Project | University of Texas Rio Grande Valley

![Status](https://img.shields.io/badge/Status-Prototype-blue)
![UI](https://img.shields.io/badge/UI-CustomTkinter-orange)
![Privacy](https://img.shields.io/badge/Privacy-Local_First-green)

## What This Project Does

LPBD helps students discover scholarships, aid, and support services while keeping personal profile data local.

End-to-end flow:

1. Chrome extension collects relevant `.edu` and `.gov` domains (plus optional custom pages).
2. Native host stores those items in a local SQLite DB.
3. `map.py` discovers pages on each domain and writes `mapped_pages.json`.
4. `scrape_all.py` scrapes mapped pages and writes text files into `scraped_output/`.
5. `match.py` runs the multi-stage matching pipeline with Ollama and writes `matched_benefits.json`.
6. GUI lets users fill questionnaire data and chat locally with the model.

## Repo Layout

- `browser_extension/`: Manifest V3 Chrome extension (domain/page collection, queueing, native messaging).
- `native_host/`: Chrome native messaging host (`host.py`, `setup_host.py`, local DB).
- `mapper/`: Domain mapper (sitemap + BFS crawler).
- `worker_service/`: FastAPI scraper worker with weekly pack caching and change-detection.
- `matching/`: Multi-stage pipeline -- keyword filter, LLM matching, evidence validation, LLM verification, keyword fallback detection, profile signals, and cross-referencing.
- `GUI/`: Desktop app (login/signup/questionnaire/chat/settings).
- `map.py`, `scrape_all.py`, `match.py`: top-level pipeline controllers.
- `match_it.py`: test/debug runner (same pipeline, prints reports to console only).
- `ollama_client.py`: shared REST wrapper for local Ollama server.
- `domains.py`: CLI utility to inspect/clear the native host DB.
- `custom_pages.py`: CLI to manage user-added custom page URLs.

## Prerequisites

- Python 3.10+
- Google Chrome
- Ollama installed locally: https://ollama.com/download
- Windows for automatic native host setup (`native_host/setup_host.py` uses Windows registry)

Install Python deps:

```bash
pip install -r requirements.txt
```

Pull required Ollama models:

```bash
ollama pull phi3:mini
ollama pull nomic-embed-text
```

`phi3:mini` is the default matching/chat model. `nomic-embed-text` is used for page embeddings in both the full pipeline and realtime mode.

## Step-By-Step: First Full Run

### 1. Clone and enter repo

```bash
git clone https://github.com/General-Zilver/LPBD.git
cd LPBD
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Install Ollama models

```bash
ollama pull phi3:mini
ollama pull nomic-embed-text
```

### 4. Run GUI once to create questionnaire answers

```bash
python GUI/start.py
```

Complete login + questionnaire flow.

### 5. Load extension in Chrome

1. Open `chrome://extensions/`
2. Turn on Developer mode
3. Click Load unpacked
4. Select `browser_extension/`
5. Copy the extension ID

### 6. Register native host (Windows)

```bash
python native_host/setup_host.py
```

When prompted, paste the extension ID from step 5.

### 7. Collect some browsing data

With extension enabled, browse a few `.edu` / `.gov` pages.

Optional check:

```bash
python domains.py
```

### 8. Run pipeline controllers in order

```bash
python map.py
python scrape_all.py
python match.py --user default_user
```

`match.py` runs the full pipeline: keyword filter, LLM matching, evidence validation, pass-2 LLM verification, keyword fallback detection, deduplication, and cross-referencing. It uses both base keywords and profile-derived keywords by default.

Use `--no-profile-keywords` if you want base keywords only.
Use `--no-verify-pass2` to skip the second LLM verification pass.

For testing/debugging without saving results, use `match_it.py` instead:

```bash
python match_it.py --user default_user --verbose
```

### 9. Open GUI chat/results view

```bash
python GUI/start.py
```

## What Each Pipeline Step Produces

| Step | Script | Reads | Writes |
|---|---|---|---|
| Domain map | `map.py` | `native_host/local_benefits.db` (or `local_benefits.db`) | `mapped_pages.json` |
| Scrape | `scrape_all.py` | `mapped_pages.json`, `custom_pages.json` | `scraped_output/scraped_*.txt` |
| Match | `match.py --user <username>` | `answers.json`, `scraped_output/`, `embeddings.json` | `pipeline_state.json`, `matched_benefits.json`, `embeddings.json` |

## Main Runtime Files

- `answers.json`: questionnaire answers per user, used for matching and chat context.
- `native_host/local_benefits.db`: collected domain/page queue persisted by native host.
- `mapped_pages.json`: mapper output (domain -> discovered URLs).
- `scraped_output/*.txt`: normalized page text from scraper.
- `embeddings.json`: page embedding cache (nomic-embed-text vectors), used by both full pipeline and realtime mode.
- `pipeline_state.json`: current/last pipeline stage metadata (supports resume).
- `matched_benefits.json`: final results envelope (`results` list plus pipeline metadata).
- `custom_pages.json`: user-added custom page URLs with status tracking (pending/scraped/error).
- `institutions.json`: list of educational institutions for questionnaire dropdown.
- `users.json`: user credentials for GUI login.

## Useful Commands

```bash
# Show captured domains/pages
python domains.py

# Show all DB rows
python domains.py --all

# Clear all captured domain/page rows
python domains.py --clear

# Manage custom pages
python custom_pages.py list
python custom_pages.py add https://example.edu/scholarships
python custom_pages.py remove https://example.edu/scholarships

# Faster map test
python map.py --max-pages 50 --delay 0.1

# Scrape only first N pages per mapped domain
python scrape_all.py --max-pages 5

# Default matching run (base + profile keywords, pass-2 verification on)
python match.py --user default_user

# Use a different model
python match.py --user default_user --model llama3:8b

# Disable pass-2 LLM verification (faster, less strict)
python match.py --user default_user --no-verify-pass2

# Low-priority background mode with thread cap
python match.py --user default_user --low-priority --num-threads 4

# Disable profile-derived keyword additions (base keywords only)
python match.py --user default_user --no-profile-keywords

# Real-time single-page matching
python match.py --user default_user --url https://utrgv.edu/financial-aid

# Debug/test run (prints reports to console, does not save results)
python match_it.py --user default_user --verbose
```

Keyword mode quick reference:
- `default`: base keyword list + profile-derived keyword additions.
- `--profile-keywords`: explicitly turns profile-derived additions on.
- `--no-profile-keywords`: turns profile-derived additions off (base list only).

Pass-2 verification quick reference:
- `default`: second strict LLM verification pass is **on**.
- `--no-verify-pass2`: disables it (faster but less strict).
- `--verify-pass2`: explicitly turns it on.

## Quick Test Without Chrome Extension

If you want to test pipeline mechanics without native host data:

1. Map a domain directly with mapper:

```bash
python mapper/mapper.py https://www.utrgv.edu --mode foreground --workers 1 --output mapped_pages.json
```

2. Run scrape + match:

```bash
python scrape_all.py
python match.py --user default_user
```

Or add a single custom page and match it in realtime:

```bash
python custom_pages.py add https://www.utrgv.edu/financial-aid/scholarships
python scrape_all.py
python match.py --user default_user
```

## Troubleshooting

- `local_benefits.db not found`:
  - Run `python native_host/setup_host.py`
  - Make sure extension is loaded and has sent at least one item
- `No domains found in the database`:
  - Browse `.edu` / `.gov` sites with extension enabled, then run `python domains.py`
- `No answers found for user ...`:
  - Use `python match_it.py --user default_user`
  - Verify `answers.json` exists
- `Ollama is not running`:
  - Start Ollama app or run `ollama serve`
- `Model ... not found`:
  - Pull it: `ollama pull phi3:mini` and `ollama pull nomic-embed-text`

## Team

- Josue Aranday
- John Payes
- Alejandro Salinas
- Kevin Gonzalez

Faculty Adviser: Pedro Fonseca

## License

Distributed under the MIT License. See `LICENSE` for more information.
