# filter.py -- Keyword pre-filter for benefit pages.
# Purpose: quickly answer "does this page talk about benefits at all?"
# without running embeddings. Student-specific relevance is handled later
# by the LLM matcher.

import re
from urllib.parse import urlparse

# Category -> strong benefit keywords/phrases.
# Generic words like "apply" or "deadline" are intentionally excluded,
# because they create too many false positives on non-benefit pages.
BENEFIT_KEYWORDS = {
    "scholarship": {
        "scholarship", "scholarships", "fellowship", "fellowships", "stipend",
    },
    "grant": {
        "grant", "grants", "pell grant", "fseog", "institutional grant",
    },
    "financial-aid": {
        "financial aid", "student aid", "aid package", "cost of attendance",
        "fafsa", "tasfa", "financial assistance",
    },
    "loan": {
        "student loan", "student loans", "federal loan", "subsidized loan",
        "unsubsidized loan", "parent plus", "loan counseling",
    },
    "tuition": {
        "tuition assistance", "tuition advantage", "tuition waiver",
        "fee waiver", "waiver", "tuition support",
    },
    "employment": {
        "work-study", "work study", "student employment", "campus job",
        "on-campus employment", "career center",
    },
    "mental-health": {
        "counseling center", "counseling services", "mental health",
        "crisis line", "therapy", "wellness center", "timelycare",
    },
    "health": {
        "student health", "health services", "health insurance",
        "student health insurance", "health plan",
    },
    "emergency": {
        "emergency fund", "emergency grant", "emergency assistance",
        "hardship", "basic needs", "crisis support",
    },
    "housing-food": {
        "housing assistance", "rent assistance", "food pantry",
        "meal assistance", "meal swipe", "housing insecurity",
    },
    "accessibility": {
        "disability services", "accessibility services", "accommodations",
        "ada", "student accessibility", "assistive technology",
    },
    "veteran": {
        "veteran services", "va benefits", "gi bill", "military benefits",
    },
    "childcare": {
        "child care", "childcare", "dependent care", "parenting student",
    },
}

def _build_single_word_patterns(keyword_map):
    return {
        keyword: re.compile(rf"\b{re.escape(keyword)}\b")
        for keywords in keyword_map.values()
        for keyword in keywords
        if " " not in keyword and "-" not in keyword and "/" not in keyword
    }


BASE_SINGLE_WORD_PATTERNS = _build_single_word_patterns(BENEFIT_KEYWORDS)


def _normalize_text(text):
    return " ".join((text or "").lower().split())


def _normalize_keyword(keyword):
    return " ".join(str(keyword or "").lower().split())


def _normalize_extra_keywords(extra_keywords):
    normalized = {}
    if not isinstance(extra_keywords, dict):
        return normalized

    for category, keywords in extra_keywords.items():
        cat = _normalize_keyword(category)
        if not cat:
            continue

        values = []
        if isinstance(keywords, str):
            values = [keywords]
        elif isinstance(keywords, (list, tuple, set)):
            values = list(keywords)
        else:
            continue

        bucket = set()
        for kw in values:
            clean = _normalize_keyword(kw)
            if not clean:
                continue
            if len(clean) < 3 or len(clean) > 80:
                continue
            bucket.add(clean)

        if bucket:
            normalized[cat] = bucket

    return normalized


def _merge_keyword_maps(extra_keywords=None):
    merged = {category: set(keywords) for category, keywords in BENEFIT_KEYWORDS.items()}
    for category, keywords in _normalize_extra_keywords(extra_keywords).items():
        merged.setdefault(category, set()).update(keywords)
    return merged


def _keyword_present(normalized_text, keyword, single_word_patterns):
    if keyword in single_word_patterns:
        return single_word_patterns[keyword].search(normalized_text) is not None
    return keyword in normalized_text


# Custom (non-.edu/.gov) pages are user-curated and bypass keyword gating.
def _is_custom_domain(url):
    host = urlparse(url).netloc.lower()
    return not (
        host.endswith(".edu")
        or ".edu." in host
        or host.endswith(".gov")
        or ".gov." in host
    )


# Returns {category: [matched_keywords]}.
def detect_benefit_keywords(page_text, keyword_map=None, single_word_patterns=None):
    normalized = _normalize_text(page_text)
    if not normalized:
        return {}

    keyword_map = keyword_map or BENEFIT_KEYWORDS
    single_word_patterns = single_word_patterns or BASE_SINGLE_WORD_PATTERNS

    matched = {}
    for category, keywords in keyword_map.items():
        hits = [
            kw
            for kw in sorted(keywords)
            if _keyword_present(normalized, kw, single_word_patterns)
        ]
        if hits:
            matched[category] = hits
    return matched


# Main entry point for keyword pre-filtering.
# scraped_lookup format: {url: (title, text)}
# Returns (relevant, not_relevant), both lists of page-entry dicts.
def filter_pages(scraped_lookup, extra_keywords=None):
    if not scraped_lookup:
        print("  No scraped pages found.")
        return [], []

    keyword_map = _merge_keyword_maps(extra_keywords=extra_keywords)
    single_word_patterns = _build_single_word_patterns(keyword_map)

    relevant = []
    not_relevant = []
    custom_bypassed = 0

    for url, (title, text) in scraped_lookup.items():
        matches = detect_benefit_keywords(
            text,
            keyword_map=keyword_map,
            single_word_patterns=single_word_patterns,
        )
        categories = sorted(matches.keys())
        keyword_hits = sorted({kw for kws in matches.values() for kw in kws})

        entry = {
            "url": url,
            "title": title or "",
            "keyword_categories": categories,
            "keyword_hits": keyword_hits,
            "keyword_hit_count": len(keyword_hits),
        }

        if _is_custom_domain(url):
            entry["filter_reason"] = "custom-domain-bypass"
            relevant.append(entry)
            custom_bypassed += 1
        elif keyword_hits:
            entry["filter_reason"] = "benefit-keyword-match"
            relevant.append(entry)
        else:
            entry["filter_reason"] = "no-benefit-keywords"
            not_relevant.append(entry)

    relevant.sort(key=lambda x: (-x["keyword_hit_count"], x["url"]))
    not_relevant.sort(key=lambda x: x["url"])

    print(
        f"  Keyword pre-filter: {len(relevant)} relevant, "
        f"{len(not_relevant)} filtered out."
    )
    if extra_keywords:
        derived_count = sum(
            len(keywords) for keywords in _normalize_extra_keywords(extra_keywords).values()
        )
        if derived_count:
            print(f"  Added {derived_count} profile-derived keyword(s) to filter.")
    if custom_bypassed:
        print(f"  {custom_bypassed} custom page(s) bypassed keyword gate.")

    if relevant:
        category_counts = {}
        for page in relevant:
            for category in page.get("keyword_categories", []):
                category_counts[category] = category_counts.get(category, 0) + 1
        if category_counts:
            top = sorted(category_counts.items(), key=lambda x: (-x[1], x[0]))[:6]
            top_text = ", ".join(f"{name}:{count}" for name, count in top)
            print(f"  Top keyword categories: {top_text}")

    return relevant, not_relevant
