# matcher.py -- Sends filtered pages + user profile to the LLM for detailed
# benefit analysis. Each page that passed the keyword filter gets a structured
# prompt with the user's profile, applicable heuristic rules, and the page
# content. The LLM returns JSON matching the MatchResult schema.

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

from matching.models import MatchResult, CrossReference
from matching.profile_signals import build_profile_signals
from matching.rules import format_hints_for_prompt

MATCH_MODEL = ollama_client.DEFAULT_MODEL


# Figures out whether a URL is .edu, .gov, or something else.
def detect_source_type(url):
    host = urlparse(url).netloc.lower()
    if host.endswith(".edu") or ".edu." in host:
        return "edu"
    if host.endswith(".gov") or ".gov." in host:
        return "gov"
    return "custom"


# Builds a structured profile summary from the user's answers dict.
# answers format: {question_text: {section_name: answer_value}}
def format_profile(answers):
    labels = {
        "What is your full legal name?": "Name",
        "What is your date of birth?": "Date of birth",
        "What is your current address?": "Address",
        "What is your gender?": "Gender",
        "Are you a student?": "Student",
        "What is your institution name?": "Institution",
        "What is your current GPA?": "GPA",
        "Please describe your health history.": "Health history",
        "What is your current employment status?": "Employment",
        "Do you currently have health insurance?": "Health insurance",
        "Are you covered under a parent/guardian plan?": "Parent/guardian plan",
        "Do you take any regular medications?": "Regular medications",
        "Do you have car insurance?": "Car insurance",
        "Do you have renter's insurance?": "Renter's insurance",
        "Have you filed any claims in the last year?": "Claims filed",
        "Have you applied for financial aid?": "Applied for financial aid",
        "Are you currently receiving any scholarships?": "Receiving scholarships",
        "What is the total annual scholarship amount?": "Scholarship amount",
        "Do you have access to a student email address?": "Student email",
        "Are you enrolled in an accredited institution?": "Accredited institution",
    }

    lines = []
    for question, section_dict in answers.items():
        if question.startswith("No questions for"):
            continue
        for _section, answer in section_dict.items():
            answer = str(answer).strip()
            if not answer:
                continue
            label = labels.get(question, question)
            lines.append(f"- {label}: {answer}")
    return "\n".join(lines)


# Pulls the student's institution name from the answers dict.
def extract_user_institution(answers):
    entry = answers.get("What is your institution name?")
    if not entry:
        return ""
    for _section, value in entry.items():
        return str(value).strip()
    return ""


# Splits long page text on sentence boundaries so each chunk fits
# the LLM context window with room for the prompt and response.
def chunk_text(text, max_words=1500):
    words = text.split()
    if len(words) <= max_words:
        return [text]

    chunks = []
    sentences = re.split(r'(?<=[.!?])\s+', text)
    current = []
    current_len = 0

    for sentence in sentences:
        sentence_len = len(sentence.split())
        if current_len + sentence_len > max_words and current:
            chunks.append(" ".join(current))
            current = []
            current_len = 0
        current.append(sentence)
        current_len += sentence_len

    if current:
        chunks.append(" ".join(current))

    return chunks


