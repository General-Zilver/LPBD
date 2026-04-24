# profile_signal_test_helper.py -- Manual checks for deterministic profile
# signal extraction and deterministic keyword enrichment.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from matching.profile_keywords import build_deterministic_profile_keyword_map
from matching.profile_signals import build_profile_signals


def _flatten_keywords(keyword_map):
    return {
        keyword
        for keywords in (keyword_map or {}).values()
        for keyword in (keywords or [])
    }


def _assert_contains_any(flat_keywords, candidates, label):
    if any(candidate in flat_keywords for candidate in candidates):
        return
    raise AssertionError(f"missing expected keyword group for {label}: {candidates}")


def run_manual_profile_signal_keyword_checks():
    carter_like_answers = {
        "What is your full legal name?": {"Profile": "Carter James Vance"},
        "What is your institution name?": {"Academic": "UTRGV"},
        "What is your residency status?(In-state/ Out-of-state/ International)": {"Profile": "Out-of-state"},
        "What is your current year/classification? (Freshman / Sophomore / Junior / Senior / Graduate)": {"Academic": "Freshman"},
        "Are you enrolled full-time or part-time?": {"Academic": "Full-time"},
        "What is your major or intended major?": {"Academic": "Pre-Med / Biology"},
        "What is your current GPA?": {"Academic": "4.0"},
        "Are you currently receiving any scholarships?": {"Financial Aid & Scholarships": "Yes, a National Merit Scholarship"},
        "Do you live on campus, off campus, or with family?": {"Housing & Food": "On campus in a dorm"},
        "Is there anything else about your situation that you think might be relevant to finding benefits? (open text field)": {
            "Other": "I am in the Honors College and looking for study abroad travel grants."
        },
    }

    elena_like_answers = {
        "What is your full legal name?": {"Profile": "Elena Maria Ramirez"},
        "What is your institution name?": {"Academic": "UTRGV"},
        "Do you have dependents?": {"Profile": "Yes, 1 child"},
        "What is your major or intended major?": {"Academic": "Computer Science"},
        "What is your estimated household income range? (Under $20k / $20k-$40k / $40k-$60k / $60k-$80k / $80k+)": {
            "Financial Aid & Scholarships": "Under $20k"
        },
        "Are you Pell Grant eligible?": {"Financial Aid & Scholarships": "Yes"},
        "Do you know your Student Aid Index (SAI) or expected family contribution?": {"Financial Aid & Scholarships": "0"},
        "Have you experienced food insecurity during your time as a student?": {"Housing & Food": "Yes, often skip meals"},
        "Do you have a personal laptop or computer?": {"Technology & Access": "Mine broke recently, using library computers"},
        "Do you have reliable internet access at home?": {"Technology & Access": "No, phone hotspot only"},
        "Is there anything else about your situation that you think might be relevant to finding benefits? (open text field)": {
            "Other": "Single mother looking for childcare assistance."
        },
    }

    sparse_answers = {
        "What is your institution name?": {"Academic": "UTRGV"},
    }

    carter_signals = build_profile_signals(carter_like_answers)
    carter_map = build_deterministic_profile_keyword_map(carter_signals)
    carter_flat = _flatten_keywords(carter_map)

    _assert_contains_any(carter_flat, {"honors college", "honors scholarship"}, "carter honors")
    _assert_contains_any(carter_flat, {"pre-med", "biology", "pre-health"}, "carter pre-health")
    _assert_contains_any(carter_flat, {"national merit", "national merit scholarship"}, "carter national merit")
    _assert_contains_any(carter_flat, {"out-of-state waiver", "nonresident tuition"}, "carter out-of-state")
    _assert_contains_any(carter_flat, {"residence life"}, "carter residence life")
    _assert_contains_any(carter_flat, {"study abroad", "study abroad grant"}, "carter study abroad")

    elena_signals = build_profile_signals(elena_like_answers)
    elena_map = build_deterministic_profile_keyword_map(elena_signals)
    elena_flat = _flatten_keywords(elena_map)

    _assert_contains_any(elena_flat, {"childcare", "child care"}, "elena childcare")
    _assert_contains_any(elena_flat, {"student parent", "dependent child"}, "elena student parent")
    _assert_contains_any(elena_flat, {"pell grant", "sai 0"}, "elena pell or sai")
    _assert_contains_any(elena_flat, {"food pantry"}, "elena food pantry")
    _assert_contains_any(elena_flat, {"basic needs"}, "elena basic needs")
    _assert_contains_any(elena_flat, {"computer science", "computing"}, "elena computer science")
    _assert_contains_any(elena_flat, {"laptop loan", "technology loan"}, "elena laptop")
    _assert_contains_any(elena_flat, {"hotspot", "hotspot loan"}, "elena hotspot")
    _assert_contains_any(elena_flat, {"low income"}, "elena low-income")

    sparse_signals = build_profile_signals(sparse_answers)
    sparse_map = build_deterministic_profile_keyword_map(sparse_signals)
    if not isinstance(sparse_signals, dict) or not isinstance(sparse_map, dict):
        raise AssertionError("sparse answers should return dict outputs")

    combined_keywords = " ".join(sorted(carter_flat | elena_flat)).lower()
    forbidden_fragments = ["carter", "elena", "ramirez", "@", "555-", "date of birth", "ssn"]
    for fragment in forbidden_fragments:
        if fragment in combined_keywords:
            raise AssertionError(f"private fragment leaked into keywords: {fragment}")

    print("Manual profile signal keyword checks passed.")
    print(f"Carter-like keyword count: {len(carter_flat)}")
    print(f"Elena-like keyword count: {len(elena_flat)}")
    print(f"Sparse keyword count: {len(_flatten_keywords(sparse_map))}")


if __name__ == "__main__":
    run_manual_profile_signal_keyword_checks()
