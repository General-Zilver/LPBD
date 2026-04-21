# profile_keywords.py -- Optional profile-derived keyword expansion for the
# keyword pre-filter stage. Uses the student's questionnaire answers to infer
# extra benefit terms that may not exist in the base static dictionary.

import json

import ollama_client
from matching.profile_signals import build_profile_signals


ALLOWED_CATEGORIES = [
    "scholarship",
    "grant",
    "financial-aid",
    "loan",
    "tuition",
    "employment",
    "mental-health",
    "health",
    "emergency",
    "housing-food",
    "accessibility",
    "veteran",
    "childcare",
]

CATEGORY_ALIASES = {
    "scholarships": "scholarship",
    "grants": "grant",
    "financial aid": "financial-aid",
    "aid": "financial-aid",
    "loans": "loan",
    "mental health": "mental-health",
    "housing": "housing-food",
    "food": "housing-food",
    "disability": "accessibility",
    "disability services": "accessibility",
    "veterans": "veteran",
    "child care": "childcare",
}

SYSTEM_PROMPT = """
You build search keywords for a benefits discovery filter.

Given a student profile, output ONLY a JSON object with this shape:
{
  "category-name": ["keyword 1", "keyword 2"]
}

Rules:
- Use only categories from the provided allowed list.
- Include only terms likely to appear directly on web pages.
- Keep keywords short (1-4 words).
- Do not include names, addresses, IDs, or private details.
- Return {} when no useful additions exist.
- Output valid JSON only (no markdown or commentary).
""".strip()


def _profile_from_answers(answers):
    lines = []
    for question, section_dict in answers.items():
        if not isinstance(section_dict, dict):
            continue
        if question.startswith("No questions for"):
            continue
        for _section, value in section_dict.items():
            text = str(value or "").strip()
            if text:
                lines.append(f"- {question}: {text}")
    return "\n".join(lines)


def _extract_json_object(text):
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _normalize_category(category):
    clean = " ".join(str(category or "").lower().split())
    if not clean:
        return ""
    clean = CATEGORY_ALIASES.get(clean, clean)
    return clean if clean in ALLOWED_CATEGORIES else ""


def _normalize_keyword(keyword):
    clean = " ".join(str(keyword or "").lower().split())
    if not clean:
        return ""
    if len(clean) < 3 or len(clean) > 80:
        return ""
    return clean


def _add_keyword(keyword_map, category, keyword):
    cat = _normalize_category(category)
    clean = _normalize_keyword(keyword)
    if not cat or not clean:
        return
    keyword_map.setdefault(cat, set()).add(clean)


def _cap_keyword_map(keyword_map, max_per_category):
    capped = {}
    for category, keywords in (keyword_map or {}).items():
        clean_keywords = sorted({
            _normalize_keyword(k)
            for k in (keywords or [])
            if _normalize_keyword(k)
        })
        if clean_keywords:
            capped[category] = set(clean_keywords[:max_per_category])
    return capped


def _merge_keyword_maps(*maps, max_per_category=8):
    merged = {}
    for mapping in maps:
        for category, keywords in (mapping or {}).items():
            for keyword in (keywords or []):
                _add_keyword(merged, category, keyword)
    return _cap_keyword_map(merged, max_per_category=max_per_category)


