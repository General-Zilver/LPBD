# validator.py -- Post-match validation for the matching pipeline.
# Runs after matcher.py produces results and before post-processing/save.
# Part 1: validate_matches - checks evidence grounding, action normalization,
# required fields, tag cleaning, and domain-specific rules.
# Part 2: detect_missed_benefits - keyword-based safety net for obvious
# benefits the LLM missed or that were all rejected by validation.

import json
import re
import uuid
from datetime import datetime
from urllib.parse import urlparse

import ollama_client

from matching.models import MatchResult
from matching.profile_signals import build_profile_signals


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

# Phrases that indicate a benefit is federal, statewide, or broadly available.
CROSS_INSTITUTION_MARKERS = [
    "federal",
    "statewide",
    "state of texas",
    "u.s. department",
    "department of education",
    "texas higher education",
    "open to all texas",
    "any texas public",
    "any texas public college",
    "any texas public college or university",
    "available to all students",
    "regardless of institution",
    "transferable",
    "ameri corps",
    "americorps",
    "fafsa",
    "tasfa",
    "pell grant",
]

HARD_ELIGIBILITY_CLAIMS = [
    "gpa",
    "minimum cumulative gpa",
    "honors college",
    "student parent",
    "dependent child",
    "dependents",
    "graduate student",
    "graduate program",
    "computing major",
    "computer science",
    "cybersecurity",
    "information technology",
    "45 credit hours",
    "pre-medical",
    "pre-med",
    "health-professions advising track",
    "biology",
    "biomedical sciences",
    "chemistry",
    "health insurance",
    "campus housing",
    "live on campus",
    "full-time",
    "pell grant",
    "student aid index",
    "sai",
    "food insecurity",
    "skipping meals",
    "no meal plan",
    "low-income",
    "laptop",
    "hotspot",
    "internet",
    "veteran",
    "active-duty",
    "out-of-state",
    "national merit",
]

HARD_REQUIREMENT_PHRASES = [
    "must",
    "required",
    "eligible students must",
    "requires",
    "not available to",
    "only available to",
    "minimum gpa",
    "must be enrolled",
    "must submit",
    "must live",
    "must have",
    "must be admitted",
    "students who are currently enrolled",
    "applicants should have",
]

PRIORITY_CRITERIA_PHRASES = [
    "priority is given",
    "preference is given",
    "considered but not required",
    "may receive priority",
    "encouraged",
    "recommended",
    "normally",
    "when funds are limited",
]

ALLOWED_MATCH_TYPES = {
    "direct_match",
    "general_resource",
    "aspirational",
    "needs_info",
    "not_likely",
}

_GPA_REQUIREMENT_PATTERNS = [
    re.compile(r"(?:minimum|min\.?)\s*(?:cumulative\s*)?gpa[^0-9]{0,15}([0-4](?:\.\d+)?)"),
    re.compile(r"(?:at least|no less than|required|requirement|must (?:be|maintain|have))[^0-9]{0,15}([0-4](?:\.\d+)?)\s*gpa"),
    re.compile(r"(?:require|requires|required|must have|must maintain|need|needs)\s*(?:a\s*)?(?:minimum\s*)?(?:cumulative\s*)?gpa[^0-9]{0,15}([0-4](?:\.\d+)?)"),
    re.compile(r"gpa[^0-9]{0,10}(?:>=|=>|>|at least|minimum|min\.?|required|must be|must maintain|or higher|and above)\s*([0-4](?:\.\d+)?)"),
    re.compile(r"gpa[^0-9]{0,10}([0-4](?:\.\d+)?)\s*(?:or higher|and above|minimum|required)"),
]

VERIFY_SYSTEM_PROMPT = """
You are a strict profile-aware verifier.

You will receive:
1) A student profile and home institution
2) A candidate benefit item proposed by a prior extraction pass
3) The source page text

Your job is to verify that the candidate is valid for this specific student.

Check all of the following:
- The benefit is explicitly described in the source page text.
- The benefit is relevant to facts explicitly stated in the student profile.
- If the source page belongs to a different institution than the student's home institution, the page must explicitly show the benefit is federal, statewide, transferable across institutions, publicly available to anyone, or open to non-students of that institution. If it does not, mark valid=false.
- The evidence_quote directly supports the specific benefit_name, not just any content on the same page.
- The relevance_score follows the scoring rubric below.

Do not infer profile facts that are not explicitly stated.
Do not accept institution-specific benefits from a different institution unless the page explicitly supports federal/statewide/transferable/public/open-to-non-students.
Do not infer from common university practices.

Scoring rubric for relevance_score:
5 = Directly applies to the student based on explicit profile facts, from the student's home institution or a federal/statewide source, with clear action steps and clear page evidence.
4 = Strongly relevant but missing one detail, such as eligibility not fully confirmed.
3 = Useful to review, but not clearly actionable yet.
2 = Possibly related, but weak or speculative.
1 = General awareness only.

Do not assign score 5 unless all three conditions hold: profile supports it, source supports it, and action is clear.

If the candidate is valid but the score is too high or too low, return a corrected score.

Return only JSON:
{
  "valid": true or false,
  "corrected_relevance_score": <integer 1-5 if valid, else null>,
  "evidence_quote": "exact quote from source text if valid, else empty string",
  "reason": "short reason"
}

Output valid JSON only.
""".strip()


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
# Requires an exact substring match. Short quotes (8 words or fewer) get a
# softer rejection message since whitespace/punctuation drift is plausible.
def _check_evidence(evidence_quote, page_text):
    if not evidence_quote or not evidence_quote.strip():
        return False, "empty evidence_quote"

    quote_norm = " ".join(evidence_quote.lower().split())
    page_norm = " ".join(page_text.lower().split())

    if not quote_norm:
        return False, "empty evidence_quote"

    if quote_norm in page_norm:
        return True, None

    word_count = len(quote_norm.split())
    if word_count > 8:
        return False, "evidence quote is not an exact source substring"

    return False, "evidence quote not found in page text"


# Benefit names generic enough that they naturally appear throughout a page.
# Proximity checking is skipped for these.
_GENERIC_BENEFIT_NAMES = {
    "financial aid", "scholarships", "mental health resources",
    "counseling services", "counseling service", "work-study",
    "student employment", "tuition assistance",
}


# Checks that the benefit_name appears within 1000 characters of the
# evidence_quote on the page. Catches hallucinated pairings where the
# quote is from one section and the benefit name from another.
def _check_evidence_proximity(evidence_quote, benefit_name, page_text):
    if benefit_name.lower() in _GENERIC_BENEFIT_NAMES:
        return True, None

    quote_norm = " ".join(evidence_quote.lower().split())
    page_norm = " ".join(page_text.lower().split())
    name_norm = benefit_name.lower()

    idx = page_norm.find(quote_norm)
    if idx == -1:
        return True, None

    window_start = max(0, idx - 1000)
    window_end = min(len(page_norm), idx + len(quote_norm) + 1000)
    window = page_norm[window_start:window_end]

    if name_norm in window:
        return True, None

    return False, "benefit_name not near evidence_quote on page"


def _slice_page_text_for_verification(page_text, evidence_quote, max_words=1800):
    words = page_text.split()
    if len(words) <= max_words:
        return page_text

    # Prefer a local window around the claimed evidence when possible.
    quote = (evidence_quote or "").strip().lower()
    lower = page_text.lower()
    if quote:
        idx = lower.find(quote)
        if idx != -1:
            start = max(0, idx - 5000)
            end = min(len(page_text), idx + len(quote) + 5000)
            return page_text[start:end]

    return " ".join(words[:max_words])


