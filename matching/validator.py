# validator.py -- Post-match validation for the matching pipeline.
# Runs after matcher.py produces results and before post-processing/save.
# Part 1: validate_matches — checks evidence grounding, action normalization,
# required fields, tag cleaning, and domain-specific rules.
# Part 2: detect_missed_benefits — keyword-based safety net for obvious
# benefits the LLM missed or that were all rejected by validation.

import re
import uuid
from datetime import datetime
from urllib.parse import urlparse

from matching.models import MatchResult


# -- allowed values --------------------------------------------------------

ALLOWED_ACTIONS = {"apply", "opt-in", "opt-out", "contact", "review", "be-aware"}

ALLOWED_TAGS = {
    "scholarship", "grant", "loan", "work-study", "financial-aid", "tuition",
    "deadline", "health", "mental-health", "counseling", "housing",
    "employment", "accessibility", "veteran", "childcare", "emergency",
    "student-support", "other",
}

# Maps common LLM near-misses to the correct allowed action.
ACTION_NORMALIZATIONS = {
    "apply-for": "apply",
    "apply for": "apply",
    "enroll": "apply",
    "sign-up": "apply",
    "sign up": "apply",
    "register": "apply",
    "opt-in/apply": "apply",
    "opt in": "opt-in",
    "optin": "opt-in",
    "opt out": "opt-out",
    "optout": "opt-out",
    "waive": "opt-out",
    "decline": "opt-out",
    "contact-to-inquire": "contact",
    "inquire": "contact",
    "reach-out": "contact",
    "reach out": "contact",
    "check": "review",
    "look-into": "review",
    "look into": "review",
    "investigate": "review",
    "explore": "review",
    "be aware": "be-aware",
    "aware": "be-aware",
    "note": "be-aware",
    "inform": "be-aware",
    "not-relevant": None,
    "not relevant": None,
}

# Words that must appear in the page text for an opt-out action to be valid.
OPT_OUT_SIGNALS = [
    "opt-out", "opt out", "waiver", "waive", "decline",
    "default enrollment", "auto-enroll", "automatically enrolled",
]

# Academic program keywords that trigger the academic program filter.
ACADEMIC_PROGRAM_WORDS = [
    "degree", "certificate", "major", "minor", "concentration",
    "bachelor", "master", "doctoral", "ph.d", "program of study",
]

# Words that exempt a match from the academic program filter.
FUNDING_EXEMPTIONS = [
    "scholarship", "grant", "aid", "waiver", "stipend", "fellowship",
    "assistantship", "funding", "tuition", "fee waiver",
]


# -- action normalization --------------------------------------------------

# Normalizes near-miss action values to allowed ones.
# Returns (normalized_action, None) on success or (None, reason) on rejection.
def _normalize_action(action):
    if action is None:
        return None, "action is None"
    if isinstance(action, list):
        action = action[0] if action else ""
    if not action:
        return None, "empty action"

    clean = str(action).strip().lower()

    if clean in ALLOWED_ACTIONS:
        return clean, None

    normalized = ACTION_NORMALIZATIONS.get(clean)
    if normalized:
        return normalized, None
    if normalized is None and clean in ACTION_NORMALIZATIONS:
        return None, f"action '{action}' maps to not-relevant"

    return None, f"unrecognized action '{action}'"


# -- evidence checks -------------------------------------------------------

# Checks if the evidence quote actually appears in the page text.
# First tries exact substring. Falls back to fuzzy word overlap.
def _check_evidence(evidence_quote, page_text):
    if not evidence_quote or not evidence_quote.strip():
        return False, "empty evidence_quote"

    quote_lower = evidence_quote.strip().lower()
    page_lower = page_text.lower()

    # Exact substring match
    if quote_lower in page_lower:
        return True, None

    # Fuzzy: check if 60%+ of evidence words appear in a window of the page
    quote_words = quote_lower.split()
    if not quote_words:
        return False, "evidence_quote has no words"

    page_words = page_lower.split()
    page_word_set = set(page_words)
    found = sum(1 for w in quote_words if w in page_word_set)
    ratio = found / len(quote_words)

    if ratio >= 0.6:
        return True, None

    return False, f"evidence not grounded in page text ({ratio:.0%} word overlap)"


# -- opt-out validation ----------------------------------------------------

# Makes sure the page actually talks about opting out or waiving something.
def _check_opt_out(page_text):
    lower = page_text.lower()
    for signal in OPT_OUT_SIGNALS:
        if signal in lower:
            return True
    return False


