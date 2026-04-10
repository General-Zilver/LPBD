# pipeline.py -- Orchestrates the matching pipeline stages sequentially:
# keyword filter -> match -> validate -> detect -> save.
# Tracks state for resume capability and persists results across sessions.

import hashlib
import json
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ollama_client

try:
    import psutil

    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

from matching.models import (
    MatchResult,
    CrossReference,
    PipelineState,
    PipelineProgress,
    MatchResultsEnvelope,
)
from matching.filter import filter_pages
from matching.matcher import match_pages, load_scraped_lookup
from matching.validator import validate_matches, detect_missed_benefits

STAGES = ["filtering", "matching"]


# Prints one line of resource stats: RAM, CPU, and which Ollama model is loaded.
# Only does anything when verbose=True and psutil is available.
def log_resources(label, verbose=False, expected_model=None):
    if not verbose or not _HAS_PSUTIL:
        return
    proc = psutil.Process()
    mem_mb = proc.memory_info().rss / (1024 * 1024)
    cpu = psutil.cpu_percent(interval=0.1)
    ollama_info = ""
    try:
        import requests as _req

        r = _req.get(f"{ollama_client.OLLAMA_BASE}/api/ps", timeout=3)
        if r.ok:
            models = r.json().get("models", [])
            if models:
                parts = []
                for m in models:
                    name = m.get("name", "?")
                    size_mb = m.get("size", 0) / (1024 * 1024)
                    parts.append(f"{name} ({size_mb:.0f}MB)")
                ollama_info = f" | ollama: {', '.join(parts)}"
            else:
                if expected_model:
                    ollama_info = f" | ollama: no model loaded (will load {expected_model} on first call)"
                else:
                    ollama_info = " | ollama: no model loaded"
    except Exception:
        ollama_info = " | ollama: unreachable"
    print(f"  [{label}] RAM: {mem_mb:.0f}MB | CPU: {cpu:.0f}%{ollama_info}")