def _parse_verification_json(response_text):
    start = response_text.find("{")
    end = response_text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(response_text[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    raw_valid = data.get("valid", False)
    if isinstance(raw_valid, bool):
        valid = raw_valid
    elif isinstance(raw_valid, str):
        valid = raw_valid.strip().lower() in ("true", "1", "yes")
    else:
        valid = bool(raw_valid)

    evidence_quote = str(data.get("evidence_quote") or "").strip()
    reason = str(data.get("reason") or "").strip()

    raw_score = data.get("corrected_relevance_score")
    corrected_score = None
    if raw_score is not None:
        try:
            corrected_score = max(1, min(5, int(raw_score)))
        except (TypeError, ValueError):
            corrected_score = None

    return valid, evidence_quote, reason, corrected_score


def verify_matches_with_llm(matches, scraped_lookup, profile_text, user_institution,
                            model, llm_options=None):
    verified = []
    rejected = []

    for match in matches:
        page_entry = scraped_lookup.get(match.page_url)
        if not page_entry:
            match.rejection_reason = f"pass2 page missing: {match.page_url}"
            rejected.append(match)
            continue

        page_title, page_text = page_entry
        page_slice = _slice_page_text_for_verification(page_text, match.evidence_quote)

        prompt = f"""
STUDENT PROFILE
{profile_text}

USER INSTITUTION
{user_institution or "Unknown"}

CANDIDATE
benefit_name: {match.benefit_name}
action: {match.action}
relevance_score: {match.relevance_score}
summary: {match.summary}
reasoning: {match.reasoning}
claimed_evidence_quote: {match.evidence_quote}
source_url: {match.page_url}
source_title: {page_title}

SOURCE TEXT
{page_slice}

TASK
Verify whether the candidate is explicitly supported by SOURCE TEXT and relevant to this specific student profile.
If valid, confirm or correct the relevance_score using the scoring rubric.
Return JSON only.
""".strip()

        try:
            response = ollama_client.generate(
                prompt,
                system=VERIFY_SYSTEM_PROMPT,
                model=model,
                options=llm_options,
            )
        except Exception as exc:
            match.rejection_reason = f"pass2 verification error: {exc}"
            rejected.append(match)
            continue

        parsed = _parse_verification_json(response)
        if not parsed:
            match.rejection_reason = "pass2 invalid JSON response"
            rejected.append(match)
            continue

        is_valid, evidence_quote, reason, corrected_score = parsed
        if not is_valid:
            detail = reason or "not explicitly supported in source text"
            match.rejection_reason = f"pass2 rejected: {detail}"
            rejected.append(match)
            continue

        if corrected_score is not None:
            match.relevance_score = corrected_score
        if evidence_quote:
            match.evidence_quote = evidence_quote
        verified.append(match)

    return verified, rejected


# -- hard eligibility gate -------------------------------------------------

def _match_text_blob(match):
    return " ".join([
        match.benefit_name or "",
        match.summary or "",
        match.reasoning or "",
        match.action_details or "",
        match.evidence_quote or "",
    ]).lower()


def _match_identity_blob(match):
    return " ".join([
        match.benefit_name or "",
        match.page_title or "",
        match.page_url or "",
    ]).lower()


def _contains_any(text, phrases):
    return any(p in text for p in phrases)


def _contains_hard_requirement_language(text):
    lower = (text or "").lower()
    if not lower:
        return False

    if _contains_any(lower, [p for p in HARD_REQUIREMENT_PHRASES if p != "required"]):
        return True

    for m in re.finditer(r"\brequired\b", lower):
        window = lower[max(0, m.start() - 24): m.end() + 24]
        if "not required" in window or "but not required" in window:
            continue
        return True
    return False


def _contains_priority_language(text):
    return _contains_any((text or "").lower(), PRIORITY_CRITERIA_PHRASES)


def _has_nonempty_inferred_from(match):
    for item in (match.inferred_from or []):
        if str(item).strip():
            return True
    return False


def _extract_user_gpa(answers):
    direct = _get_answer(answers, "current gpa")
    if direct:
        m = re.search(r"([0-4](?:\.\d+)?)", direct)
        if m:
            return float(m.group(1))

    for question, section_dict in (answers or {}).items():
        if "gpa" not in question.lower():
            continue
        for _section, value in section_dict.items():
            m = re.search(r"([0-4](?:\.\d+)?)", str(value))
            if m:
                return float(m.group(1))
    return None


def _extract_minimum_gpa_requirements(text):
    lower = (text or "").lower()
    found = []
    for pattern in _GPA_REQUIREMENT_PATTERNS:
        for match in pattern.finditer(lower):
            try:
                value = float(match.group(1))
            except (TypeError, ValueError):
                continue
            if 0 <= value <= 5:
                found.append(value)
    return sorted(set(found))


def _is_explicit_yes(value):
    lower = (value or "").strip().lower()
    if not lower:
        return False
    if lower in ("yes", "y", "true", "1"):
        return True
    return lower.startswith("yes ")


def _is_explicit_no(value):
    lower = (value or "").strip().lower()
    if not lower:
        return False
    if _is_explicit_yes(lower):
        return False
    return any(token in lower for token in [
        "no",
        "none",
        "do not",
        "don't",
        "not",
        "without",
        "n/a",
    ])


def _answer_values_blob(answers):
    values = []
    for _question, section_dict in (answers or {}).items():
        for _section, value in section_dict.items():
            clean = str(value).strip().lower()
            if clean:
                values.append(clean)
    return " | ".join(values)


def _profile_major_value(answers):
    for question, section_dict in (answers or {}).items():
        q = question.lower()
        if "major" not in q and "field of study" not in q:
            continue
        for _section, value in section_dict.items():
            clean = str(value).strip().lower()
            if clean:
                return clean
    return ""


def _profile_supports_enrollment(answers, values_blob):
    student_answer = _get_answer(answers, "are you a student")
    if _is_explicit_yes(student_answer):
        return True
    if _get_answer(answers, "institution name"):
        return True
    return _contains_any(values_blob, ["enrolled", "student"])


def _profile_contradicts_enrollment(answers, values_blob):
    student_answer = _get_answer(answers, "are you a student")
    if _is_explicit_no(student_answer):
        return True
    return _contains_any(values_blob, ["not a student", "not enrolled"])


def _profile_supports_computing_track(values_blob):
    return _contains_any(values_blob, [
        "computer science",
        "cybersecurity",
        "information technology",
        "informatics",
        "software",
        "computing",
    ])


def _profile_contradicts_computing_track(answers):
    major = _profile_major_value(answers)
    if not major:
        return False
    if _contains_any(major, ["undeclared", "unknown", "not sure"]):
        return False
    return not _contains_any(major, [
        "computer science",
        "cybersecurity",
        "information technology",
        "informatics",
        "software",
        "computing",
    ])


def _profile_supports_45_credits_or_classification(values_blob):
    if _contains_any(values_blob, [
        "45 credit hours",
        "45 credits",
        "45 credit",
        "junior",
        "senior",
        "3rd year",
        "third year",
        "4th year",
        "fourth year",
        "upper division",
    ]):
        return True
    m = re.search(r"(\d+)\s*(credit|credits|credit hours|hours)", values_blob)
    if not m:
        return False
    try:
        return int(m.group(1)) >= 45
    except ValueError:
        return False


def _profile_contradicts_45_credits_or_classification(values_blob):
    if _contains_any(values_blob, [
        "freshman",
        "first-year",
        "first year",
        "sophomore",
        "2nd year",
        "second year",
    ]):
        return True
    m = re.search(r"(\d+)\s*(credit|credits|credit hours|hours)", values_blob)
    if not m:
        return False
    try:
        return int(m.group(1)) < 45
    except ValueError:
        return False


def _profile_supports_honors(values_blob):
    return _contains_any(values_blob, ["honors college", "honors program", "honors"])


def _profile_contradicts_honors(values_blob):
    return _contains_any(values_blob, ["not in honors", "not honors", "no honors"])


def _profile_supports_prehealth(values_blob):
    return _contains_any(values_blob, [
        "pre-med",
        "pre med",
        "pre-medical",
        "pre-health",
        "pre health",
        "health-professions advising",
        "health professions advising",
        "biology",
        "biomedical sciences",
        "chemistry",
    ])


def _profile_contradicts_prehealth(answers):
    major = _profile_major_value(answers)
    if not major:
        return False
    if _contains_any(major, ["undeclared", "unknown", "not sure"]):
        return False
    return not _contains_any(major, [
        "pre-med",
        "pre med",
        "pre-medical",
        "pre-health",
        "pre health",
        "health-professions advising",
        "health professions advising",
        "biology",
        "biomedical sciences",
        "chemistry",
    ])


def _profile_supports_on_campus(values_blob):
    return _contains_any(values_blob, [
        "live on campus",
        "on-campus",
        "on campus",
        "campus housing",
        "residence hall",
        "dorm",
    ])


def _profile_contradicts_on_campus(values_blob):
    return _contains_any(values_blob, [
        "off campus",
        "off-campus",
        "commuter",
        "live with parent",
        "live with family",
    ])


def _profile_supports_full_time(values_blob):
    return _contains_any(values_blob, [
        "full-time",
        "full time",
        "12 credit",
        "enrolled full",
    ])


def _profile_contradicts_full_time(values_blob):
    return _contains_any(values_blob, ["part-time", "part time", "less than 12 credit"])


def _profile_supports_dependents(values_blob):
    return _contains_any(values_blob, [
        "dependent child",
        "dependents",
        "student parent",
        "single parent",
        "children",
    ])


def _profile_contradicts_dependents(values_blob):
    return _contains_any(values_blob, [
        "no dependents",
        "no children",
        "0 dependents",
        "not a parent",
    ])


def _profile_supports_basic_needs(values_blob):
    return _contains_any(values_blob, [
        "food insecurity",
        "skipping meals",
        "skip meals",
        "no meal plan",
        "pell grant",
        "student aid index",
        "sai 0",
        "low-income",
        "low income",
        "student parent",
        "dependents",
        "basic needs",
    ])


def _profile_supports_technology_need(values_blob):
    return _contains_any(values_blob, [
        "broken laptop",
        "no laptop",
        "no computer",
        "without computer",
        "unreliable internet",
        "no internet",
        "hotspot",
        "library computer",
    ])


def _profile_supports_graduate_or_employee(values_blob):
    return _contains_any(values_blob, [
        "graduate student",
        "grad student",
        "graduate admission",
        "admitted to graduate",
        "graduate coursework",
        "utrgv employee",
        "employee",
        "staff",
    ])


def _profile_contradicts_graduate_or_employee(values_blob):
    has_undergrad = _contains_any(values_blob, ["undergraduate", "undergrad"])
    has_not_employee = _contains_any(values_blob, ["unemployed", "not employed", "no job"])
    has_employee_support = _contains_any(values_blob, ["employee", "staff", "utrgv employee"])
    if has_undergrad and has_not_employee and not has_employee_support:
        return True
    return False


def _profile_supports_veteran(values_blob):
    return _contains_any(values_blob, [
        "veteran",
        "active-duty",
        "active duty",
        "reservist",
        "reserve",
        "national guard",
        "military dependent",
        "military-connected",
    ])


def _profile_contradicts_veteran(values_blob):
    return _contains_any(values_blob, [
        "not a veteran",
        "no military service",
        "non-military",
        "civilian",
    ])


def _is_open_access_priority_benefit(text):
    lower = (text or "").lower()
    has_priority = _contains_priority_language(lower)
    has_enrollment = _contains_any(lower, [
        "currently enrolled",
        "enrolled students",
        "any enrolled student",
        "all enrolled students",
        "students who are currently enrolled",
        "any student",
    ])
    has_form_or_booking = _contains_any(lower, [
        "intake form",
        "complete the form",
        "submit the form",
        "book an appointment",
        "schedule an appointment",
        "request form",
        "application form",
    ])
    return has_priority and has_enrollment and has_form_or_booking


def _page_requires_fafsa(text):
    lower = (text or "").lower()
    if "fafsa" not in lower and "tasfa" not in lower:
        return False
    for sentence in re.split(r"[.!?]\s+", lower):
        if "fafsa" not in sentence and "tasfa" not in sentence:
            continue
        if "not required" in sentence:
            continue
        if _contains_any(sentence, [
            "required",
            "must",
            "need to",
            "needs to",
            "complete",
            "completed",
            "submit",
            "submitted",
            "requirement",
        ]):
            return True
    return False


def _downgrade_to_review(match, score_cap=3):
    match.action = "review"
    match.relevance_score = min(match.relevance_score, score_cap)


def _set_likely_eligible(match):
    match.eligibility_status = "likely_eligible"


def _set_needs_info(match, score_cap=3):
    match.eligibility_status = "needs_info"
    if match.action == "apply":
        match.action = "review"
    match.relevance_score = min(match.relevance_score, score_cap)


def _set_not_eligible(match, reason):
    match.eligibility_status = "not_eligible"
    if match.action == "apply":
        match.action = "review"
    match.relevance_score = min(match.relevance_score, 2)
    match.rejection_reason = reason


def _set_direct_match(match, score_floor=4):
    _set_likely_eligible(match)
    match.match_type = "direct_match"
    if score_floor is not None:
        match.relevance_score = max(score_floor, min(match.relevance_score, 5))


def _set_general_resource(match, score_cap=3):
    _set_likely_eligible(match)
    match.match_type = "general_resource"
    if match.action == "apply":
        match.action = "review"
    match.relevance_score = min(match.relevance_score, score_cap)


def _set_needs_info_match(match, score_cap=3):
    _set_needs_info(match, score_cap=score_cap)
    match.match_type = "needs_info"


def _set_aspirational(match, score_cap=3):
    match.match_type = "aspirational"
    if match.eligibility_status == "":
        match.eligibility_status = "needs_info"
    if match.action == "apply":
        match.action = "review"
    match.relevance_score = min(match.relevance_score, score_cap)


def _set_not_likely(match, score_cap=2):
    match.match_type = "not_likely"
    if match.eligibility_status == "":
        match.eligibility_status = "needs_info"
    match.action = "review"
    match.relevance_score = min(match.relevance_score, score_cap)


def _log_profile_signal_decision(match, action_taken, reason, signal_key, signal_value):
    benefit = (match.benefit_name or match.page_title or match.page_url or "").strip()
    print(
        f"  [hard gate] {benefit}: {action_taken}; "
        f"reason={reason}; signal={signal_key}={signal_value}"
    )


def _has_dependents_requirement(text):
    lower = (text or "").lower()
    if not lower:
        return False

    strong_requirement_phrases = [
        "at least one dependent child",
        "proof of dependent status",
        "childcare cost estimate",
        "licensed childcare",
    ]
    if _contains_any(lower, strong_requirement_phrases):
        return True

    weak_terms = [
        "dependent child",
        "student parent",
        "students with children",
    ]
    hard_markers = [
        "must",
        "required",
        "requirement",
        "eligible",
        "only",
        "need to",
        "needs to",
        "must submit",
        "must provide",
    ]
    for term in weak_terms:
        for m in re.finditer(re.escape(term), lower):
            start = max(0, m.start() - 80)
            end = min(len(lower), m.end() + 80)
            window = lower[start:end]
            if _contains_any(window, hard_markers):
                return True
    return False


def _is_dependent_child_benefit(match):
    identity_parts = [
        match.benefit_name or "",
        match.page_title or "",
        match.page_url or "",
        " ".join(match.tags or []),
    ]
    identity_blob = " ".join(identity_parts).lower()

    positive_terms = [
        "childcare",
        "child care",
        "student parent",
        "dependent child",
        "dependent-care",
        "dependent care",
        "parent resource",
    ]
    if any(term in identity_blob for term in positive_terms):
        return True
    return False


def _has_narrow_dependents_requirement_near_match(match, page_text):
    lower_page = (page_text or "").lower()
    if not lower_page:
        return False

    requirement_phrases = [
        "must have at least one dependent child",
        "have at least one dependent child",
        "proof of dependent status",
        "student parents only",
        "licensed childcare requirement",
    ]
    if not any(phrase in lower_page for phrase in requirement_phrases):
        return False

    anchors = [
        str(match.evidence_quote or "").strip().lower(),
        str(match.benefit_name or "").strip().lower(),
    ]
    for anchor in anchors:
        if not anchor:
            continue
        pos = lower_page.find(anchor)
        if pos == -1:
            continue
        window_start = max(0, pos - 600)
        window_end = min(len(lower_page), pos + len(anchor) + 600)
        window_text = lower_page[window_start:window_end]
        for sentence in re.split(r"(?<=[.!?])\s+", window_text):
            if any(phrase in sentence for phrase in requirement_phrases):
                return True
    return False


def _has_veteran_requirement(text):
    return _contains_any((text or "").lower(), [
        "veteran",
        "active-duty",
        "active duty",
        "military-connected",
        "gi bill",
        "military dependent",
    ])


def _has_grad_or_employee_requirement(text):
    return _contains_any((text or "").lower(), [
        "graduate student",
        "admitted to graduate program",
        "graduate assistantship",
        "employee tuition assistance",
        "employee",
    ])


def _is_grad_or_employee_only_requirement(text):
    return _contains_any((text or "").lower(), [
        "only for graduate students",
        "graduate students only",
        "only available to graduate students",
        "only available to graduate student",
        "must be a graduate student",
        "only for employees",
        "employees only",
        "only available to employees",
        "must be an employee",
        "must be a utrgv employee",
    ])


def _has_computing_major_requirement(text):
    return _contains_any((text or "").lower(), [
        "computing major",
        "computer science major",
        "cybersecurity major",
        "information technology major",
        "undergraduate computing majors",
        "degree in computer science",
        "degree in cybersecurity",
        "degree in information technology",
    ])


def _profile_signals_supports_computing_major(profile_signals):
    terms = [str(t).strip().lower() for t in (profile_signals.get("major_terms") or [])]
    blob = " | ".join([t for t in terms if t])
    if not blob:
        return False
    return _contains_any(blob, [
        "computer science",
        "computing",
        "cybersecurity",
        "information technology",
        "informatics",
        "software",
    ])


def _profile_signals_undergrad_classification(profile_signals):
    classification = str(profile_signals.get("classification") or "").lower()
    return _contains_any(classification, [
        "freshman",
        "sophomore",
        "junior",
        "senior",
        "undergraduate",
        "undergrad",
    ])


def _profile_explicitly_not_employed(values_blob):
    lower = (values_blob or "").lower()
    has_not_employed = _contains_any(lower, ["unemployed", "not employed", "no job"])
    has_employed = _contains_any(lower, ["employee", "staff", "employed"])
    return has_not_employed and not has_employed


def _is_women_in_computing_match(identity_blob):
    return (
        "women in computing retention scholarship" in identity_blob
        or "women-in-computing-retention-scholarship" in identity_blob
    )


def _is_honors_mini_grant_match(identity_blob):
    return (
        "honors research and study travel mini-grant" in identity_blob
        or "honors-research-travel-mini-grant" in identity_blob
    )


def _is_prehealth_program_match(match):
    identity_blob = _match_identity_blob(match)
    return (
        "pre-health shadowing and mcat support program" in identity_blob
        or "prehealth-shadowing-mcat-support" in identity_blob
    )


def _is_residence_life_match(identity_blob):
    return (
        "residence life sports leadership stipend" in identity_blob
        or "residence-life-sports-leadership-stipend" in identity_blob
    )


def _is_childcare_access_grant_match(identity_blob):
    return (
        "childcare access grant" in identity_blob
        or "childcare-access-grant" in identity_blob
    )


def _is_food_pantry_match(identity_blob):
    return (
        "food pantry and meal swipe relief" in identity_blob
        or "food-pantry-meal-swipe-relief" in identity_blob
    )


def _is_technology_emergency_match(identity_blob):
    return (
        "technology emergency loan and hotspot program" in identity_blob
        or "technology-emergency-loan-hotspot" in identity_blob
    )


def _is_graduate_assistantship_match(identity_blob):
    return (
        "graduate assistantship and employee tuition support" in identity_blob
        or "graduate-assistantship-employee-tuition-support" in identity_blob
    )


def _is_veterans_book_grant_match(identity_blob):
    return (
        "veterans transition book grant" in identity_blob
        or "veterans-transition-book-grant" in identity_blob
    )


def _is_out_of_state_merit_match(identity_blob):
    return (
        "out-of-state merit waiver" in identity_blob
        or "out of state merit waiver" in identity_blob
        or (
            "national merit" in identity_blob
            and "waiver" in identity_blob
        )
    )


def _normalize_token_text(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _institution_acronym(value):
    words = re.findall(r"[a-z0-9]+", str(value or "").lower())
    if not words:
        return ""
    stopwords = {"the", "of", "and", "for", "at", "in"}
    filtered = [w for w in words if w not in stopwords]
    if not filtered:
        filtered = words
    acronym = "".join(w[0] for w in filtered if w)
    if len(acronym) < 3:
        return ""
    return acronym


def _is_home_institution_page(url, home_domains, institution_name):
    hostname = _clean_hostname(url)
    if not hostname:
        return False

    if home_domains:
        return any(_hostname_matches_domain(hostname, d) for d in home_domains)

    institution_token = _normalize_token_text(institution_name)
    if not institution_token:
        return True
    hostname_token = _normalize_token_text(hostname)
    if not hostname_token:
        return False
    if institution_token in hostname_token or hostname_token in institution_token:
        return True
    acronym = _institution_acronym(institution_name)
    if acronym and acronym in hostname_token:
        return True
    return False


def _collapse_prehealth_components(matches):
    kept = []
    rejected = []
    grouped = {}

    for match in matches:
        if (match.evidence_type or "").lower() == "keyword-detection":
            kept.append(match)
            continue
        if _is_prehealth_program_match(match):
            grouped.setdefault(match.page_url, []).append(match)
            continue
        kept.append(match)

    for _url, group in grouped.items():
        if not group:
            continue
        primary = sorted(
            group,
            key=lambda m: (
                m.relevance_score,
                1 if m.evidence_quote else 0,
                len(m.action_details or ""),
            ),
            reverse=True,
        )[0]
        canonical_name = "Pre-Health Shadowing and MCAT Support Program"
        primary.benefit_name = canonical_name

        component_names = []
        for item in group:
            name = (item.benefit_name or "").strip()
            if name and name.lower() != canonical_name.lower() and name not in component_names:
                component_names.append(name)
        if component_names:
            component_text = ", ".join(component_names[:3])
            if component_text.lower() not in (primary.summary or "").lower():
                if primary.summary:
                    primary.summary = f"{primary.summary} Components: {component_text}."
                else:
                    primary.summary = f"Components: {component_text}."

        kept.append(primary)
        for item in group:
            if item is primary:
                continue
            item.rejection_reason = "hard gate: collapsed component into program-level match"
            rejected.append(item)

    return kept, rejected


def hard_eligibility_gate(matches, answers, scraped_lookup, profile_signals=None):
    accepted = []
    rejected = []

    if profile_signals is None:
        profile_signals = build_profile_signals(answers or {})
    values_blob = _answer_values_blob(answers)
    user_gpa = _extract_user_gpa(answers)
    signal_gpa = profile_signals.get("gpa")
    if signal_gpa is not None:
        try:
            user_gpa = float(signal_gpa)
        except (TypeError, ValueError):
            pass
    aid_answer = _get_answer(answers, "applied for financial aid")
    has_not_applied_aid = _is_explicit_no(aid_answer)
    if profile_signals.get("has_fafsa") is False:
        has_not_applied_aid = True
    elif profile_signals.get("has_fafsa") is True:
        has_not_applied_aid = False
    insurance_answer = _get_answer(answers, "currently have health insurance")
    has_no_health_insurance = _is_explicit_no(insurance_answer)
    if profile_signals.get("insured") is False:
        has_no_health_insurance = True
    elif profile_signals.get("insured") is True:
        has_no_health_insurance = False
    supports_enrollment = _profile_supports_enrollment(answers, values_blob)
    if profile_signals.get("student") is True:
        supports_enrollment = True
    elif profile_signals.get("student") is False:
        supports_enrollment = False
    contradicts_enrollment = _profile_contradicts_enrollment(answers, values_blob)
    if profile_signals.get("student") is False:
        contradicts_enrollment = True
    elif profile_signals.get("student") is True:
        contradicts_enrollment = False
    home_domains = _extract_user_home_domains(answers or {})

    for match in matches:
        if (match.evidence_type or "").lower() == "keyword-detection":
            match.action = "review"
            match.relevance_score = min(match.relevance_score, 2)
            if not match.eligibility_status:
                match.eligibility_status = "needs_info"
            if not getattr(match, "match_type", ""):
                match.match_type = "general_resource"
            accepted.append(match)
            continue

        match.eligibility_status = ""
        match.match_type = ""
        identity_blob = _match_identity_blob(match)
        text_blob = _match_text_blob(match)
        page_text = ""
        page_entry = (scraped_lookup or {}).get(match.page_url)
        if page_entry:
            _page_title, page_text = page_entry
        requirement_text = " ".join([text_blob, (page_text or "").lower()])
        has_hard_requirements = _contains_hard_requirement_language(requirement_text)
        has_priority_language = _contains_priority_language(requirement_text)
        pending_needs_info = (
            match.action == "apply"
            and (has_hard_requirements or _contains_any(text_blob, HARD_ELIGIBILITY_CLAIMS))
            and not _has_nonempty_inferred_from(match)
        )
        forced_grad_or_employee_downgrade = False
        forced_computing_downgrade = False

        signal_has_dependents = profile_signals.get("has_dependents")
        dependent_child_benefit = _is_dependent_child_benefit(match)
        has_narrow_dependent_requirement = _has_narrow_dependents_requirement_near_match(
            match,
            page_text,
        )
        if (
            signal_has_dependents is False
            and dependent_child_benefit
            and has_narrow_dependent_requirement
        ):
            _set_not_eligible(match, "profile contradicts dependent-child requirement")
            _log_profile_signal_decision(
                match,
                "reject",
                "profile contradicts dependent-child requirement",
                "has_dependents",
                signal_has_dependents,
            )
            rejected.append(match)
            continue

        signal_veteran = profile_signals.get("veteran")
        if signal_veteran is False and _has_veteran_requirement(requirement_text):
            _set_not_eligible(match, "profile contradicts veteran or military requirement")
            _log_profile_signal_decision(
                match,
                "reject",
                "profile contradicts veteran or military requirement",
                "veteran",
                signal_veteran,
            )
            rejected.append(match)
            continue

        classification_undergrad = _profile_signals_undergrad_classification(profile_signals)
        requires_grad_or_employee = _has_grad_or_employee_requirement(requirement_text)
        only_grad_or_employee = _is_grad_or_employee_only_requirement(requirement_text)
        explicitly_not_employed = _profile_explicitly_not_employed(values_blob)
        if classification_undergrad and requires_grad_or_employee:
            if only_grad_or_employee and explicitly_not_employed:
                _set_not_eligible(match, "profile contradicts graduate or employee requirement")
                _log_profile_signal_decision(
                    match,
                    "reject",
                    "profile contradicts graduate or employee requirement",
                    "classification",
                    profile_signals.get("classification"),
                )
                rejected.append(match)
                continue

            _set_aspirational(match, score_cap=3)
            if match.action not in ("contact", "review"):
                match.action = "review"
            match.reasoning = (
                "This benefit may become relevant later, but current profile signals "
                "indicate undergraduate classification without confirmed graduate or employee eligibility."
            )
            _log_profile_signal_decision(
                match,
                "downgrade",
                "undergraduate classification with graduate or employee requirement",
                "classification",
                profile_signals.get("classification"),
            )
            forced_grad_or_employee_downgrade = True

        if _has_computing_major_requirement(requirement_text):
            supports_computing_major = _profile_signals_supports_computing_major(profile_signals)
            if not supports_computing_major:
                _set_not_likely(match, score_cap=2)
                match.reasoning = (
                    "This benefit requires a computing-focused major, and the profile signals "
                    "do not support that major requirement."
                )
                _log_profile_signal_decision(
                    match,
                    "downgrade",
                    "profile does not support computing-major requirement",
                    "major_terms",
                    profile_signals.get("major_terms"),
                )
                forced_computing_downgrade = True

        if has_hard_requirements and contradicts_enrollment:
            _set_not_eligible(
                match,
                "hard gate: hard requirement contradicts profile enrollment status",
            )
            rejected.append(match)
            continue

        required_gpas = _extract_minimum_gpa_requirements(
            " ".join([match.evidence_quote or "", match.summary or "", match.reasoning or ""])
        )
        if required_gpas:
            min_required = max(required_gpas)
            if user_gpa is None:
                _set_needs_info_match(match, score_cap=3)
                match.reasoning = (
                    f"This benefit references a minimum GPA of {min_required:.2f}, "
                    "but the profile does not confirm GPA."
                )
            elif user_gpa < min_required:
                gap = min_required - user_gpa
                if has_hard_requirements:
                    if gap <= 0.40:
                        _set_aspirational(match, score_cap=3)
                    else:
                        _set_not_likely(match, score_cap=2)
                    match.reasoning = (
                        f"This benefit requires a minimum GPA of {min_required:.2f}. "
                        f"The profile GPA is {user_gpa:.2f}, so this is not apply-ready right now."
                    )
                else:
                    _set_needs_info_match(match, score_cap=3)

        if _is_women_in_computing_match(identity_blob) and not forced_computing_downgrade:
            computing_support = _profile_supports_computing_track(values_blob)
            computing_contradiction = _profile_contradicts_computing_track(answers)
            credits_support = _profile_supports_45_credits_or_classification(values_blob)
            credits_contradiction = _profile_contradicts_45_credits_or_classification(values_blob)
            gpa_contradiction = user_gpa is not None and user_gpa < 3.20
            gpa_missing = user_gpa is None

            if computing_support and credits_support and not gpa_missing and not gpa_contradiction:
                _set_direct_match(match, score_floor=4)
                if match.action not in ("review", "contact"):
                    match.action = "apply"
            else:
                if computing_contradiction:
                    _set_not_likely(match, score_cap=2)
                    match.reasoning = (
                        "This scholarship is targeted to computing-focused students. "
                        "The current profile does not confirm that fit."
                    )
                elif gpa_contradiction:
                    gap = 3.20 - user_gpa if user_gpa is not None else 0.0
                    if gap <= 0.40:
                        _set_aspirational(match, score_cap=3)
                    else:
                        _set_not_likely(match, score_cap=2)
                    match.reasoning = (
                        "This scholarship requires a higher GPA. "
                        "It may become relevant if GPA requirements are met later."
                    )
                elif credits_contradiction:
                    _set_aspirational(match, score_cap=3)
                    match.reasoning = (
                        "This scholarship expects advanced credit progress. "
                        "It may become relevant after additional completed credit hours."
                    )
                else:
                    _set_needs_info_match(match, score_cap=3)
                    match.reasoning = (
                        "This scholarship may be relevant, but the profile is missing one or more required details."
                    )

        if _is_honors_mini_grant_match(identity_blob):
            honors_support = _profile_supports_honors(values_blob)
            honors_contradiction = _profile_contradicts_honors(values_blob)
            gpa_contradiction = user_gpa is not None and user_gpa < 3.50
            gpa_missing = user_gpa is None

            if honors_support and not gpa_missing and not gpa_contradiction:
                _set_direct_match(match, score_floor=4)
                if match.action not in ("review", "contact"):
                    match.action = "apply"
            else:
                if gpa_contradiction:
                    gap = 3.50 - user_gpa if user_gpa is not None else 0.0
                    if gap <= 0.40:
                        _set_aspirational(match, score_cap=3)
                    else:
                        _set_not_likely(match, score_cap=2)
                    match.reasoning = (
                        "This grant requires a higher GPA. "
                        "It may become relevant after GPA improvements."
                    )
                elif honors_contradiction:
                    _set_aspirational(match, score_cap=3)
                    match.reasoning = (
                        "This grant is intended for Honors students. "
                        "It may become relevant after joining an Honors program."
                    )
                else:
                    _set_needs_info_match(match, score_cap=3)
                    match.reasoning = (
                        "This grant may be relevant, but Honors participation or GPA details are not fully confirmed."
                    )

        if _is_prehealth_program_match(match):
            prehealth_support = _profile_supports_prehealth(values_blob)
            prehealth_contradiction = _profile_contradicts_prehealth(answers)
            if prehealth_support:
                _set_direct_match(match, score_floor=4)
                if match.action not in ("review", "contact"):
                    match.action = "apply"
            else:
                if prehealth_contradiction:
                    _set_not_likely(match, score_cap=2)
                    match.reasoning = (
                        "This program is mainly for pre-health tracks. "
                        "The current profile does not confirm that track."
                    )
                else:
                    _set_needs_info_match(match, score_cap=3)
                    match.reasoning = (
                        "This program may be relevant, but the profile does not confirm pre-health track alignment."
                    )
            if has_no_health_insurance and _contains_any(text_blob, [
                "clinical observation placement assistance",
                "clinical observation",
            ]):
                _set_not_likely(match, score_cap=2)
                match.reasoning = (
                    "Clinical observation placement on this page may require health insurance. "
                    "The profile does not currently support that requirement."
                )

        if _is_residence_life_match(identity_blob):
            on_campus_support = _profile_supports_on_campus(values_blob)
            on_campus_contradiction = _profile_contradicts_on_campus(values_blob)
            full_time_support = _profile_supports_full_time(values_blob)
            full_time_contradiction = _profile_contradicts_full_time(values_blob)
            gpa_contradiction = user_gpa is not None and user_gpa < 3.00
            gpa_missing = user_gpa is None

            if on_campus_support and full_time_support and not gpa_missing and not gpa_contradiction:
                _set_direct_match(match, score_floor=4)
                if match.action not in ("review", "contact"):
                    match.action = "apply"
            else:
                if gpa_contradiction:
                    gap = 3.00 - user_gpa if user_gpa is not None else 0.0
                    if gap <= 0.40:
                        _set_aspirational(match, score_cap=3)
                    else:
                        _set_not_likely(match, score_cap=2)
                    match.reasoning = (
                        "This stipend requires a higher GPA. "
                        "It may become relevant after GPA improvements."
                    )
                elif on_campus_contradiction or full_time_contradiction:
                    _set_aspirational(match, score_cap=3)
                    match.reasoning = (
                        "This stipend is tied to residence-life and enrollment requirements. "
                        "The current profile does not show those requirements yet."
                    )
                else:
                    _set_needs_info_match(match, score_cap=3)
                    match.reasoning = (
                        "This stipend may be relevant, but housing, enrollment, or GPA details are incomplete."
                    )

        if _is_childcare_access_grant_match(identity_blob):
            dependents_support = _profile_supports_dependents(values_blob)
            dependents_contradiction = _profile_contradicts_dependents(values_blob)
            fafsa_required = _page_requires_fafsa(requirement_text)

            if dependents_contradiction:
                _set_not_eligible(
                    match,
                    "hard gate: Childcare Access Grant requires dependent child support",
                )
                rejected.append(match)
                continue

            if dependents_support and (not fafsa_required or not has_not_applied_aid):
                _set_direct_match(match, score_floor=4)
                if match.action not in ("review", "contact"):
                    match.action = "apply"
            elif dependents_support and fafsa_required and has_not_applied_aid:
                _set_aspirational(match, score_cap=3)
                match.reasoning = (
                    "This childcare benefit may be relevant, but FAFSA or TASFA completion appears required first."
                )
            elif dependents_support and fafsa_required and not aid_answer:
                _set_needs_info_match(match, score_cap=3)
                match.reasoning = (
                    "This childcare benefit may be relevant, but financial aid application status is not confirmed."
                )
            else:
                _set_needs_info_match(match, score_cap=3)
                match.reasoning = (
                    "This childcare benefit may be relevant, but the profile does not confirm dependent-child status."
                )

        if _is_out_of_state_merit_match(identity_blob):
            signal_out_of_state = profile_signals.get("out_of_state")
            signal_national_merit = profile_signals.get("national_merit")
            signal_full_time = profile_signals.get("full_time")
            signal_student = profile_signals.get("student")
            signal_institution = profile_signals.get("institution")

            supports_out_of_state = (
                signal_out_of_state is True
                or _contains_any(values_blob, ["out-of-state", "out of state", "nonresident"])
            )
            supports_national_merit = (
                signal_national_merit is True
                or _contains_any(values_blob, ["national merit"])
            )
            supports_full_time = (
                signal_full_time is True
                or _profile_supports_full_time(values_blob)
            )
            supports_student = (
                signal_student is True
                or supports_enrollment
            )
            supports_gpa = user_gpa is not None and user_gpa >= 3.00
            is_home_page = _is_home_institution_page(
                match.page_url,
                home_domains,
                signal_institution,
            )

            contradiction = (
                signal_out_of_state is False
                or signal_national_merit is False
                or signal_full_time is False
                or signal_student is False
            )

            if (
                is_home_page
                and supports_out_of_state
                and supports_national_merit
                and supports_full_time
                and supports_student
                and supports_gpa
            ):
                _set_direct_match(match, score_floor=5)
                match.action = "apply"
                match.reasoning = (
                    "The profile signals support out-of-state, National Merit, full-time enrollment, "
                    "and GPA requirements for this waiver."
                )
            elif contradiction:
                _set_not_likely(match, score_cap=2)
                match.reasoning = (
                    "This waiver has profile requirements that are directly contradicted by the current profile."
                )
            else:
                _set_needs_info_match(match, score_cap=3)
                match.reasoning = (
                    "This waiver may be relevant, but one or more required profile details are not fully confirmed."
                )

        if _is_food_pantry_match(identity_blob):
            basic_needs_support = _profile_supports_basic_needs(values_blob)
            if supports_enrollment:
                if basic_needs_support:
                    _set_direct_match(match, score_floor=4)
                    if match.action not in ("review", "contact"):
                        match.action = "apply"
                    match.reasoning = (
                        "This page provides food and basic-needs support for students, "
                        "and the profile includes basic-needs indicators."
                    )
                else:
                    _set_general_resource(match, score_cap=3)
                    match.reasoning = (
                        "This is a general food resource for enrolled students. "
                        "The profile does not show food insecurity, so this is lower priority."
                    )
            else:
                _set_needs_info_match(match, score_cap=3)
                match.reasoning = (
                    "This may be relevant because the page offers food support, "
                    "but enrollment is not clearly confirmed in the profile."
                )

        if _is_technology_emergency_match(identity_blob):
            technology_need_support = _profile_supports_technology_need(values_blob)
            if supports_enrollment:
                if technology_need_support:
                    _set_direct_match(match, score_floor=4)
                    if match.action not in ("review", "contact"):
                        match.action = "apply"
                    match.reasoning = (
                        "This page provides technology support for students, "
                        "and the profile includes technology-access barriers."
                    )
                else:
                    _set_general_resource(match, score_cap=3)
                    match.reasoning = (
                        "This is a general technology support resource. "
                        "The profile already shows technology access, so this is lower priority."
                    )
            else:
                _set_needs_info_match(match, score_cap=3)
                match.reasoning = (
                    "This may be relevant because the page offers technology support, "
                    "but enrollment is not clearly confirmed in the profile."
                )

        if _is_graduate_assistantship_match(identity_blob) and not forced_grad_or_employee_downgrade:
            graduate_support = _profile_supports_graduate_or_employee(values_blob)
            graduate_contradiction = _profile_contradicts_graduate_or_employee(values_blob)
            if graduate_support:
                _set_direct_match(match, score_floor=4)
                if match.action not in ("review", "contact"):
                    match.action = "apply"
            elif graduate_contradiction:
                _set_not_likely(match, score_cap=2)
                match.reasoning = (
                    "This benefit is mainly for graduate students or eligible employees. "
                    "The current profile does not show that fit."
                )
            else:
                _set_needs_info_match(match, score_cap=3)
                match.reasoning = (
                    "This benefit may be relevant, but graduate or employee eligibility is not confirmed."
                )

        if _is_veterans_book_grant_match(identity_blob):
            veteran_support = _profile_supports_veteran(values_blob)
            veteran_contradiction = _profile_contradicts_veteran(values_blob)
            if veteran_contradiction:
                _set_not_eligible(
                    match,
                    "hard gate: Veterans grant requires military-connected profile support",
                )
                rejected.append(match)
                continue
            if veteran_support:
                _set_direct_match(match, score_floor=4)
                if match.action not in ("review", "contact"):
                    match.action = "apply"
            else:
                _set_needs_info_match(match, score_cap=3)
                match.reasoning = (
                    "This page is targeted to military-connected students, "
                    "but the profile does not confirm that status."
                )

        if _is_open_access_priority_benefit(requirement_text) and has_priority_language:
            if match.match_type == "":
                if supports_enrollment:
                    _set_general_resource(match, score_cap=3)
                    match.reasoning = (
                        "This page describes a broadly available student resource with priority criteria. "
                        "The profile does not confirm every priority factor."
                    )
                else:
                    _set_needs_info_match(match, score_cap=3)
                    match.reasoning = (
                        "This may be relevant because the page describes a student resource, "
                        "but enrollment is not clearly confirmed in the profile."
                    )

        if match.eligibility_status == "":
            if pending_needs_info:
                _set_needs_info_match(match, score_cap=3)
            elif has_hard_requirements and not supports_enrollment:
                _set_needs_info_match(match, score_cap=2)
            else:
                _set_likely_eligible(match)
                if match.match_type == "":
                    match.match_type = "general_resource"

        if match.eligibility_status == "not_eligible":
            if not getattr(match, "rejection_reason", ""):
                match.rejection_reason = "hard gate: profile contradicts a hard requirement"
            rejected.append(match)
            continue

        if match.match_type not in ALLOWED_MATCH_TYPES:
            match.match_type = ""

        if match.match_type == "direct_match" and match.eligibility_status == "":
            match.eligibility_status = "likely_eligible"

        if match.match_type == "general_resource":
            if match.action not in ("review", "contact"):
                match.action = "review"
            match.relevance_score = min(match.relevance_score, 3)
            if match.eligibility_status == "":
                match.eligibility_status = "likely_eligible"

        if match.match_type == "aspirational":
            match.action = "review"
            match.relevance_score = min(match.relevance_score, 3)
            if match.eligibility_status == "":
                match.eligibility_status = "needs_info"

        if match.match_type == "needs_info":
            if match.action not in ("review", "contact"):
                match.action = "review"
            match.relevance_score = min(match.relevance_score, 3)
            if match.eligibility_status == "":
                match.eligibility_status = "needs_info"

        if match.match_type == "not_likely":
            match.action = "review"
            match.relevance_score = min(match.relevance_score, 2)
            if match.eligibility_status == "":
                match.eligibility_status = "needs_info"

        if match.eligibility_status == "needs_info" and match.action not in ("review", "contact"):
            match.action = "review"
            match.relevance_score = min(match.relevance_score, 3)

        if match.action == "apply" and match.eligibility_status in ("needs_info", "not_eligible"):
            match.action = "review"
            match.relevance_score = min(match.relevance_score, 3)

        if match.action == "apply" and match.match_type in ("aspirational", "needs_info", "not_likely"):
            match.action = "review"
            match.relevance_score = min(match.relevance_score, 3)

        if match.match_type == "needs_info" and not (match.reasoning or "").strip():
            match.reasoning = (
                "This may be relevant because the page describes a real student benefit. "
                "The profile does not confirm all hard eligibility details yet."
            )

        accepted.append(match)

    accepted, collapsed = _collapse_prehealth_components(accepted)
    rejected.extend(collapsed)
    return accepted, rejected


def normalize_output_matches(matches):
    normalized = []
    for match in matches:
        eligibility_status = str(getattr(match, "eligibility_status", "") or "").strip()
        match_type = str(getattr(match, "match_type", "") or "").strip()
        evidence_type = str(getattr(match, "evidence_type", "") or "").strip().lower()

        if eligibility_status == "not_eligible":
            continue

        if not match_type:
            if eligibility_status == "needs_info":
                match_type = "needs_info"
            elif eligibility_status == "likely_eligible":
                match_type = "general_resource"
            else:
                match_type = "general_resource"

        if match_type not in ALLOWED_MATCH_TYPES:
            match_type = "general_resource"

        if match_type == "direct_match" and not eligibility_status:
            eligibility_status = "likely_eligible"

        if match_type == "general_resource":
            if match.action not in ("review", "contact"):
                match.action = "review"
            match.relevance_score = min(match.relevance_score, 3)
            if not eligibility_status:
                eligibility_status = "likely_eligible"

        if match_type == "aspirational":
            match.action = "review"
            match.relevance_score = min(match.relevance_score, 3)
            if not eligibility_status:
                eligibility_status = "needs_info"

        if match_type == "needs_info":
            if match.action not in ("review", "contact"):
                match.action = "review"
            match.relevance_score = min(match.relevance_score, 3)
            eligibility_status = "needs_info"

        if match_type == "not_likely":
            match.action = "review"
            match.relevance_score = min(match.relevance_score, 2)
            if not eligibility_status:
                eligibility_status = "needs_info"

        if eligibility_status == "needs_info" and match.action not in ("review", "contact"):
            match.action = "review"
        if match.action == "apply" and eligibility_status in ("needs_info", "not_eligible"):
            match.action = "review"
        if match.action == "apply" and match_type in ("aspirational", "needs_info", "not_likely"):
            match.action = "review"

        if evidence_type == "keyword-detection":
            match.action = "review"
            match.relevance_score = min(match.relevance_score, 2)
            if match_type == "direct_match":
                match_type = "general_resource"

        match.eligibility_status = eligibility_status
        match.match_type = match_type
        normalized.append(match)

    return normalized


def sanitize_match_text_fields(matches):
    emdash = chr(8212)
    broken_emdash = "\u00e2\u20ac\u201d"
    for match in matches:
        match.summary = str(match.summary or "").replace(emdash, "-").replace(broken_emdash, "-")
        match.reasoning = str(match.reasoning or "").replace(emdash, "-").replace(broken_emdash, "-")
        match.action_details = str(match.action_details or "").replace(emdash, "-").replace(broken_emdash, "-")
        match.evidence_quote = str(match.evidence_quote or "").replace(emdash, "-").replace(broken_emdash, "-")
    return matches

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


# -- hostname helpers ------------------------------------------------------

# Parses a URL or bare domain into a clean lowercase hostname without www.
def _clean_hostname(url_or_domain):
    if not url_or_domain:
        return ""
    raw = url_or_domain.strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    hostname = urlparse(raw).netloc.lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    hostname = hostname.rstrip(".")
    return hostname


# Returns True if hostname equals domain or is a subdomain of it.
def _hostname_matches_domain(hostname, domain):
    h = _clean_hostname(hostname)
    d = _clean_hostname(domain)
    if not h or not d:
        return False
    return h == d or h.endswith("." + d)


# Questions that may contain the user's home school domain(s).
_DOMAIN_QUESTIONS = [
    "what is your school's website domain?",
    "what is your school website domain?",
    "what is your institution website domain?",
    "what is your institution's website domain?",
    "what school websites should be treated as your school or target schools?",
]


# Extracts home domains from the user's answers if a domain question exists.
# Returns a list of cleaned domain strings, or empty list if none found.
def _extract_user_home_domains(answers):
    for question, section_dict in answers.items():
        if question.lower() in _DOMAIN_QUESTIONS:
            for _section, value in section_dict.items():
                raw = str(value).strip()
                if not raw:
                    continue
                parts = [_clean_hostname(p.strip()) for p in raw.split(",")]
                return [p for p in parts if p]
    return []


# -- institution classification --------------------------------------------

# Returns a local window of page text around the evidence quote.
def _local_evidence_window(evidence_quote, page_text, radius=1000):
    quote_norm = " ".join((evidence_quote or "").lower().split())
    page_norm = " ".join(page_text.lower().split())
    if not quote_norm:
        return ""
    idx = page_norm.find(quote_norm)
    if idx == -1:
        return ""
    start = max(0, idx - radius)
    end = min(len(page_norm), idx + len(quote_norm) + radius)
    return page_norm[start:end]


# Determines whether a match is from the student's home institution, a broadly
# available source, or a different school.
# Returns one of: "home", "broad", "other", "unknown".
def _classify_institution_scope(match, page_text, user_home_domains):
    hostname = _clean_hostname(match.page_url)
    if not hostname:
        return "unknown"

    if not user_home_domains:
        return "home"

    if any(_hostname_matches_domain(hostname, d) for d in user_home_domains):
        return "home"

    candidate_text = " ".join([
        match.benefit_name or "",
        match.summary or "",
        match.reasoning or "",
        match.action_details or "",
        match.evidence_quote or "",
    ]).lower()

    local_window = _local_evidence_window(match.evidence_quote, page_text)

    if any(m in candidate_text or m in local_window
           for m in CROSS_INSTITUTION_MARKERS):
        return "broad"

    return "other"


# Nudges a match from a different school: subtracts 1 from score and tags it.
def _apply_other_school_nudge(match):
    match.relevance_score = max(1, match.relevance_score - 1)
    match.institution_scope = "other"


# -- main validator --------------------------------------------------------

# Validates proposed matches from the matcher. Returns (valid, rejected).
# Each rejected match gets a rejection_reason attribute.
# scraped_lookup: {url: (title, text)} from matcher.load_scraped_lookup.
def validate_matches(matches, scraped_lookup, answers=None, user_home_domains=None):
    if user_home_domains is None:
        user_home_domains = _extract_user_home_domains(answers or {})
    valid = []
    rejected = []

    for match in matches:
        reason = _validate_single(match, scraped_lookup, user_home_domains)
        if reason:
            match.rejection_reason = reason
            rejected.append(match)
        else:
            valid.append(match)

    return valid, rejected


# Runs all validation checks on a single match.
# Returns a rejection reason string, or None if the match is valid.
def _validate_single(match, scraped_lookup, user_home_domains=None):
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

    # 3b. Evidence proximity check
    ok, prox_err = _check_evidence_proximity(
        match.evidence_quote, match.benefit_name, page_text
    )
    if not ok:
        return f"evidence check failed: {prox_err}"

    # 3c. Institution scope classification
    scope = _classify_institution_scope(match, page_text, user_home_domains or [])
    if scope == "other":
        _apply_other_school_nudge(match)
    elif scope == "home":
        match.institution_scope = "home"
    elif scope == "broad":
        match.institution_scope = "broad"

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


_INCIDENTAL_MENTION_PHRASES = [
    "may combine with",
    "can be combined with",
    "related resources",
    "learn more",
    "other support",
    "links",
    "see also",
]

_GENERIC_BENEFIT_SUBJECT_TERMS = {
    "FAFSA/TASFA Application": ["fafsa", "tasfa"],
    "Work-Study / Student Employment": ["work-study", "work study", "student employment", "career center"],
    "Scholarship Opportunities": ["scholarship", "scholarships"],
    "Tuition Assistance / Fee Waiver": ["tuition assistance", "tuition advantage", "fee waiver"],
    "Student Health Insurance": ["student health insurance", "student health plan", "health plan"],
    "Counseling / Mental Health Services": ["counseling", "counseling services", "counseling center", "crisis line"],
}


def _canonical_page_benefit_name(title, url):
    clean_title = (title or "").strip()
    if clean_title:
        if " | " in clean_title:
            clean_title = clean_title.split(" | ", 1)[0].strip()
        return clean_title

    path = urlparse(url or "").path.strip("/")
    if not path:
        return url
    slug = path.split("/")[-1]
    slug = re.sub(r"\.html?$", "", slug, flags=re.IGNORECASE)
    slug = slug.replace("-", " ").replace("_", " ").strip()
    return slug.title() if slug else url


def _generic_name_is_subject_level(generic_name, title, url):
    terms = _GENERIC_BENEFIT_SUBJECT_TERMS.get(generic_name, [])
    if not terms:
        return False
    source = f"{title or ''} {url or ''}".lower()
    return any(term in source for term in terms)


def _choose_keyword_candidate_benefit_name(hit, title, url):
    canonical = _canonical_page_benefit_name(title, url)
    detected_name = str(hit.get("benefit_name") or "").strip()
    if detected_name and _generic_name_is_subject_level(detected_name, title, url):
        return detected_name
    return canonical or detected_name or (url or "")


def _is_keyword_subject_level(keyword, url, title, page_text):
    keyword_norm = str(keyword or "").strip().lower()
    if not keyword_norm:
        return False

    title_lower = (title or "").lower()
    url_lower = (url or "").lower()
    words = (page_text or "").lower().split()
    first_200_words = " ".join(words[:200])
    first_content_block = " ".join(words[:80])

    if (
        keyword_norm in title_lower
        or keyword_norm in url_lower
        or keyword_norm in first_200_words
        or keyword_norm in first_content_block
    ):
        return True

    page_lower = (page_text or "").lower()
    positions = [m.start() for m in re.finditer(re.escape(keyword_norm), page_lower)]
    if not positions:
        return False

    all_incidental = True
    for pos in positions:
        start = max(0, pos - 120)
        end = min(len(page_lower), pos + 120)
        context = page_lower[start:end]
        if not any(phrase in context for phrase in _INCIDENTAL_MENTION_PHRASES):
            all_incidental = False
            break

    if all_incidental:
        return False
    return False


def _reason_indicates_hard_profile_contradiction(reason):
    lower = str(reason or "").strip().lower()
    if not lower:
        return False

    if "hard gate:" in lower and _contains_any(lower, [
        "contradict",
        "requires",
        "not eligible",
    ]):
        return True

    if _contains_any(lower, [
        "profile contradict",
        "not eligible",
        "requires dependent child",
        "requires military",
        "requires veteran",
    ]):
        return True

    if "pass2 rejected" not in lower and "rejected" not in lower:
        return False

    has_requirement_term = _contains_any(lower, [
        "dependent",
        "student parent",
        "veteran",
        "active-duty",
        "graduate",
        "gpa",
        "full-time",
        "full time",
        "out-of-state",
        "out of state",
        "national merit",
        "health insurance",
        "live on campus",
    ])
    has_negative_term = _contains_any(lower, [
        " no ",
        " not ",
        "does not",
        "without",
        "below",
        "under",
        "missing",
    ])
    return has_requirement_term and has_negative_term


def _page_mentions_dependent_requirement(title, page_text):
    lower = " ".join([str(title or "").lower(), str(page_text or "").lower()])
    if not lower:
        return False
    return _contains_any(lower, [
        "dependent child",
        "dependent children",
        "at least one dependent",
        "student parent",
        "students with children",
        "parenting student",
    ])


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

def _detect_fafsa(url, title, page_text, answers, profile_signals=None):
    lower = page_text.lower()
    if "fafsa" not in lower and "tasfa" not in lower:
        return None

    has_fafsa = None
    if isinstance(profile_signals, dict):
        has_fafsa = profile_signals.get("has_fafsa")
    if has_fafsa is not False:
        return None

    keyword = "FAFSA" if "fafsa" in lower else "TASFA"
    return {
        "benefit_name": "FAFSA/TASFA Application",
        "action": "apply",
        "tags": ["financial-aid"],
        "summary": f"{title or url} describes {keyword} - you haven't applied for financial aid yet.",
        "reasoning": f"Detected by keyword matching: '{keyword}' found on page, "
                     f"relevant because student has not applied for financial aid.",
        "detected_keyword": keyword,
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

def _detect_counseling(url, title, page_text, answers, profile_signals=None):
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
        "summary": f"{title or url} offers counseling or crisis services - "
                   f"relevant to your health history.",
        "reasoning": f"Detected by keyword matching: '{found_keyword}' found on page, "
                     f"relevant because student health history mentions mental health needs.",
        "detected_keyword": found_keyword,
        "evidence_quote": _extract_evidence_sentence(page_text, found_keyword),
        "inferred_from": ["Please describe your health history."],
    }


def _detect_scholarships(url, title, page_text, answers, profile_signals=None):
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
        "summary": f"{title or url} lists multiple scholarships - "
                   f"you're not currently receiving any.",
        "reasoning": f"Detected by keyword matching: 'scholarship' appears {count} times on page, "
                     f"relevant because student is not receiving scholarships.",
        "detected_keyword": "scholarship",
        "evidence_quote": _extract_evidence_sentence(page_text, "scholarship"),
        "inferred_from": ["Are you currently receiving any scholarships?",
                          "What is the total annual scholarship amount?"],
    }


def _detect_work_study(url, title, page_text, answers, profile_signals=None):
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
        "summary": f"{title or url} has student employment resources - "
                   f"relevant to your job search.",
        "reasoning": f"Detected by keyword matching: '{keyword}' found on page, "
                     f"relevant because student is unemployed or seeking work.",
        "detected_keyword": keyword,
        "evidence_quote": _extract_evidence_sentence(page_text, keyword),
        "inferred_from": ["What is your current employment status?"],
    }


def _detect_tuition_assistance(url, title, page_text, answers, profile_signals=None):
    lower = page_text.lower()
    has_keyword = ("tuition advantage" in lower or "tuition assistance" in lower
                   or "fee waiver" in lower)
    if not has_keyword:
        return None

    has_fafsa = None
    if isinstance(profile_signals, dict):
        has_fafsa = profile_signals.get("has_fafsa")
    if has_fafsa is not False:
        return None

    keyword = next(kw for kw in ["tuition advantage", "tuition assistance",
                                  "fee waiver"] if kw in lower)
    return {
        "benefit_name": "Tuition Assistance / Fee Waiver",
        "action": "review",
        "tags": ["tuition", "financial-aid"],
        "summary": f"{title or url} describes tuition assistance - "
                   f"you haven't applied for financial aid yet.",
        "reasoning": f"Detected by keyword matching: '{keyword}' found on page, "
                     f"relevant because student has not applied for financial aid.",
        "detected_keyword": keyword,
        "evidence_quote": _extract_evidence_sentence(page_text, keyword),
        "inferred_from": ["Have you applied for financial aid?"],
    }


def _detect_health_insurance(url, title, page_text, answers, profile_signals=None):
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
        "summary": f"{title or url} describes a student health plan - "
                   f"you don't currently have health insurance.",
        "reasoning": f"Detected by keyword matching: '{keyword}' found on page, "
                     f"relevant because student has no health insurance.",
        "detected_keyword": keyword,
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
                           pipeline_run_id="", rejected_matches=None):
    # Figure out which pages already have valid matches
    pages_with_matches = {m.page_url for m in existing_matches}
    profile_signals = build_profile_signals(answers or {})

    blocked_urls = set()
    for rejected_match in (rejected_matches or []):
        if isinstance(rejected_match, dict):
            rejected_url = str(rejected_match.get("page_url") or "").strip()
            rejection_reason = str(rejected_match.get("rejection_reason") or "").strip()
        else:
            rejected_url = str(getattr(rejected_match, "page_url", "") or "").strip()
            rejection_reason = str(getattr(rejected_match, "rejection_reason", "") or "").strip()
        if rejected_url and _reason_indicates_hard_profile_contradiction(rejection_reason):
            blocked_urls.add(rejected_url)

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
        if url in blocked_urls:
            continue

        for rule_fn in _DETECTION_RULES:
            hit = rule_fn(url, title, page_text, answers, profile_signals=profile_signals)
            if not hit:
                continue

            detected_keyword = str(hit.get("detected_keyword") or "").strip()
            if not _is_keyword_subject_level(detected_keyword, url, title, page_text):
                continue

            if (
                profile_signals.get("has_dependents") is False
                and _page_mentions_dependent_requirement(title, page_text)
            ):
                continue

            # Dedup: skip if this page + tag category already covered
            hit_tags = hit.get("tags", [])
            if any((url, tag) in existing_categories for tag in hit_tags):
                continue

            benefit_name = _choose_keyword_candidate_benefit_name(hit, title, url)
            summary = hit["summary"]
            if not summary.startswith("Possible benefit candidate:"):
                summary = f"Possible benefit candidate: {summary}"

            raw_relevance_score = hit.get("relevance_score", 2)
            try:
                relevance_score = int(raw_relevance_score)
            except (TypeError, ValueError):
                relevance_score = 2
            relevance_score = min(2, relevance_score)

            result = MatchResult(
                match_id=str(uuid.uuid4()),
                page_url=url,
                page_title=title,
                source_type=_detect_source_type(url),
                relevance_score=relevance_score,
                benefit_name=benefit_name,
                action="review",
                summary=summary,
                reasoning=hit["reasoning"],
                action_details="",
                evidence_quote=hit["evidence_quote"],
                evidence_type="keyword-detection",
                eligibility_status="needs_info",
                match_type="general_resource",
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