# -- academic program filter -----------------------------------------------

# Checks if a match is just describing a degree/program rather than a benefit.
# Returns True if the match should be REJECTED.
def _is_academic_program_match(match, page_title, page_url):
    url_lower = page_url.lower()
    title_lower = (page_title or "").lower()

    # Check if the page is an academic/program page
    academic_url_signals = ["graduate", "deadlines", "application-deadlines",
                            "programs", "academics", "catalog"]
    page_is_academic = any(s in url_lower or s in title_lower
                           for s in academic_url_signals)

    if not page_is_academic:
        return False

    # Check if the match references academic program concepts
    match_text = f"{match.benefit_name} {match.summary}".lower()
    references_program = any(w in match_text for w in ACADEMIC_PROGRAM_WORDS)

    if not references_program:
        return False

    # Exempt if it specifically references funding tied to the program
    has_funding_tie = any(w in match_text for w in FUNDING_EXEMPTIONS)
    return not has_funding_tie


# -- tag validation --------------------------------------------------------

# Strips any tags not in the allowed set. Returns the cleaned list.
def _clean_tags(tags):
    return [t for t in tags if t in ALLOWED_TAGS]


# -- main validator --------------------------------------------------------

# Validates proposed matches from the matcher. Returns (valid, rejected).
# Each rejected match gets a rejection_reason attribute.
# scraped_lookup: {url: (title, text)} from matcher.load_scraped_lookup.
def validate_matches(matches, scraped_lookup):
    valid = []
    rejected = []

    for match in matches:
        reason = _validate_single(match, scraped_lookup)
        if reason:
            match.rejection_reason = reason
            rejected.append(match)
        else:
            valid.append(match)

    return valid, rejected


# Runs all validation checks on a single match.
# Returns a rejection reason string, or None if the match is valid.
def _validate_single(match, scraped_lookup):
    # 1. Required fields
    if not match.benefit_name or not match.benefit_name.strip():
        return "missing benefit_name"
    if not match.summary or not match.summary.strip():
        return "missing summary"
    if not match.reasoning or not match.reasoning.strip():
        return "missing reasoning"

    # 2. Action normalization
    normalized, action_err = _normalize_action(match.action)
    if action_err:
        return f"invalid action: {action_err}"
    match.action = normalized

    # 3. Evidence check
    page_entry = scraped_lookup.get(match.page_url)
    if not page_entry:
        return f"page not found in scraped_lookup: {match.page_url}"

    page_title, page_text = page_entry

    ok, evidence_err = _check_evidence(match.evidence_quote, page_text)
    if not ok:
        return f"evidence check failed: {evidence_err}"

    # 4. Opt-out validation
    if match.action == "opt-out" and not _check_opt_out(page_text):
        return "opt-out action but page has no opt-out/waiver language"

    # 5. Academic program filter
    if _is_academic_program_match(match, page_title, match.page_url):
        return "academic program description, not a benefit"

    # 6. Tag validation (non-rejecting, just cleans)
    match.tags = _clean_tags(match.tags)

    return None


# =========================================================================
# Part 2: Missed benefit detection
# =========================================================================

# -- answer extraction helpers ---------------------------------------------

# Pulls a single answer value from the answers dict.
# answers format: {question_text: {section_name: answer_value}}
def _get_answer(answers, question_fragment):
    for question, section_dict in answers.items():
        if question_fragment.lower() in question.lower():
            for _section, value in section_dict.items():
                return str(value).strip()
    return ""


# Checks if a value looks like "no", empty, or missing.
def _answer_is_no_or_empty(value):
    return not value or value.lower() in ("no", "none", "n/a", "0", "")


# Checks if the answer text contains any of the given keywords.
def _answer_contains_any(value, keywords):
    lower = value.lower()
    return any(k in lower for k in keywords)


# -- evidence extraction --------------------------------------------------

# Finds the first sentence in page_text containing the keyword.
# Returns that sentence as the evidence_quote.
def _extract_evidence_sentence(page_text, keyword):
    sentences = re.split(r'(?<=[.!?])\s+', page_text)
    keyword_lower = keyword.lower()
    for sentence in sentences:
        if keyword_lower in sentence.lower():
            return sentence.strip()[:200]
    return keyword


# -- source type detection (avoid circular import from matcher) ------------

def _detect_source_type(url):
    host = urlparse(url).netloc.lower()
    if host.endswith(".edu") or ".edu." in host:
        return "edu"
    if host.endswith(".gov") or ".gov." in host:
        return "gov"
    return "custom"