# Stable hash of the answers dict so we can detect profile changes between runs.
def _hash_answers(answers):
    raw = json.dumps(answers, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# Legacy compatibility: older state files may contain "embedding" stage.
def _normalize_state_for_keyword_pipeline(state):
    changed = False

    if state.current_stage == "embedding":
        state.current_stage = "filtering"
        changed = True

    if state.current_stage not in ("filtering", "matching", "complete"):
        state.current_stage = "filtering"
        changed = True

    normalized = []
    for stage in state.stages_completed:
        mapped = "filtering" if stage == "embedding" else stage
        if mapped in STAGES and mapped not in normalized:
            normalized.append(mapped)

    if normalized != state.stages_completed:
        state.stages_completed = normalized
        changed = True

    return changed


def _mark_stage_completed(state, stage):
    if stage not in state.stages_completed:
        state.stages_completed.append(stage)


# -- state persistence -----------------------------------------------------

# Loads pipeline state from disk if a previous run exists.
def load_state(path):
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return PipelineState.from_dict(data)
    return None


# Saves pipeline state to disk after each progress update.
def save_state(state, path):
    state.updated_at = datetime.now().isoformat()
    path.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")


# -- results persistence ---------------------------------------------------

# Loads existing match results from disk if available.
def load_results(path):
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return MatchResultsEnvelope.from_dict(data)
    return MatchResultsEnvelope(pipeline_status="idle")


# Saves the results envelope to disk.
def save_results(envelope, path):
    envelope.last_updated = datetime.now().isoformat()
    envelope.result_count = len(envelope.results)
    path.write_text(json.dumps(envelope.to_dict(), indent=2), encoding="utf-8")


# -- upsert logic ----------------------------------------------------------

# Stable key for matching the same benefit across pipeline runs.
# Two results are "the same" if they come from the same page, recommend
# the same action, and share the same tag set.
def _result_key(r):
    if isinstance(r, MatchResult):
        return (r.page_url, r.action, tuple(sorted(r.tags)))
    return (r.get("page_url"), r.get("action"), tuple(sorted(r.get("tags", []))))


# Merges new results into existing ones. Preserves user-set statuses
# (seen / dismissed / saved) so re-runs don't wipe user decisions.
def upsert_results(existing, new_results):
    by_key = {}
    for r in existing:
        by_key[_result_key(r)] = r

    merged = []
    seen_keys = set()

    for r in new_results:
        key = _result_key(r)
        seen_keys.add(key)
        old = by_key.get(key)
        if old and old.status in ("seen", "dismissed", "saved"):
            # Keep user's status, refresh the content
            old.relevance_score = r.relevance_score
            old.summary = r.summary
            old.reasoning = r.reasoning
            old.action_details = r.action_details
            old.inferred_from = r.inferred_from
            old.matched_at = r.matched_at
            old.pipeline_run_id = r.pipeline_run_id
            merged.append(old)
        else:
            merged.append(r)

    # Retain results the user explicitly saved or dismissed even if they
    # didn't appear in the new run (page may have been filtered out).
    for r in existing:
        key = _result_key(r)
        if key not in seen_keys and r.status in ("saved", "dismissed"):
            merged.append(r)

    return merged


# -- cross-references ------------------------------------------------------

# Finds results from different pages that share tags and links them.
def compute_cross_references(results):
    for r in results:
        r.cross_references = []

    for i, a in enumerate(results):
        if not a.tags:
            continue
        for b in results[i + 1 :]:
            if a.page_url == b.page_url:
                continue
            shared = set(a.tags) & set(b.tags)
            if not shared:
                continue
            tag_str = ", ".join(sorted(shared))
            a.cross_references.append(
                CrossReference(
                    match_id=b.match_id,
                    relationship=f"Related benefit ({tag_str})",
                )
            )
            b.cross_references.append(
                CrossReference(
                    match_id=a.match_id,
                    relationship=f"Related benefit ({tag_str})",
                )
            )


# -- pipeline orchestrator -------------------------------------------------


def run_pipeline(user, answers, scraped_dir, results_path, state_path, model=None, delay=5, verbose=False):
    if model is None:
        model = ollama_client.DEFAULT_MODEL
    now = datetime.now().isoformat()
    current_hash = _hash_answers(answers)

    # Try to resume a previous run
    state = load_state(state_path)
    resuming = False

    if state and _normalize_state_for_keyword_pipeline(state):
        save_state(state, state_path)

    if state and state.user == user and state.current_stage != "complete":
        # Check if answers changed mid-run -- restart filter+match if so
        if state.answers_hash and state.answers_hash != current_hash:
            print("Answers changed since last run - will re-filter and re-match all pages")
            state.stages_completed = []
            state.current_stage = "filtering"
            state.last_processed_item = None
            state.answers_hash = current_hash
            state.model = model
            save_state(state, state_path)
            run_id = state.run_id
        else:
            resuming = True
            run_id = state.run_id
            state.model = model
            save_state(state, state_path)
            print(f"Resuming pipeline run {run_id} from stage: {state.current_stage}")
    elif state and state.user == user and state.current_stage == "complete":
        # Previous run finished -- check if answers changed since then
        prior_hash = state.answers_hash
        run_id = str(uuid.uuid4())[:8]
        state = PipelineState(
            run_id=run_id,
            user=user,
            model=model,
            current_stage="filtering",
            answers_hash=current_hash,
            stages_completed=[],
            started_at=now,
        )
        save_state(state, state_path)
        if prior_hash and prior_hash != current_hash:
            print("Answers changed since last run - re-filtering and re-matching all pages")
        else:
            print(f"Starting pipeline run {run_id}")
    else:
        run_id = str(uuid.uuid4())[:8]
        state = PipelineState(
            run_id=run_id,
            user=user,
            model=model,
            current_stage="filtering",
            answers_hash=current_hash,
            started_at=now,
        )
        save_state(state, state_path)
        print(f"Starting pipeline run {run_id}")

    pipeline_start = time.time()
    timings = {}
    peak_ram_mb = 0

    def _track_ram():
        nonlocal peak_ram_mb
        if _HAS_PSUTIL:
            current = psutil.Process().memory_info().rss / (1024 * 1024)
            if current > peak_ram_mb:
                peak_ram_mb = current

    scraped = load_scraped_lookup(scraped_dir)
    if not scraped:
        print("No scraped pages found. Run `python scrape_all.py` first.")
        state.current_stage = "complete"
        _mark_stage_completed(state, "matching")
        save_state(state, state_path)

        envelope = load_results(results_path)
        envelope.pipeline_status = "complete"
        save_results(envelope, results_path)
        empty_stats = {
            "llm_proposed": 0,
            "llm_validated": 0,
            "rejected": [],
            "keyword_detected": [],
            "timings": timings,
            "peak_ram_mb": peak_ram_mb,
            "wall_time": time.time() - pipeline_start,
            "model": model,
            "pages_total": 0,
            "pages_relevant": 0,
            "pages_filtered": 0,
        }
        return envelope, empty_stats

    # ---- stage 1: filtering ----
    t0 = time.time()
    if state.current_stage == "filtering" or "filtering" not in state.stages_completed:
        print("\n--- Stage 1/2: Keyword Filtering ---")
        log_resources("filter start", verbose)
        state.current_stage = "filtering"
        save_state(state, state_path)

        relevant, not_relevant = filter_pages(scraped)

        _mark_stage_completed(state, "filtering")
        state.items_processed = len(relevant) + len(not_relevant)
        state.items_total = len(relevant) + len(not_relevant)
        save_state(state, state_path)
    else:
        relevant, not_relevant = filter_pages(scraped)

    timings["filter"] = time.time() - t0
    _track_ram()
    log_resources("filter end", verbose)

    if not relevant:
        print("\nNo pages passed the keyword filter. Pipeline complete with no matches.")
        state.current_stage = "complete"
        _mark_stage_completed(state, "matching")
        save_state(state, state_path)

        envelope = load_results(results_path)
        envelope.pipeline_status = "complete"
        save_results(envelope, results_path)
        empty_stats = {
            "llm_proposed": 0,
            "llm_validated": 0,
            "rejected": [],
            "keyword_detected": [],
            "timings": timings,
            "peak_ram_mb": peak_ram_mb,
            "wall_time": time.time() - pipeline_start,
            "model": model,
            "pages_total": len(scraped),
            "pages_relevant": 0,
            "pages_filtered": len(not_relevant),
        }
        return envelope, empty_stats

    # ---- stage 2: matching ----
    print(f"\n--- Stage 2/2: Matching ({len(relevant)} pages) ---")
    log_resources("match start", verbose, expected_model=model)
    t0 = time.time()
    state.current_stage = "matching"
    save_state(state, state_path)

    pages_to_match = relevant
    if resuming and state.last_processed_item:
        last_url = state.last_processed_item
        try:
            idx = next(i for i, p in enumerate(relevant) if p["url"] == last_url)
            pages_to_match = relevant[idx + 1 :]
            print(f"  Resuming after {last_url} ({len(pages_to_match)} remaining)")
        except StopIteration:
            pass

    envelope = load_results(results_path)
    existing_results = list(envelope.results)

    if pages_to_match:
        new_results = match_pages(
            answers,
            pages_to_match,
            scraped_lookup=scraped,
            pipeline_run_id=run_id,
            model=model,
            delay=delay,
        )

        if new_results:
            state.last_processed_item = new_results[-1].page_url
        elif pages_to_match:
            state.last_processed_item = pages_to_match[-1]["url"]
        save_state(state, state_path)
    else:
        new_results = []

    ollama_client.unload_model(model)
    print(f"  Unloaded {model}")

    timings["match"] = time.time() - t0
    _track_ram()
    log_resources("match end", verbose)

    # ---- stage 2.5: validation ----
    t0 = time.time()
    llm_proposed = len(new_results)
    rejected = []
    if new_results:
        print("\n--- Validating ---")
        new_results, rejected = validate_matches(new_results, scraped)
        print(f"  {len(new_results)} validated, {len(rejected)} rejected")
        if rejected:
            reasons = {}
            for r in rejected:
                reason = getattr(r, "rejection_reason", "unknown")
                reasons[reason] = reasons.get(reason, 0) + 1
            for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
                print(f"    - {reason}: {count}")
    timings["validate"] = time.time() - t0

    # ---- stage 2.6: missed benefit detection ----
    t0 = time.time()
    print("\n--- Detecting missed benefits ---")
    keyword_matches = detect_missed_benefits(
        scraped,
        answers,
        new_results,
        pipeline_run_id=run_id,
    )
    if keyword_matches:
        print(f"  {len(keyword_matches)} keyword-detected benefit(s):")
        for km in keyword_matches:
            print(f"    + {km.benefit_name} ({km.page_url})")
        new_results.extend(keyword_matches)
    else:
        print("  No additional benefits detected.")
    timings["detect"] = time.time() - t0

    _track_ram()

    # Collect stats for callers that want detailed reporting
    wall_time = time.time() - pipeline_start
    stats = {
        "llm_proposed": llm_proposed,
        "llm_validated": llm_proposed - len(rejected),
        "rejected": rejected,
        "keyword_detected": keyword_matches,
        "timings": timings,
        "peak_ram_mb": peak_ram_mb,
        "wall_time": wall_time,
        "model": model,
        "pages_total": len(scraped),
        "pages_relevant": len(relevant),
        "pages_filtered": len(not_relevant),
    }

    # ---- post-processing: upsert + cross-references ----
    print("\n--- Post-processing ---")
    merged = upsert_results(existing_results, new_results)
    compute_cross_references(merged)

    ref_count = sum(len(r.cross_references) for r in merged)
    print(f"  {len(merged)} total result(s), {ref_count} cross-reference(s)")

    # ---- save final results ----
    envelope = MatchResultsEnvelope(
        pipeline_status="complete",
        pipeline_progress=PipelineProgress(
            current_stage="complete",
            items_processed=len(relevant),
            items_total=len(relevant),
            started_at=state.started_at,
        ),
        results=merged,
        result_count=len(merged),
    )
    save_results(envelope, results_path)

    state.current_stage = "complete"
    _mark_stage_completed(state, "matching")
    state.items_processed = len(relevant)
    state.items_total = len(relevant)
    save_state(state, state_path)

    print("\n=== Pipeline Complete ===")
    print(f"Results: {len(merged)}")
    print(f"Output: {results_path}")

    return envelope, stats