SYSTEM_PROMPT = r"""
You are a broad but grounded benefit classifier.

You will receive one student profile and one web page.

Return ONLY items that satisfy BOTH conditions:
1. The item is explicitly described on the page.
2. The item is a real benefit or actionable support resource for students.

If condition 1 fails, do not include it.
If nothing qualifies, return [].

Valid items:
- scholarship
- grant
- loan
- work-study
- financial aid program
- FAFSA/TASFA help
- tuition assistance
- fee waiver
- counseling service
- crisis line
- wellness service
- accessibility service
- student employment resource
- veteran service
- childcare support
- emergency support
- support office with contact info
- deadline directly tied to aid, access, or a support resource

Invalid items by themselves:
- degree programs
- certificate programs
- majors
- graduate program lists
- admissions pages
- application pathways
- general academic deadlines
- online/campus delivery modes
- guessed interests
- common university practices

Do NOT:
- invent counseling, financial aid, insurance, scholarships, or deadlines
- invent user facts that are not in the profile or profile signals
- guess from common college practice
- treat academic counseling programs as mental health counseling
- treat graduate program deadlines as financial aid deadlines
- output invalid action values

Do not infer attributes about the student that are not explicitly stated in the profile or profile signals.
This includes but is not limited to: interests, intended major, career goals, high school status, graduate status, military or veteran status, disability status, food insecurity, income level, housing situation, family composition, and immigration status.
If an attribute is not in the profile or profile signals, do not use it to justify a match.

The student's home institution is provided in the USER INSTITUTION field below.
If the web page belongs to a different institution, only include the item if the page explicitly shows that it is federal, statewide, transferable across institutions, publicly available to anyone, or explicitly open to non-students of that institution.
Institution-specific scholarships, programs, and services from a different institution should NOT be included.
Do not assume a benefit is federal, statewide, transferable, or public unless the page text supports that.

Allowed actions only:
apply
opt-in
opt-out
contact
review
be-aware

Use opt-out ONLY if the page explicitly says waiver, decline, opt-out, or default enrollment.

Allowed match_type values:
direct_match
general_resource
aspirational
needs_info
not_likely

match_type meaning:
- direct_match: the profile signals clearly support eligibility or relevance.
- general_resource: broadly useful to students but not specifically triggered by a need.
- aspirational: not currently supported but may become relevant if the student changes status, joins a program, improves GPA, changes major, transfers, applies for FAFSA, or meets future requirements.
- needs_info: the page may be relevant but the profile is missing a required fact.
- not_likely: the page is related but likely not a fit.

Scoring rubric for relevance_score:
5 = Directly applies to the student based on explicit profile facts, from the student's home institution or a federal/statewide source, with clear action steps and clear page evidence.
4 = Strongly relevant but missing one detail, such as eligibility not fully confirmed.
3 = Useful to review, but not clearly actionable yet.
2 = Possibly related, but weak or speculative.
1 = General awareness only.

Do not output an item at score 5 unless all three conditions hold: profile supports it, source supports it, and action is clear.

Return ONLY valid JSON array.
Each item must contain:
benefit_name
relevance_score
action
summary
reasoning
action_details
evidence_quote
evidence_type
eligibility_status
match_type
inferred_from
tags

For inferred_from:
- Include only student facts that are explicitly present in STUDENT PROFILE or PROFILE SIGNALS.
- Do not include page eligibility requirements unless those requirements are explicitly present in student facts.
- If no supporting student facts are present, use [].

Every item must include a short evidence_quote copied from the page.
If you cannot provide evidence_quote, do not include the item.
"""


# Builds the user-side prompt for one page.
def build_user_prompt(profile_text, profile_signals_text, hints_text, user_institution, url, title, page_text):
    return f"""
STUDENT PROFILE
{profile_text}

PROFILE SIGNALS
{profile_signals_text or "None"}

The profile signals are normalized facts extracted from the student's answers.
The model may use these signals as the source of truth for student facts.
The model must still only return benefits explicitly described on the page.

USER INSTITUTION
{user_institution or "Unknown"}

MATCHING HINTS
{hints_text or "None"}

WEB PAGE
URL: {url}
Title: {title}

PAGE TEXT
{page_text}

TASK
Return only page-grounded benefits or actionable student resources relevant to this student.
Remember:
- Degree programs, certificates, majors, and general admissions deadlines are not benefits by themselves.
- Counseling as an academic specialization is not mental health counseling.
- If the page does not clearly contain a relevant benefit or actionable support resource, return [].
- inferred_from must list only facts present in STUDENT PROFILE or PROFILE SIGNALS.
- Output only a JSON array.
""".strip()


