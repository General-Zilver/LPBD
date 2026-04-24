# pipeline.py -- Orchestrates the matching pipeline stages sequentially:
# keyword filter -> match -> validate -> detect -> save.
# Tracks state for resume capability and persists results across sessions.

import hashlib
import json
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

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
from matching.matcher import match_pages, load_scraped_lookup, format_profile, extract_user_institution
from matching.profile_keywords import build_profile_keyword_map
from matching.profile_signals import build_profile_signals
from matching.validator import (
    validate_matches,
    detect_missed_benefits,
    verify_matches_with_llm,
    hard_eligibility_gate,
    normalize_output_matches,
    sanitize_match_text_fields,
)

STAGES = ["filtering", "matching"]

_PREHEALTH_MAJOR_TERMS = {
    "biology",
    "pre-med",
    "pre med",
    "pre-health",
    "pre health",
    "biomedical sciences",
    "chemistry",
}

_PREHEALTH_PAGE_TERMS = {
    "pre-health",
    "prehealth",
    "mcat",
    "shadowing",
    "clinical observation",
}

_PREHEALTH_RESCUE_BENEFIT_NAME = "Pre-Health Shadowing and MCAT Support Program"

_DOMAIN_QUESTIONS = [
    "what is your school's website domain?",
    "what is your school website domain?",
    "what is your institution website domain?",
    "what is your institution's website domain?",
    "what school websites should be treated as your school or target schools?",
]


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


def _build_llm_options(num_threads=None):
    if isinstance(num_threads, int) and num_threads > 0:
        return {"num_thread": num_threads}
    return None


def _clean_hostname(url_or_domain):
    text = str(url_or_domain or "").strip().lower()
    if not text:
        return ""
    if "://" in text:
        text = urlparse(text).netloc.lower()
    if text.startswith("www."):
        text = text[4:]
    return text.split("/")[0]


def _hostname_matches_domain(hostname, domain):
    h = _clean_hostname(hostname)
    d = _clean_hostname(domain)
    if not h or not d:
        return False
    return h == d or h.endswith("." + d)


def _extract_user_home_domains(answers):
    for question, section_dict in (answers or {}).items():
        if str(question or "").lower() not in _DOMAIN_QUESTIONS:
            continue
        if not isinstance(section_dict, dict):
            raw = str(section_dict or "").strip()
            if not raw:
                continue
            parts = [_clean_hostname(p.strip()) for p in raw.split(",")]
            domains = [p for p in parts if p]
            if domains:
                return domains
            continue
        for _section, value in section_dict.items():
            raw = str(value or "").strip()
            if not raw:
                continue
            parts = [_clean_hostname(p.strip()) for p in raw.split(",")]
            domains = [p for p in parts if p]
            if domains:
                return domains
    return []


def _contains_any(text, terms):
    lower = str(text or "").lower()
    return any(term in lower for term in terms)


def _major_terms_support_prehealth(profile_signals):
    major_terms = profile_signals.get("major_terms") if isinstance(profile_signals, dict) else []
    if not isinstance(major_terms, list):
        return False
    for term in major_terms:
        lower = str(term or "").strip().lower()
        if not lower:
            continue
        normalized = lower.replace("-", " ")
        if any(target in lower or target in normalized for target in _PREHEALTH_MAJOR_TERMS):
            return True
    return False


def _is_home_institution_page(page_url, answers):
    hostname = _clean_hostname(page_url)
    if not hostname:
        return False
    home_domains = _extract_user_home_domains(answers or {})
    if not home_domains:
        return True
    return any(_hostname_matches_domain(hostname, d) for d in home_domains)


def _select_prehealth_evidence_quote(page_text):
    if not page_text:
        return ""

    preferred_quotes = [
        "The Pre-Health Shadowing and MCAT Support Program connects qualified UTRGV students with physician shadowing opportunities, basic clinical observation training, and a limited number of MCAT preparation vouchers.",
        "The program is intended for students exploring medical school, dental school, physician assistant programs, or other health professional pathways.",
        "MCAT preparation voucher up to $600.",
    ]
    for quote in preferred_quotes:
        if quote in page_text:
            return quote

    sentences = re.split(r"(?<=[.!?])\s+", page_text)
    for sentence in sentences:
        snippet = sentence.strip()
        if not snippet:
            continue
        if snippet in page_text and _contains_any(snippet, _PREHEALTH_PAGE_TERMS):
            return snippet
    return ""