# -- detection rules -------------------------------------------------------
# Each rule is a function that takes (url, title, page_text, answers)
# and returns a dict with match fields if detected, or None if not.

def _detect_fafsa(url, title, page_text, answers):
    lower = page_text.lower()
    if "fafsa" not in lower and "tasfa" not in lower:
        return None

    aid_answer = _get_answer(answers, "applied for financial aid")
    if not _answer_is_no_or_empty(aid_answer):
        return None

    keyword = "FAFSA" if "fafsa" in lower else "TASFA"
    return {
        "benefit_name": "FAFSA/TASFA Application",
        "action": "apply",
        "tags": ["financial-aid"],
        "summary": f"{title or url} describes {keyword} — you haven't applied for financial aid yet.",
        "reasoning": f"Detected by keyword matching: '{keyword}' found on page, "
                     f"relevant because student has not applied for financial aid.",
        "evidence_quote": _extract_evidence_sentence(page_text, keyword),
        "inferred_from": ["Have you applied for financial aid?"],
    }


# Words that indicate counseling as a service, not an academic program.
_COUNSELING_SERVICE_KEYWORDS = [
    "counseling center", "counseling services", "crisis line",
    "timelycare", "vaqueros crisis",
]
# Words that indicate this is an academic program, not a service.
_COUNSELING_PROGRAM_KEYWORDS = [
    "school counseling certification", "counseling degree",
    "counseling program", "master of", "bachelor of",
    "department of counseling",
]

def _detect_counseling(url, title, page_text, answers):
    lower = page_text.lower()

    found_keyword = None
    for kw in _COUNSELING_SERVICE_KEYWORDS:
        if kw in lower:
            found_keyword = kw
            break
    if not found_keyword:
        return None

    # Make sure it's not an academic program page
    if any(prog in lower for prog in _COUNSELING_PROGRAM_KEYWORDS):
        return None

    health_answer = _get_answer(answers, "health history")
    mental_health_words = ["anxiety", "counseling", "mental health", "stress",
                           "depression", "therapy", "counselor"]
    if not _answer_contains_any(health_answer, mental_health_words):
        return None

    return {
        "benefit_name": "Counseling / Mental Health Services",
        "action": "contact",
        "tags": ["mental-health", "counseling"],
        "summary": f"{title or url} offers counseling or crisis services — "
                   f"relevant to your health history.",
        "reasoning": f"Detected by keyword matching: '{found_keyword}' found on page, "
                     f"relevant because student health history mentions mental health needs.",
        "evidence_quote": _extract_evidence_sentence(page_text, found_keyword),
        "inferred_from": ["Please describe your health history."],
    }


def _detect_scholarships(url, title, page_text, answers):
    lower = page_text.lower()
    count = lower.count("scholarship")
    if count < 3:
        return None

    scholarship_answer = _get_answer(answers, "receiving any scholarships")
    amount_answer = _get_answer(answers, "total annual scholarship amount")
    if not _answer_is_no_or_empty(scholarship_answer) and amount_answer not in ("0", ""):
        return None

    return {
        "benefit_name": "Scholarship Opportunities",
        "action": "review",
        "tags": ["scholarship"],
        "summary": f"{title or url} lists multiple scholarships — "
                   f"you're not currently receiving any.",
        "reasoning": f"Detected by keyword matching: 'scholarship' appears {count} times on page, "
                     f"relevant because student is not receiving scholarships.",
        "evidence_quote": _extract_evidence_sentence(page_text, "scholarship"),
        "inferred_from": ["Are you currently receiving any scholarships?",
                          "What is the total annual scholarship amount?"],
    }


def _detect_work_study(url, title, page_text, answers):
    lower = page_text.lower()
    has_keyword = ("work-study" in lower or "work study" in lower
                   or "student employment" in lower or "career center" in lower)
    if not has_keyword:
        return None

    employment_answer = _get_answer(answers, "employment status")
    if not _answer_contains_any(employment_answer,
                                ["unemployed", "looking", "seeking", "part-time",
                                 "no job", "not employed"]):
        return None

    keyword = next(kw for kw in ["work-study", "work study", "student employment",
                                  "career center"] if kw in lower)
    return {
        "benefit_name": "Work-Study / Student Employment",
        "action": "review",
        "tags": ["employment"],
        "summary": f"{title or url} has student employment resources — "
                   f"relevant to your job search.",
        "reasoning": f"Detected by keyword matching: '{keyword}' found on page, "
                     f"relevant because student is unemployed or seeking work.",
        "evidence_quote": _extract_evidence_sentence(page_text, keyword),
        "inferred_from": ["What is your current employment status?"],
    }


