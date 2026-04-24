# profile_signals.py -- Deterministic extraction of normalized profile facts
# from questionnaire answers. Output is safe for matching logic and keyword
# generation, without private identifiers.

import re


def get_answer(answers, question_fragment):
    fragment = str(question_fragment or "").strip().lower()
    if not fragment:
        return ""

    for question, section_dict in (answers or {}).items():
        question_text = str(question or "").lower()
        if fragment not in question_text:
            continue

        if isinstance(section_dict, dict):
            for _section, value in section_dict.items():
                text = str(value or "").strip()
                if text:
                    return text
        else:
            text = str(section_dict or "").strip()
            if text:
                return text
    return ""


def parse_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False

    text = str(value or "").strip().lower()
    if not text:
        return False
    if text in ("none", "n/a", "na", "null", ""):
        return False
    if re.match(r"^(yes|y|true|1)\b", text):
        return True
    if re.match(r"^(no|n|false|0)\b", text):
        return False
    return None


def parse_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return None

    m = re.search(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?", text)
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _collect_answer_values(answers):
    values = []
    for _question, section_dict in (answers or {}).items():
        if isinstance(section_dict, dict):
            for _section, value in section_dict.items():
                text = str(value or "").strip()
                if text:
                    values.append(text)
        else:
            text = str(section_dict or "").strip()
            if text:
                values.append(text)
    return values


def _split_major_terms(value):
    text = str(value or "").strip().lower()
    if not text:
        return []

    text = text.replace("&", "/")
    text = re.sub(r"\band\b", "/", text)
    parts = re.split(r"[/,;|]+", text)

    terms = []
    for part in parts:
        clean = " ".join(part.split())
        if not clean:
            continue
        if clean not in terms:
            terms.append(clean)
    return terms


def _parse_yes_no_fact(answers, fragment):
    raw = get_answer(answers, fragment)
    if not raw:
        return None
    return parse_bool(raw)


def _parse_full_time(answers):
    raw = get_answer(answers, "full-time or part-time")
    if not raw:
        raw = get_answer(answers, "full-time")
    if not raw:
        return None
    lower = raw.lower()
    if "full" in lower:
        return True
    if "part" in lower:
        return False
    return parse_bool(raw)


def _parse_on_campus(answers):
    raw = get_answer(answers, "live on campus")
    if not raw:
        return None
    lower = raw.lower()
    if "on campus" in lower:
        return True
    if "off campus" in lower or "with family" in lower or "commute" in lower:
        return False
    return parse_bool(raw)


def _parse_has_laptop(answers):
    raw = get_answer(answers, "personal laptop or computer")
    if not raw:
        return None
    lower = raw.lower()
    if any(token in lower for token in [
        "broken",
        "broke",
        "no laptop",
        "no computer",
        "without",
        "library computer",
        "using library",
    ]):
        return False
    bool_value = parse_bool(raw)
    if bool_value is not None:
        return bool_value
    if any(token in lower for token in ["yes", "have", "macbook", "laptop", "computer"]):
        return True
    return None


def _parse_reliable_internet(answers):
    raw = get_answer(answers, "reliable internet access")
    if not raw:
        return None
    lower = raw.lower()
    if any(token in lower for token in ["no", "unreliable", "hotspot", "cellular"]):
        if "no" in lower or "unreliable" in lower or "hotspot" in lower:
            return False
    bool_value = parse_bool(raw)
    if bool_value is not None:
        return bool_value
    if any(token in lower for token in ["yes", "reliable", "fast"]):
        return True
    return None


def _parse_out_of_state(answers):
    raw = get_answer(answers, "residency status")
    if not raw:
        return None
    lower = raw.lower()
    if "out-of-state" in lower or "out of state" in lower or "nonresident" in lower:
        return True
    if "in-state" in lower or "in state" in lower:
        return False
    return parse_bool(raw)


def _parse_low_income(answers):
    income_raw = get_answer(answers, "estimated household income range")
    pell_raw = get_answer(answers, "pell grant eligible")
    sai_raw = get_answer(answers, "student aid index")

    low_income = None
    if income_raw:
        lower = income_raw.lower()
        if "under $20k" in lower or "$20k-$40k" in lower:
            low_income = True
        elif "$80k+" in lower or "$60k-$80k" in lower:
            low_income = False

    pell = parse_bool(pell_raw) if pell_raw else None
    if pell is True:
        low_income = True

    sai = parse_float(sai_raw)
    if sai is not None:
        if sai <= 0:
            low_income = True
        elif sai >= 40000 and low_income is None:
            low_income = False

    return low_income, sai, pell


def build_profile_signals(answers):
    values = _collect_answer_values(answers)
    values_lower = " | ".join(v.lower() for v in values)

    institution = get_answer(answers, "institution name")
    classification = get_answer(answers, "year/classification")
    if not classification:
        classification = get_answer(answers, "classification")
    classification = " ".join(classification.lower().split()) if classification else ""

    major_raw = get_answer(answers, "major or intended major")
    major_terms = _split_major_terms(major_raw)
    major_blob = " | ".join(major_terms)

    gpa = parse_float(get_answer(answers, "current gpa"))
    student_raw = get_answer(answers, "are you a student")
    if not student_raw:
        student_raw = get_answer(answers, "enrolled in an accredited institution")
    student = parse_bool(student_raw) if student_raw else None

    has_fafsa_raw = get_answer(answers, "completed the fafsa")
    if not has_fafsa_raw:
        has_fafsa_raw = get_answer(answers, "applied for financial aid")
    has_fafsa = parse_bool(has_fafsa_raw) if has_fafsa_raw else None

    insured = _parse_yes_no_fact(answers, "currently have health insurance")
    veteran = _parse_yes_no_fact(answers, "veteran or active-duty military")
    if veteran is None:
        veteran = _parse_yes_no_fact(answers, "veteran or active-duty")
    has_dependents = _parse_yes_no_fact(answers, "do you have dependents")
    food_insecurity = _parse_yes_no_fact(answers, "food insecurity")
    has_laptop = _parse_has_laptop(answers)
    reliable_internet = _parse_reliable_internet(answers)
    on_campus = _parse_on_campus(answers)
    has_meal_plan = _parse_yes_no_fact(answers, "currently have a meal plan")
    first_generation = _parse_yes_no_fact(answers, "first-generation college student")
    out_of_state = _parse_out_of_state(answers)
    full_time = _parse_full_time(answers)

    honors = None
    if "honors college" in values_lower or "honors program" in values_lower or "honors classes" in values_lower:
        honors = True
    elif "not in honors" in values_lower:
        honors = False

    national_merit = None
    if "national merit" in values_lower:
        national_merit = True

    low_income, sai_value, pell_value = _parse_low_income(answers)

    positive_terms = set()
    negative_terms = set()

    if any(term in major_blob for term in ["computer science", "computing", "cybersecurity", "information technology"]):
        positive_terms.update([
            "computer science",
            "computing",
            "women in computing",
            "technology scholarship",
        ])
    if any(term in major_blob for term in ["biology", "pre-med", "pre med", "pre-health", "pre health", "biomedical sciences", "chemistry"]):
        positive_terms.update([
            "biology",
            "pre-med",
            "pre-health",
            "mcat",
            "shadowing",
        ])
    if honors is True:
        positive_terms.update([
            "honors",
            "honors college",
            "honors program",
            "honors scholarship",
        ])
    if national_merit is True:
        positive_terms.update([
            "national merit",
            "national merit scholarship",
            "nonresident tuition",
        ])
    if out_of_state is True:
        positive_terms.update([
            "out-of-state",
            "nonresident tuition",
            "tuition waiver",
        ])
    if has_dependents is True:
        positive_terms.update([
            "student parent",
            "dependent child",
            "childcare",
        ])
    if food_insecurity is True or low_income is True:
        positive_terms.update([
            "food pantry",
            "basic needs",
            "emergency grant",
        ])
    if low_income is True:
        positive_terms.add("low income")
    if pell_value is True:
        positive_terms.add("pell grant")
    if sai_value is not None and sai_value <= 0:
        positive_terms.add("sai 0")
    if has_laptop is False:
        positive_terms.update([
            "broken laptop",
            "technology loan",
            "library computer",
        ])
    if reliable_internet is False:
        positive_terms.update([
            "hotspot",
            "unreliable internet",
        ])
    if veteran is True:
        positive_terms.update([
            "veteran",
            "veteran services",
            "gi bill",
            "military benefits",
        ])
    if on_campus is True:
        positive_terms.update([
            "residence life",
            "housing",
            "meal plan",
        ])
    if first_generation is True:
        positive_terms.add("first generation")
    if "study abroad" in values_lower:
        positive_terms.add("study abroad")
    if "research conference" in values_lower or ("research" in values_lower and "conference" in values_lower):
        positive_terms.add("research conference")

    if veteran is False:
        negative_terms.add("not veteran")
    if has_dependents is False:
        negative_terms.add("no dependents")
    if insured is False:
        negative_terms.add("not insured")
    if on_campus is False:
        negative_terms.add("off campus")

    signals = {
        "student": student,
        "institution": institution,
        "classification": classification,
        "full_time": full_time,
        "major_terms": sorted(set(major_terms)),
        "gpa": gpa,
        "has_fafsa": has_fafsa,
        "insured": insured,
        "veteran": veteran,
        "has_dependents": has_dependents,
        "food_insecurity": food_insecurity,
        "has_laptop": has_laptop,
        "reliable_internet": reliable_internet,
        "on_campus": on_campus,
        "has_meal_plan": has_meal_plan,
        "honors": honors,
        "national_merit": national_merit,
        "out_of_state": out_of_state,
        "first_generation": first_generation,
        "low_income": low_income,
        "positive_terms": sorted(positive_terms),
        "negative_terms": sorted(negative_terms),
    }
    return signals