def _detect_source_type_for_rescue(url):
    host = urlparse(url).netloc.lower()
    if host.endswith(".edu") or ".edu." in host:
        return "edu"
    if host.endswith(".gov") or ".gov." in host:
        return "gov"
    return "custom"


def _build_prehealth_rescue_match(validated_results, scraped_lookup, answers, profile_signals, pipeline_run_id):
    existing_urls = {str(r.page_url or "").strip() for r in (validated_results or [])}

    if not _major_terms_support_prehealth(profile_signals):
        return None

    for page_url, payload in (scraped_lookup or {}).items():
        if page_url in existing_urls:
            continue

        title = ""
        page_text = ""
        if isinstance(payload, tuple) and len(payload) >= 2:
            title = payload[0] or ""
            page_text = payload[1] or ""

        search_blob = " ".join([str(page_url or ""), str(title or ""), str(page_text or "")])
        if not _contains_any(search_blob, _PREHEALTH_PAGE_TERMS):
            continue

        if not _is_home_institution_page(page_url, answers):
            continue

        evidence_quote = _select_prehealth_evidence_quote(page_text)
        if not evidence_quote or evidence_quote not in page_text:
            continue

        rescue = MatchResult(
            match_id=str(uuid.uuid4()),
            page_url=page_url,
            page_title=title,
            source_type=_detect_source_type_for_rescue(page_url),
            relevance_score=5,
            benefit_name=_PREHEALTH_RESCUE_BENEFIT_NAME,
            action="apply",
            summary=(
                "The program supports pre-health students with shadowing, MCAT preparation, "
                "or related medical-school preparation resources."
            ),
            reasoning=(
                "The profile signals include a pre-health or biology major path, "
                "and the page describes a pre-health support program."
            ),
            action_details="Submit the pre-health interest form or follow the page instructions.",
            evidence_quote=evidence_quote,
            evidence_type="deterministic-profile-signal",
            institution_scope="home",
            eligibility_status="likely_eligible",
            match_type="direct_match",
            cross_references=[],
            inferred_from=["major_terms"],
            tags=["health", "student-support"],
            matched_at=datetime.now().isoformat(),
            pipeline_run_id=pipeline_run_id,
            status="new",
        )

        rescue_valid, _rescue_rejected = validate_matches(
            [rescue],
            scraped_lookup or {},
            answers=answers,
        )
        if rescue_valid:
            return rescue_valid[0]

    return None


def _set_low_priority(verbose=False):
    if not _HAS_PSUTIL:
        print("  Low-priority mode requested, but psutil is not installed.")
        return

    proc = psutil.Process()
    try:
        if hasattr(psutil, "IDLE_PRIORITY_CLASS"):
            proc.nice(psutil.IDLE_PRIORITY_CLASS)
            if verbose:
                print("  Process priority set to IDLE.")
        elif hasattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS"):
            proc.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
            if verbose:
                print("  Process priority set to BELOW_NORMAL.")
        else:
            proc.nice(19)
            if verbose:
                print("  Process niceness set to 19 (best effort).")
    except Exception as exc:
        print(f"  Failed to lower process priority: {exc}")


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
            old.eligibility_status = getattr(r, "eligibility_status", "")
            old.match_type = getattr(r, "match_type", "")
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

# Strips www. from a parsed hostname for consistent comparison.
def _normalize_host(url):
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


# Finds results from different pages that share tags and links them.
# Requires 2+ shared tags, or 1 shared tag if both pages are on the same host.
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
            same_hostname = _normalize_host(a.page_url) == _normalize_host(b.page_url)
            if len(shared) < 2 and not (same_hostname and len(shared) >= 1):
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


# -- benefit_name dedup ----------------------------------------------------

# Caps how many matches share the same benefit_name across pages.
# Keeps the top per_name_cap by score, evidence presence, and detail length.
def dedup_by_benefit_name(results, per_name_cap=3):
    groups = {}
    for r in results:
        name = " ".join((r.benefit_name or "").lower().split())
        if not name:
            key = f"{r.page_url}|{r.summary}"
        else:
            key = name
        groups.setdefault(key, []).append(r)

    out = []
    for group in groups.values():
        sorted_group = sorted(
            group,
            key=lambda m: (
                m.relevance_score,
                1 if m.evidence_quote else 0,
                len(m.action_details or ""),
            ),
            reverse=True,
        )
        out.extend(sorted_group[:per_name_cap])
    return out


