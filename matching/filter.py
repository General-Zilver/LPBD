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

SINGLE_WORD_PATTERNS = {
    keyword: re.compile(rf"\b{re.escape(keyword)}\b")
    for keywords in BENEFIT_KEYWORDS.values()
    for keyword in keywords
    if " " not in keyword and "-" not in keyword and "/" not in keyword
}


def _normalize_text(text):
    return " ".join((text or "").lower().split())


def _keyword_present(normalized_text, keyword):
    if keyword in SINGLE_WORD_PATTERNS:
        return SINGLE_WORD_PATTERNS[keyword].search(normalized_text) is not None
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
def detect_benefit_keywords(page_text):
    normalized = _normalize_text(page_text)
    if not normalized:
        return {}

    matched = {}
    for category, keywords in BENEFIT_KEYWORDS.items():
        hits = [kw for kw in sorted(keywords) if _keyword_present(normalized, kw)]
        if hits:
            matched[category] = hits
    return matched


# Main entry point for keyword pre-filtering.
# scraped_lookup format: {url: (title, text)}
# Returns (relevant, not_relevant), both lists of page-entry dicts.
def filter_pages(scraped_lookup):
    if not scraped_lookup:
        print("  No scraped pages found.")
        return [], []

    relevant = []
    not_relevant = []
    custom_bypassed = 0

    for url, (title, text) in scraped_lookup.items():
        matches = detect_benefit_keywords(text)
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