def format_profile_signals_for_prompt(profile_signals):
    if not isinstance(profile_signals, dict):
        return ""

    private_keys = {
        "name",
        "full_name",
        "address",
        "date_of_birth",
        "dob",
        "phone",
        "email",
        "id",
        "student_id",
        "ssn",
    }
    lines = []
    ordered_keys = [
        "student",
        "institution",
        "classification",
        "full_time",
        "major_terms",
        "gpa",
        "has_fafsa",
        "insured",
        "veteran",
        "has_dependents",
        "food_insecurity",
        "has_laptop",
        "reliable_internet",
        "on_campus",
        "has_meal_plan",
        "honors",
        "national_merit",
        "out_of_state",
        "first_generation",
        "low_income",
        "positive_terms",
        "negative_terms",
    ]

    for key in ordered_keys:
        if key in private_keys:
            continue
        if key not in profile_signals:
            continue
        value = profile_signals.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            text = value.strip()
            if not text:
                continue
        elif isinstance(value, list):
            if not value:
                continue
            text = ", ".join(str(v).strip() for v in value if str(v).strip())
            if not text:
                continue
        elif isinstance(value, bool):
            text = "true" if value else "false"
        else:
            text = str(value).strip()
            if not text:
                continue
        lines.append(f"- {key}: {text}")
    return "\n".join(lines)


def _normalize_free_text(text):
    lowered = str(text or "").strip().lower()
    lowered = re.sub(r"[^a-z0-9.]+", " ", lowered)
    return " ".join(lowered.split())


def _coerce_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [value]
    return []


def _filter_inferred_from(raw_value, profile_text, profile_signals_text):
    source_blob = _normalize_free_text(
        " ".join([profile_text or "", profile_signals_text or ""])
    )
    if not source_blob:
        return []

    filtered = []
    seen = set()
    for item in _coerce_list(raw_value):
        clean = str(item or "").strip()
        if not clean:
            continue
        normalized = _normalize_free_text(clean)
        if not normalized:
            continue
        if normalized not in source_blob:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        filtered.append(clean)
    return filtered


# Tries to extract a JSON array from the LLM response, handling markdown
# fences and commentary.
def parse_response_json(response_text):
    start = response_text.find("[")
    end = response_text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        return json.loads(response_text[start:end + 1])
    except json.JSONDecodeError:
        return []


# Converts a raw benefit dict from the LLM into a MatchResult dataclass.
# LLMs sometimes return null for fields, so we coalesce None to safe defaults.
def to_match_result(raw, url, title, source_type, pipeline_run_id, profile_text="", profile_signals_text=""):
    allowed_eligibility_status = {"likely_eligible", "needs_info", "not_eligible"}
    allowed_match_types = {
        "direct_match",
        "general_resource",
        "aspirational",
        "needs_info",
        "not_likely",
    }

    score = raw.get("relevance_score")
    try:
        score = max(1, min(5, int(score)))
    except (TypeError, ValueError):
        score = 1

    eligibility_status = str(raw.get("eligibility_status") or "").strip()
    if eligibility_status not in allowed_eligibility_status:
        eligibility_status = ""

    match_type = str(raw.get("match_type") or "").strip()
    if match_type not in allowed_match_types:
        match_type = ""

    return MatchResult(
        match_id=str(uuid.uuid4()),
        page_url=url,
        page_title=title,
        source_type=source_type,
        relevance_score=score,
        benefit_name=raw.get("benefit_name") or "",
        action=raw.get("action") or "be-aware",
        summary=raw.get("summary") or "",
        reasoning=raw.get("reasoning") or "",
        action_details=raw.get("action_details") or "",
        evidence_quote=raw.get("evidence_quote") or "",
        evidence_type=raw.get("evidence_type") or "",
        eligibility_status=eligibility_status,
        match_type=match_type,
        cross_references=[],
        inferred_from=_filter_inferred_from(
            raw.get("inferred_from"),
            profile_text,
            profile_signals_text,
        ),
        tags=[raw.get("tags")] if isinstance(raw.get("tags"), str) else (raw.get("tags") or []),
        matched_at=datetime.now().isoformat(),
        pipeline_run_id=pipeline_run_id,
        status="new",
    )