def _detect_tuition_assistance(url, title, page_text, answers):
    lower = page_text.lower()
    has_keyword = ("tuition advantage" in lower or "tuition assistance" in lower
                   or "fee waiver" in lower)
    if not has_keyword:
        return None

    aid_answer = _get_answer(answers, "applied for financial aid")
    if not _answer_is_no_or_empty(aid_answer):
        return None

    keyword = next(kw for kw in ["tuition advantage", "tuition assistance",
                                  "fee waiver"] if kw in lower)
    return {
        "benefit_name": "Tuition Assistance / Fee Waiver",
        "action": "review",
        "tags": ["tuition", "financial-aid"],
        "summary": f"{title or url} describes tuition assistance — "
                   f"you haven't applied for financial aid yet.",
        "reasoning": f"Detected by keyword matching: '{keyword}' found on page, "
                     f"relevant because student has not applied for financial aid.",
        "evidence_quote": _extract_evidence_sentence(page_text, keyword),
        "inferred_from": ["Have you applied for financial aid?"],
    }


def _detect_health_insurance(url, title, page_text, answers):
    lower = page_text.lower()
    has_keyword = ("student health insurance" in lower or "health plan" in lower
                   or "student health plan" in lower)
    if not has_keyword:
        return None

    insurance_answer = _get_answer(answers, "currently have health insurance")
    if not _answer_is_no_or_empty(insurance_answer):
        return None

    keyword = next(kw for kw in ["student health insurance", "student health plan",
                                  "health plan"] if kw in lower)
    return {
        "benefit_name": "Student Health Insurance",
        "action": "review",
        "tags": ["health"],
        "summary": f"{title or url} describes a student health plan — "
                   f"you don't currently have health insurance.",
        "reasoning": f"Detected by keyword matching: '{keyword}' found on page, "
                     f"relevant because student has no health insurance.",
        "evidence_quote": _extract_evidence_sentence(page_text, keyword),
        "inferred_from": ["Do you currently have health insurance?"],
    }


# All detection rules in order. Each returns a dict or None.
_DETECTION_RULES = [
    _detect_fafsa,
    _detect_counseling,
    _detect_scholarships,
    _detect_work_study,
    _detect_tuition_assistance,
    _detect_health_insurance,
]


# -- main missed-benefit detector -----------------------------------------

# Scans pages that had no valid LLM matches and catches obvious benefits
# via keyword matching against the student profile.
# scraped_lookup: {url: (title, text)}
# existing_matches: list of MatchResult already validated from the LLM.
# Returns a list of new MatchResult objects for detected benefits.
def detect_missed_benefits(scraped_lookup, answers, existing_matches,
                           pipeline_run_id=""):
    # Figure out which pages already have valid matches
    pages_with_matches = {m.page_url for m in existing_matches}

    # Build a set of (page_url, benefit_category) for dedup
    existing_categories = set()
    for m in existing_matches:
        for tag in m.tags:
            existing_categories.add((m.page_url, tag))

    detected = []

    for url, (title, page_text) in scraped_lookup.items():
        # Only scan pages with NO valid LLM matches
        if url in pages_with_matches:
            continue

        for rule_fn in _DETECTION_RULES:
            hit = rule_fn(url, title, page_text, answers)
            if not hit:
                continue

            # Dedup: skip if this page + tag category already covered
            hit_tags = hit.get("tags", [])
            if any((url, tag) in existing_categories for tag in hit_tags):
                continue

            result = MatchResult(
                match_id=str(uuid.uuid4()),
                page_url=url,
                page_title=title,
                source_type=_detect_source_type(url),
                relevance_score=3,
                benefit_name=hit["benefit_name"],
                action=hit["action"],
                summary=hit["summary"],
                reasoning=hit["reasoning"],
                action_details="",
                evidence_quote=hit["evidence_quote"],
                evidence_type="keyword-detection",
                cross_references=[],
                inferred_from=hit.get("inferred_from", []),
                tags=hit_tags,
                matched_at=datetime.now().isoformat(),
                pipeline_run_id=pipeline_run_id,
                status="new",
            )

            detected.append(result)
            for tag in hit_tags:
                existing_categories.add((url, tag))

    return detected
