# realtime.py -- Single-page immediate matching for when the user adds
# a custom URL and wants instant results. Fetches the page, embeds it
# with nomic-embed-text (reusing the embedder module), skips the filter,
# and runs it through phi3 matching (reusing the matcher module).

import hashlib
import sys
import uuid
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ollama_client

from matching.embedder import ensure_model as ensure_embed_model
from matching.embedder import embed_text, load_embeddings, save_embeddings
from matching.matcher import (
    match_page, detect_source_type, format_profile, MATCH_MODEL,
)
from matching.rules import format_hints_for_prompt
from matching.validator import validate_matches, detect_missed_benefits
from matching.pipeline import load_results, save_results, compute_cross_references


# Fetches a URL and returns (title, normalized_text).
# Same normalization as worker_service/worker.py: strip script/style/noscript,
# collapse whitespace.
def fetch_page(url):
    r = requests.get(url, timeout=30)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    text = " ".join(soup.get_text(" ", strip=True).split())
    return title, text


# Embeds the page text and stores the vector in embeddings.json so it's
# cached for future pipeline runs. Uses the embedder module directly.
def embed_single_page(url, title, text, embeddings_path):
    ensure_embed_model()

    text_hash = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()

    embeddings = load_embeddings(embeddings_path)
    existing = embeddings["pages"].get(url)
    if existing and existing.get("text_hash") == text_hash:
        print(f"  Embedding cached (unchanged).")
        return

    print(f"  Embedding page with nomic-embed-text...")
    vector = embed_text(text)
    embeddings["pages"][url] = {
        "title": title,
        "text_hash": text_hash,
        "embedding": vector,
        "embedded_at": datetime.now().isoformat(),
    }
    save_embeddings(embeddings_path, embeddings)


# Matches a single URL immediately against the user's profile.
# Flow: fetch → embed (nomic) → unload nomic → match (phi3) → unload phi3.
# Returns a list of MatchResult objects.
def match_single_page(url, answers, embeddings_path, model=MATCH_MODEL):
    print(f"  Fetching {url}...")
    title, text = fetch_page(url)

    if not text:
        print(f"  No text content found on page.")
        return []

    # Step 1: embed with nomic-embed-text
    embed_single_page(url, title, text, embeddings_path)
    ollama_client.unload_model(ollama_client.EMBED_MODEL)

    # Step 2: match with phi3
    ok, err = ollama_client.check_ollama(model)
    if not ok:
        raise ConnectionError(err)

    profile_text = format_profile(answers)
    hints_text = format_hints_for_prompt(answers)
    source_type = detect_source_type(url)
    run_id = f"rt-{str(uuid.uuid4())[:8]}"

    print(f"  Matching against profile with {model}...")
    results = match_page(
        url, title, text, profile_text, hints_text,
        source_type, run_id, model,
    )

    ollama_client.unload_model(model)

    # Validate matches against the page text we already have in memory
    if results:
        scraped_lookup = {url: (title, text)}
        results, rejected = validate_matches(results, scraped_lookup)
        if rejected:
            print(f"  Rejected {len(rejected)} match(es):")
            for r in rejected:
                reason = getattr(r, "rejection_reason", "unknown")
                print(f"    - {reason}")

    # Detect missed benefits on the page if LLM returned nothing valid
    if not results:
        scraped_lookup = {url: (title, text)}
        keyword_matches = detect_missed_benefits(
            scraped_lookup, answers, [], pipeline_run_id=run_id,
        )
        if keyword_matches:
            print(f"  {len(keyword_matches)} keyword-detected benefit(s):")
            for km in keyword_matches:
                print(f"    + {km.benefit_name}")
            results = keyword_matches

    for r in results:
        print(f"    -> {r.action}: {r.summary[:80]}... (score: {r.relevance_score})")

    if not results:
        print(f"  No benefits found on this page.")

    return results


# Matches a single URL and merges the results into the existing results
# file so they persist alongside pipeline results.
def match_and_save(url, answers, results_path, embeddings_path, model=MATCH_MODEL):
    results = match_single_page(url, answers, embeddings_path, model)

    if results:
        envelope = load_results(results_path)
        existing = list(envelope.results)
        existing.extend(results)
        compute_cross_references(existing)
        envelope.results = existing
        envelope.result_count = len(existing)
        save_results(envelope, results_path)

    return results
