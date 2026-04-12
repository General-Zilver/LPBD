# profile_keywords.py -- Optional profile-derived keyword expansion for the
# keyword pre-filter stage. Uses the student's questionnaire answers to infer
# extra benefit terms that may not exist in the base static dictionary.

import json

import ollama_client


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


def build_profile_keyword_map(answers, model, llm_options=None, max_per_category=8):
    profile_text = _profile_from_answers(answers)
    if not profile_text:
        return {}

    ok, err = ollama_client.check_ollama(model)
    if not ok:
        print(f"  Profile keyword expansion skipped: {err}")
        return {}

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
        return {}

    raw = _extract_json_object(response)
    normalized = {}
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
            normalized[cat] = set(seen)

    return normalized