# Loads all scraped pages from the output directory into a dict keyed
# by URL for fast lookup. Returns {url: (title, text)}.
def load_scraped_lookup(scraped_dir):
    lookup = {}
    for filepath in sorted(scraped_dir.glob("scraped_*.txt")):
        content = filepath.read_text(encoding="utf-8")
        pages = re.split(r"\n--- (https?://\S+) ---\n", content)

        for i in range(1, len(pages) - 1, 2):
            url = pages[i]
            body = pages[i + 1]

            title = ""
            text_lines = []
            for line in body.splitlines():
                if line.startswith("Title: "):
                    title = line[7:]
                elif line.startswith("Hash: "):
                    continue
                else:
                    text_lines.append(line)

            text = " ".join(text_lines).strip()
            if text:
                lookup[url] = (title, text)
    return lookup


# Matches a single page against the user's profile. Chunks the page text
# if needed and calls phi3 for each chunk. Returns a list of MatchResults.
def match_page(url, title, page_text, profile_text, profile_signals_text, hints_text, user_institution,
               source_type, pipeline_run_id, model=MATCH_MODEL, llm_options=None):
    chunks = chunk_text(page_text)
    results = []

    for chunk in chunks:
        prompt = build_user_prompt(
            profile_text,
            profile_signals_text,
            hints_text,
            user_institution,
            url,
            title,
            chunk,
        )

        try:
            response = ollama_client.generate(
                prompt, system=SYSTEM_PROMPT, model=model, options=llm_options
            )
            raw_benefits = parse_response_json(response)

            for raw in raw_benefits:
                result = to_match_result(
                    raw, url, title, source_type, pipeline_run_id,
                    profile_text=profile_text,
                    profile_signals_text=profile_signals_text,
                )
                if result.action != "not-relevant":
                    results.append(result)

        except Exception as exc:
            print(f"    Error: {exc}")

    return results


# Main entry point for the matching stage.
# Takes keyword-filtered pages (from filter.py) and runs the LLM matcher.
# scraped_lookup format: {url: (title, text)}.
def match_pages(answers, filtered_pages, scraped_dir=None, scraped_lookup=None,
                pipeline_run_id="", model=MATCH_MODEL, delay=5, llm_options=None):
    ok, err = ollama_client.check_ollama(model)
    if not ok:
        raise ConnectionError(err)

    profile_text = format_profile(answers)
    profile_signals = build_profile_signals(answers)
    profile_signals_text = format_profile_signals_for_prompt(profile_signals)
    hints_text = format_hints_for_prompt(answers)
    user_institution = extract_user_institution(answers)

    if scraped_lookup is not None:
        scraped = scraped_lookup
    elif scraped_dir is not None:
        scraped = load_scraped_lookup(scraped_dir)
    else:
        raise ValueError("match_pages requires either scraped_lookup or scraped_dir")
    all_results = []
    matched_count = 0

    for i, page in enumerate(filtered_pages, 1):
        url = page["url"]
        entry = scraped.get(url)
        if not entry:
            print(f"  [{i}/{len(filtered_pages)}] {url} -- no scraped text, skipping")
            continue

        title, text = entry
        source_type = detect_source_type(url)
        gate_reason = page.get("filter_reason", "")
        categories = page.get("keyword_categories", [])
        category_text = f" categories={','.join(categories)}" if categories else ""
        reason_text = f" gate={gate_reason}" if gate_reason else ""

        chunks = chunk_text(text)
        chunk_label = f" ({len(chunks)} chunks)" if len(chunks) > 1 else ""
        print(
            f"  [{i}/{len(filtered_pages)}] Matching {url}"
            f"{reason_text}{category_text}{chunk_label}..."
        )

        results = match_page(
            url, title, text, profile_text, profile_signals_text, hints_text, user_institution,
            source_type, pipeline_run_id, model, llm_options
        )

        if results:
            matched_count += len(results)
            all_results.extend(results)
            for r in results:
                print(f"    -> {r.action}: {r.summary[:80]}... "
                      f"(score: {r.relevance_score})")
        else:
            print(f"    No matches")

        # Delay between pages so phi3 isn't overwhelmed
        if i < len(filtered_pages):
            time.sleep(delay)

    print(f"  {matched_count} benefit(s) found across "
          f"{len(filtered_pages)} page(s).")
    return all_results

