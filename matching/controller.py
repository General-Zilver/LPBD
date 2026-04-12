# controller.py -- Public interface for the matching pipeline.
# Follows the same pattern as map.py calling mapper.map_domains_batch()
# and scrape_all.py calling the worker service. The root-level match.py
# is a thin wrapper that calls these functions.
#
# Usage from match.py:
#   from matching.controller import run_matching_pipeline, get_status
#   run_matching_pipeline("john_doe", delay=5)

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from matching.models import MatchResultsEnvelope
from matching.pipeline import run_pipeline, load_results, save_results
from matching.realtime import match_and_save

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCRAPED_DIR = PROJECT_ROOT / "scraped_output"
# Realtime single-page mode still uses embeddings cache.
DEFAULT_EMBEDDINGS = PROJECT_ROOT / "embeddings.json"
DEFAULT_RESULTS = PROJECT_ROOT / "matched_benefits.json"
DEFAULT_STATE = PROJECT_ROOT / "pipeline_state.json"


# Loads answers for a specific user from answers.json.
# Shared with match.py -- same lookup logic.
def load_user_answers(username):
    candidates = [
        PROJECT_ROOT / "answers.json",
        PROJECT_ROOT / "GUI" / "answers.json",
    ]
    for path in candidates:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if username in data:
                return data[username]
    return None


# Runs the full matching pipeline: keyword filter -> match.
# This is what match.py calls. Returns the results envelope.
def run_matching_pipeline(
    user,
    model=None,
    delay=5,
    scraped_dir=None,
    output=None,
    verify_pass2=False,
    low_priority=False,
    num_threads=None,
    profile_keywords=True,
):
    answers = load_user_answers(user)
    if not answers:
        raise ValueError(
            f"No answers found for user '{user}'. "
            "Complete the questionnaire in the GUI first."
        )

    s_dir = scraped_dir or DEFAULT_SCRAPED_DIR
    if not s_dir.exists():
        raise FileNotFoundError(
            f"{s_dir} not found. Run `python scrape_all.py` first."
        )

    envelope, _stats = run_pipeline(
        user=user,
        answers=answers,
        scraped_dir=s_dir,
        results_path=output or DEFAULT_RESULTS,
        state_path=DEFAULT_STATE,
        model=model,
        delay=delay,
        verify_pass2=verify_pass2,
        low_priority=low_priority,
        num_threads=num_threads,
        use_profile_keywords=profile_keywords,
    )
    return envelope


# Matches a single URL immediately without the full pipeline.
# Fetches -> embeds (nomic) -> matches (phi3) -> saves results.
# Returns a list of MatchResult objects.
def run_single_page(user, url, model="phi3:mini"):
    answers = load_user_answers(user)
    if not answers:
        raise ValueError(
            f"No answers found for user '{user}'. "
            "Complete the questionnaire in the GUI first."
        )

    return match_and_save(
        url=url,
        answers=answers,
        results_path=DEFAULT_RESULTS,
        embeddings_path=DEFAULT_EMBEDDINGS,
        model=model,
    )


# Returns the current results envelope for the GUI or API to display.
def get_status(user):
    envelope = load_results(DEFAULT_RESULTS)
    return envelope.to_dict()


# Updates a single match's status (new -> seen, dismissed, saved, etc).
# Returns True if the match was found and updated, False otherwise.
def update_match_status(match_id, status):
    valid = ("new", "seen", "dismissed", "saved")
    if status not in valid:
        raise ValueError(f"Invalid status '{status}'. Must be one of: {valid}")

    envelope = load_results(DEFAULT_RESULTS)
    for result in envelope.results:
        if result.match_id == match_id:
            result.status = status
            save_results(envelope, DEFAULT_RESULTS)
            return True
    return False
