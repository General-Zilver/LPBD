# embedder.py -- Generates vector embeddings for scraped page content
# using nomic-embed-text through Ollama. First stage of the matching
# pipeline: reads scraped_output/, embeds each page, saves vectors
# to embeddings.json for the filter stage.

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ollama_client

EMBED_MODEL = ollama_client.EMBED_MODEL


# Checks that nomic-embed-text is pulled, downloads it if missing.
# Raises ConnectionError if Ollama itself isn't running.
def ensure_model():
    ok, err = ollama_client.check_ollama(EMBED_MODEL)
    if ok:
        return

    if "not running" in (err or ""):
        raise ConnectionError(err)

    print(f"  Model '{EMBED_MODEL}' not found. Pulling (this may take a few minutes)...")
    ollama_client.pull_model(EMBED_MODEL)
    print(f"  Model '{EMBED_MODEL}' ready.")




# Caps at 6000 characters for the embedding. This is just Tier 1 similarity
# filtering -- the matcher already chunks full page text for phi3 in Tier 2.
MAX_EMBED_CHARS = 6000

def truncate_for_embedding(text):
    if len(text) <= MAX_EMBED_CHARS:
        return text
    return text[:MAX_EMBED_CHARS]


# Embeds a single text string, returns the float vector.
def embed_text(text):
    return ollama_client.embed(truncate_for_embedding(text), model=EMBED_MODEL)


# Parses scraped output files and yields (url, title, text, text_hash) tuples.
# Same split logic as match.py's load_scraped_pages but also keeps the hash
# so we can skip pages that haven't changed since last embed.
def load_scraped_pages(scraped_dir):
    for filepath in sorted(scraped_dir.glob("scraped_*.txt")):
        content = filepath.read_text(encoding="utf-8")

        pages = re.split(r"\n--- (https?://\S+) ---\n", content)

        for i in range(1, len(pages) - 1, 2):
            url = pages[i]
            body = pages[i + 1]

            title = ""
            text_hash = ""
            text_lines = []
            for line in body.splitlines():
                if line.startswith("Title: "):
                    title = line[7:]
                elif line.startswith("Hash: "):
                    text_hash = line[6:]
                else:
                    text_lines.append(line)

            text = " ".join(text_lines).strip()
            if text:
                yield url, title, text, text_hash


# Loads the embeddings cache from disk, or returns an empty structure.
def load_embeddings(path):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"model": EMBED_MODEL, "updated_at": None, "pages": {}}


# Writes the embeddings dict to disk as JSON.
def save_embeddings(path, embeddings):
    embeddings["updated_at"] = datetime.now().isoformat()
    path.write_text(json.dumps(embeddings), encoding="utf-8")


# Main entry point for the embedding stage.
# Reads all scraped pages, embeds any that are new or changed since last run,
# and saves the updated embeddings to output_path.
# Returns (embedded_count, skipped_count).
def embed_scraped_pages(scraped_dir, output_path, delay=5):
    ensure_model()

    pages = list(load_scraped_pages(scraped_dir))
    if not pages:
        print("  No scraped pages found to embed.")
        return 0, 0

    embeddings = load_embeddings(output_path)
    embedded_count = 0
    skipped_count = 0

    for i, (url, title, text, text_hash) in enumerate(pages, 1):
        existing = embeddings["pages"].get(url)
        if existing and existing.get("text_hash") == text_hash:
            skipped_count += 1
            continue

        print(f"  [{i}/{len(pages)}] Embedding {url}...")

        vector = embed_text(text)
        embeddings["pages"][url] = {
            "title": title,
            "text_hash": text_hash,
            "embedding": vector,
            "embedded_at": datetime.now().isoformat(),
        }
        embedded_count += 1

        # Save after each page so progress survives interruption
        save_embeddings(output_path, embeddings)

        # Delay between embed calls so Ollama isn't overwhelmed
        if i < len(pages):
            time.sleep(delay)

    if skipped_count:
        print(f"  Skipped {skipped_count} unchanged page(s).")

    return embedded_count, skipped_count
