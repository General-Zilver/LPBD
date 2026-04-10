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
5. `match_it.py` runs the keyword-gated matching pipeline with Ollama and writes `matched_benefits.json`.
6. GUI lets users fill questionnaire data and chat locally with the model.

## Repo Layout

- `browser_extension/`: Manifest V3 Chrome extension (domain/page collection, queueing, native messaging).
- `native_host/`: Chrome native messaging host (`host.py`, `setup_host.py`, local DB).
- `mapper/`: Domain mapper (sitemap + BFS crawler).
- `worker_service/`: FastAPI scraper worker with caching/change-detection.
- `matching/`: Keyword pre-filtering, LLM matching, validation, and keyword fallback detection.
- `GUI/`: Desktop app (login/signup/questionnaire/chat).
- `map.py`, `scrape_all.py`, `match_it.py`: top-level pipeline controllers.

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
ollama pull llama3:8b
```

Optional (only needed for realtime single-page mode in `match.py --url`):

```bash
ollama pull nomic-embed-text
```

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
ollama pull llama3:8b
```

Optional for realtime single-page mode:

```bash
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
python match_it.py --user default_user
```

### 9. Open GUI chat/results view

```bash
python GUI/start.py
```

## What Each Pipeline Step Produces

| Step | Script | Reads | Writes |
|---|---|---|---|
| Domain map | `map.py` | `native_host/local_benefits.db` (or `local_benefits.db`) | `mapped_pages.json` |
| Scrape | `scrape_all.py` | `mapped_pages.json` (+ custom pages in DB) | `scraped_output/scraped_*.txt` |
| Match | `match_it.py --user default_user` | `answers.json`, `scraped_output/` | `pipeline_state.json`, `matched_benefits.json` |

## Main Runtime Files

- `answers.json`: questionnaire answers used for matching.
- `native_host/local_benefits.db`: collected domain/page queue persisted by native host.
- `mapped_pages.json`: mapper output (domain -> discovered URLs).
- `scraped_output/*.txt`: normalized page text from scraper.
- `embeddings.json`: optional cache used by realtime single-page matching (`match.py --url`).
- `pipeline_state.json`: current/last pipeline stage metadata.
- `matched_benefits.json`: final results envelope (`results` list plus pipeline metadata).

## Useful Commands

```bash
# Show captured domains/pages
python domains.py

# Show all DB rows
python domains.py --all

# Clear all captured domain/page rows
python domains.py --clear

# Faster map test
python map.py --max-pages 50 --delay 0.1

# Scrape only first N pages per mapped domain
python scrape_all.py --max-pages 5

# Verbose matching output
python match_it.py --user default_user --verbose

# Use a different model
python match_it.py --user default_user --model phi3:mini
```

## Quick Test Without Chrome Extension

If you want to test pipeline mechanics without native host data:

1. Map a domain directly with mapper:

```bash
python mapper/mapper.py https://www.utrgv.edu --mode foreground --workers 1 --output mapped_pages.json
```

2. Run scrape + match:

```bash
python scrape_all.py
python match_it.py --user default_user
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
  - Pull it, for example `ollama pull llama3:8b`

## Team

- Josue Aranday
- John Payes
- Alejandro Salinas
- Kevin Gonzalez

Faculty Adviser: Pedro Fonseca

## License

Distributed under the MIT License. See `LICENSE` for more information.