def build_deterministic_profile_keyword_map(profile_signals, max_per_category=8):
    signals = profile_signals or {}
    keyword_map = {}

    major_terms = signals.get("major_terms") or []
    major_blob = " | ".join(major_terms)
    positive_terms = set(signals.get("positive_terms") or [])

    if signals.get("has_fafsa") is True:
        _add_keyword(keyword_map, "financial-aid", "fafsa")
        _add_keyword(keyword_map, "financial-aid", "tasfa")

    if signals.get("insured") is False:
        _add_keyword(keyword_map, "health", "student health insurance")
        _add_keyword(keyword_map, "health", "health plan")

    if signals.get("honors") is True:
        _add_keyword(keyword_map, "scholarship", "honors scholarship")
        _add_keyword(keyword_map, "grant", "honors grant")
        _add_keyword(keyword_map, "grant", "honors college")
        _add_keyword(keyword_map, "grant", "research conference")

    if signals.get("national_merit") is True:
        _add_keyword(keyword_map, "scholarship", "national merit")
        _add_keyword(keyword_map, "scholarship", "national merit scholarship")
        _add_keyword(keyword_map, "tuition", "nonresident tuition")
        _add_keyword(keyword_map, "tuition", "tuition waiver")

    if signals.get("out_of_state") is True:
        _add_keyword(keyword_map, "tuition", "out-of-state waiver")
        _add_keyword(keyword_map, "tuition", "nonresident tuition")
        _add_keyword(keyword_map, "tuition", "tuition waiver")

    if signals.get("has_dependents") is True:
        _add_keyword(keyword_map, "childcare", "childcare")
        _add_keyword(keyword_map, "childcare", "child care")
        _add_keyword(keyword_map, "childcare", "student parent")
        _add_keyword(keyword_map, "childcare", "dependent child")
        _add_keyword(keyword_map, "grant", "childcare grant")

    if signals.get("food_insecurity") is True or signals.get("low_income") is True:
        _add_keyword(keyword_map, "housing-food", "food pantry")
        _add_keyword(keyword_map, "housing-food", "basic needs")
        _add_keyword(keyword_map, "housing-food", "meal swipe")
        _add_keyword(keyword_map, "emergency", "emergency grant")
        _add_keyword(keyword_map, "emergency", "hardship fund")
        _add_keyword(keyword_map, "financial-aid", "pell grant")
        _add_keyword(keyword_map, "financial-aid", "sai 0")
        _add_keyword(keyword_map, "financial-aid", "low income")

    if signals.get("has_laptop") is False:
        _add_keyword(keyword_map, "loan", "laptop loan")
        _add_keyword(keyword_map, "loan", "technology loan")
        _add_keyword(keyword_map, "loan", "library computer")
        _add_keyword(keyword_map, "emergency", "technology emergency loan")

    if signals.get("reliable_internet") is False:
        _add_keyword(keyword_map, "loan", "hotspot")
        _add_keyword(keyword_map, "loan", "hotspot loan")
        _add_keyword(keyword_map, "loan", "technology loan")
        _add_keyword(keyword_map, "emergency", "technology emergency loan")

    if signals.get("on_campus") is True:
        _add_keyword(keyword_map, "housing-food", "residence life")
        _add_keyword(keyword_map, "housing-food", "campus housing")
        _add_keyword(keyword_map, "housing-food", "meal plan")

    if signals.get("has_meal_plan") is False:
        _add_keyword(keyword_map, "housing-food", "meal swipe")
        _add_keyword(keyword_map, "housing-food", "food pantry")

    if signals.get("veteran") is True:
        _add_keyword(keyword_map, "veteran", "veteran services")
        _add_keyword(keyword_map, "veteran", "gi bill")
        _add_keyword(keyword_map, "veteran", "military benefits")

    if signals.get("first_generation") is True:
        _add_keyword(keyword_map, "scholarship", "first generation scholarship")
        _add_keyword(keyword_map, "grant", "first generation grant")

    if signals.get("full_time") is True:
        _add_keyword(keyword_map, "scholarship", "full-time scholarship")

    if signals.get("gpa") is not None and signals.get("gpa") >= 3.5:
        _add_keyword(keyword_map, "scholarship", "merit scholarship")

    if any(term in major_blob for term in ["computer science", "computing", "cybersecurity", "information technology"]):
        _add_keyword(keyword_map, "scholarship", "computer science")
        _add_keyword(keyword_map, "scholarship", "computing")
        _add_keyword(keyword_map, "scholarship", "women in computing")
        _add_keyword(keyword_map, "scholarship", "technology scholarship")

    if any(term in major_blob for term in ["biology", "pre-med", "pre med", "pre-health", "pre health", "biomedical sciences", "chemistry"]):
        _add_keyword(keyword_map, "health", "biology")
        _add_keyword(keyword_map, "health", "pre-med")
        _add_keyword(keyword_map, "health", "pre-health")
        _add_keyword(keyword_map, "health", "mcat")
        _add_keyword(keyword_map, "health", "shadowing")

    if "study abroad" in positive_terms:
        _add_keyword(keyword_map, "grant", "study abroad")
        _add_keyword(keyword_map, "grant", "study abroad grant")
        _add_keyword(keyword_map, "grant", "travel grant")

    if "research conference" in positive_terms:
        _add_keyword(keyword_map, "grant", "research conference")
        _add_keyword(keyword_map, "grant", "conference travel")
        _add_keyword(keyword_map, "grant", "travel grant")

    if "residence life" in positive_terms:
        _add_keyword(keyword_map, "housing-food", "residence life")

    return _cap_keyword_map(keyword_map, max_per_category=max_per_category)


def build_profile_keyword_map(answers, model, llm_options=None, max_per_category=8):
    profile_signals = build_profile_signals(answers)
    deterministic = build_deterministic_profile_keyword_map(
        profile_signals,
        max_per_category=max_per_category,
    )
    deterministic_count = sum(len(v) for v in deterministic.values())
    print(f"  Generated {deterministic_count} deterministic profile keyword(s).")

    safe_signals = {
        key: value
        for key, value in (profile_signals or {}).items()
        if value not in (None, "", [], {})
    }
    if safe_signals:
        print("  Deterministic profile signals:")
        for key in sorted(safe_signals):
            print(f"    {key}: {safe_signals[key]}")
    else:
        print("  Deterministic profile signals: none")

    profile_text = _profile_from_answers(answers)
    if not profile_text:
        return deterministic

    ok, err = ollama_client.check_ollama(model)
    if not ok:
        print(f"  Profile keyword expansion skipped: {err}")
        return deterministic

    user_prompt = f"""
ALLOWED CATEGORIES
{", ".join(ALLOWED_CATEGORIES)}

STUDENT PROFILE
{profile_text}

TASK
Suggest category-keyword additions that could improve benefit-page filtering for this student.
Return only JSON.
""".strip()

    try:
        response = ollama_client.generate(
            user_prompt,
            system=SYSTEM_PROMPT,
            model=model,
            options=llm_options,
        )
    except Exception as exc:
        print(f"  Profile keyword expansion skipped: {exc}")
        return deterministic

    raw = _extract_json_object(response)
    llm_keyword_map = {}
    for category, values in raw.items():
        cat = _normalize_category(category)
        if not cat:
            continue

        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            continue

        seen = []
        for keyword in values:
            clean = _normalize_keyword(keyword)
            if clean and clean not in seen:
                seen.append(clean)
            if len(seen) >= max_per_category:
                break

        if seen:
            llm_keyword_map[cat] = set(seen)

    llm_count = sum(len(v) for v in llm_keyword_map.values())
    if llm_count:
        print(f"  Generated {llm_count} LLM profile keyword(s).")

    return _merge_keyword_maps(
        deterministic,
        llm_keyword_map,
        max_per_category=max_per_category,
    )