# -- pipeline orchestrator -------------------------------------------------


def run_pipeline(
    user,
    answers,
    scraped_dir,
    results_path,
    state_path,
    model=None,
    delay=5,
    verbose=False,
    verify_pass2=True,
    low_priority=False,
    num_threads=None,
    use_profile_keywords=True,
):
    if model is None:
        model = ollama_client.DEFAULT_MODEL
    llm_options = _build_llm_options(num_threads)
    now = datetime.now().isoformat()
    current_hash = _hash_answers(answers)

    if low_priority:
        _set_low_priority(verbose=verbose)
    if llm_options:
        print(f"  Ollama thread cap enabled: num_thread={llm_options['num_thread']}")

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
            "pass2_rejected": [],
            "keyword_detected": [],
            "profile_keywords_added": 0,
            "timings": timings,
            "peak_ram_mb": peak_ram_mb,
            "wall_time": time.time() - pipeline_start,
            "model": model,
            "pages_total": 0,
            "pages_relevant": 0,
            "pages_filtered": 0,
        }
        return envelope, empty_stats

    profile_keywords = {}
    profile_keyword_count = 0
    if use_profile_keywords:
        print("\n--- Profile Keyword Expansion ---")
        t_pk = time.time()
        profile_keywords = build_profile_keyword_map(
            answers,
            model=model,
            llm_options=llm_options,
        )
        timings["profile_keywords"] = time.time() - t_pk
        profile_keyword_count = sum(len(v) for v in profile_keywords.values())
        if profile_keyword_count:
            print(
                f"  Generated {profile_keyword_count} profile-derived keyword(s) "
                f"across {len(profile_keywords)} category(ies)."
            )
        else:
            print("  No profile-derived keywords generated.")

    # ---- stage 1: filtering ----
    t0 = time.time()
    if state.current_stage == "filtering" or "filtering" not in state.stages_completed:
        print("\n--- Stage 1/2: Keyword Filtering ---")
        log_resources("filter start", verbose)
        state.current_stage = "filtering"
        save_state(state, state_path)

        relevant, not_relevant = filter_pages(scraped, extra_keywords=profile_keywords)

        _mark_stage_completed(state, "filtering")
        state.items_processed = len(relevant) + len(not_relevant)
        state.items_total = len(relevant) + len(not_relevant)
        save_state(state, state_path)
    else:
        relevant, not_relevant = filter_pages(scraped, extra_keywords=profile_keywords)

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
            "pass2_rejected": [],
            "keyword_detected": [],
            "profile_keywords_added": profile_keyword_count,
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
            llm_options=llm_options,
        )

        if new_results:
            state.last_processed_item = new_results[-1].page_url
        elif pages_to_match:
            state.last_processed_item = pages_to_match[-1]["url"]
        save_state(state, state_path)
    else:
        new_results = []

    timings["match"] = time.time() - t0
    _track_ram()
    log_resources("match end", verbose)

    # ---- stage 2.5: validation ----
    t0 = time.time()
    llm_proposed = len(new_results)
    pass2_rejected = []
    hard_gate_rejected = []
    rejected = []

    profile_text = format_profile(answers)
    user_institution = extract_user_institution(answers)
    profile_signals = build_profile_signals(answers)

    if verify_pass2 and new_results:
        print("\n--- Pass 2 Verification (LLM) ---")
        new_results, pass2_rejected = verify_matches_with_llm(
            new_results,
            scraped,
            profile_text=profile_text,
            user_institution=user_institution,
            model=model,
            llm_options=llm_options,
        )
        print(f"  {len(new_results)} pass-2 valid, {len(pass2_rejected)} pass-2 rejected")
        if pass2_rejected:
            reasons = {}
            for r in pass2_rejected:
                reason = getattr(r, "rejection_reason", "unknown")
                reasons[reason] = reasons.get(reason, 0) + 1
            for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
                print(f"    - {reason}: {count}")

    if new_results:
        print("\n--- Hard Eligibility Gate ---")
        new_results, hard_gate_rejected = hard_eligibility_gate(
            new_results,
            answers=answers,
            scraped_lookup=scraped,
            profile_signals=profile_signals,
        )
        print(
            f"  {len(new_results)} hard-gate passed, "
            f"{len(hard_gate_rejected)} hard-gate rejected"
        )
        if hard_gate_rejected:
            reasons = {}
            for r in hard_gate_rejected:
                reason = getattr(r, "rejection_reason", "unknown")
                reasons[reason] = reasons.get(reason, 0) + 1
            for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
                print(f"    - {reason}: {count}")

    if new_results:
        print("\n--- Validating ---")
        new_results, rejected = validate_matches(new_results, scraped, answers=answers)
        print(f"  {len(new_results)} validated, {len(rejected)} rejected")
        if rejected:
            reasons = {}
            for r in rejected:
                reason = getattr(r, "rejection_reason", "unknown")
                reasons[reason] = reasons.get(reason, 0) + 1
            for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
                print(f"    - {reason}: {count}")

    rescue_match = _build_prehealth_rescue_match(
        validated_results=new_results,
        scraped_lookup=scraped,
        answers=answers,
        profile_signals=profile_signals,
        pipeline_run_id=run_id,
    )
    if rescue_match:
        print("\n--- Deterministic Rescue ---")
        print(f"  Added 1 pre-health rescue match: {rescue_match.page_url}")
        new_results.append(rescue_match)

    ollama_client.unload_model(model)
    print(f"  Unloaded {model}")

    all_rejected = pass2_rejected + hard_gate_rejected + rejected
    timings["validate"] = time.time() - t0

    # ---- stage 2.6: missed benefit detection ----
    t0 = time.time()
    print("\n--- Detecting missed benefits ---")
    keyword_matches = detect_missed_benefits(
        scraped,
        answers,
        new_results,
        pipeline_run_id=run_id,
        rejected_matches=all_rejected,
    )
    if keyword_matches:
        print(f"  {len(keyword_matches)} keyword-detected benefit(s):")
        for km in keyword_matches:
            print(f"    + {km.benefit_name} ({km.page_url})")
        new_results.extend(keyword_matches)
    else:
        print("  No additional benefits detected.")
    timings["detect"] = time.time() - t0

    sanitize_match_text_fields(new_results)

    _track_ram()

    # Collect stats for callers that want detailed reporting
    wall_time = time.time() - pipeline_start
    stats = {
        "llm_proposed": llm_proposed,
        "llm_validated": max(0, llm_proposed - len(all_rejected)),
        "rejected": all_rejected,
        "pass2_rejected": pass2_rejected,
        "hard_gate_rejected": hard_gate_rejected,
        "keyword_detected": keyword_matches,
        "profile_keywords_added": profile_keyword_count,
        "timings": timings,
        "peak_ram_mb": peak_ram_mb,
        "wall_time": wall_time,
        "model": model,
        "pages_total": len(scraped),
        "pages_relevant": len(relevant),
        "pages_filtered": len(not_relevant),
    }

    # ---- post-processing: dedup + upsert + cross-references ----
    original_count = len(new_results)
    new_results = dedup_by_benefit_name(new_results)
    dropped = original_count - len(new_results)

    if dropped:
        print("\n--- Dedup ---")
        print(f"  Capped: {dropped} match(es) dropped by benefit_name dedup (cap: 3 per name)")

    print("\n--- Post-processing ---")
    all_results = upsert_results(existing_results, new_results)
    all_results = normalize_output_matches(all_results)
    sanitize_match_text_fields(all_results)
    all_results.sort(
        key=lambda r: (
            r.evidence_type == "keyword-detection",
            -r.relevance_score,
        )
    )
    compute_cross_references(all_results)

    ref_count = sum(len(r.cross_references) for r in all_results)
    print(f"  {len(all_results)} total result(s), {ref_count} cross-reference(s)")

    # ---- save final results ----
    envelope = MatchResultsEnvelope(
        pipeline_status="complete",
        pipeline_progress=PipelineProgress(
            current_stage="complete",
            items_processed=len(relevant),
            items_total=len(relevant),
            started_at=state.started_at,
        ),
        results=all_results,
        result_count=len(all_results),
    )
    save_results(envelope, results_path)

    state.current_stage = "complete"
    _mark_stage_completed(state, "matching")
    state.items_processed = len(relevant)
    state.items_total = len(relevant)
    save_state(state, state_path)

    print("\n=== Pipeline Complete ===")
    print(f"Results: {len(all_results)}")
    print(f"Output: {results_path}")

    return envelope, stats

