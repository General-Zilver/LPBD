# rules.py -- General benefit heuristics injected into the phi3 prompt
# to help the LLM reason about things it can't reliably extract from
# scraped text alone. These are NOT institution-specific -- they apply
# across any .edu, .gov, or custom source.
#
# To add a new rule: append a dict to the RULES list at the bottom.
# Each dict needs:
#   "name"  — short identifier (for logging / debugging)
#   "hint"  — the context string injected into the prompt
#   "check" — function(answers) → bool, returns True if rule applies
#
# If check is None the rule always applies (universal hint).


# Helper to pull an answer value out of the answers dict.
# answers format: {question_text: {section_name: answer_value}}
def _get(answers, question):
    entry = answers.get(question)
    if not entry:
        return ""
    for _section, value in entry.items():
        return str(value).strip()
    return ""


def _is_yes(value):
    return value.lower() in ("yes", "y", "1", "true")


def _is_no(value):
    return value.lower() in ("no", "n", "0", "false", "")


# --- rule check functions ------------------------------------------------
# Each takes the answers dict and returns True if the rule is relevant.

def _is_student(answers):
    return _is_yes(_get(answers, "Are you a student?"))


def _no_health_insurance(answers):
    return _is_student(answers) and _is_no(_get(answers, "Do you currently have health insurance?"))


def _no_fafsa(answers):
    return _is_student(answers) and _is_no(_get(answers, "Have you applied for financial aid?"))


def _has_fafsa(answers):
    return _is_student(answers) and _is_yes(_get(answers, "Have you applied for financial aid?"))


def _employed_student(answers):
    status = _get(answers, "What is your current employment status?").lower()
    return _is_student(answers) and status and status not in ("unemployed", "none", "n/a", "")


# --- rules ----------------------------------------------------------------
# Add new rules by appending a dict. That's it.

RULES = [
    {
        "name": "health_auto_enroll",
        "hint": (
            "Educational institutions often auto-enroll students in a student "
            "health insurance plan. If the page mentions a student health plan "
            "or insurance waiver, flag it -- the student may already be enrolled "
            "or may need to opt out."
        ),
        "check": _no_health_insurance,
    },
    {
        "name": "fafsa_prerequisite",
        "hint": (
            "FAFSA (Free Application for Federal Student Aid) is typically a "
            "prerequisite for most need-based financial aid including grants, "
            "work-study, and subsidized loans. If the page describes need-based "
            "aid, note that the student has not yet filed a FAFSA and should "
            "do so first."
        ),
        "check": _no_fafsa,
    },
    {
        "name": "classification_scholarships",
        "hint": (
            "Scholarships are often restricted by academic classification "
            "(freshman, sophomore, junior, senior, graduate). When a scholarship "
            "mentions classification requirements, include that detail so the "
            "student can check if they qualify."
        ),
        "check": _is_student,
    },
    {
        "name": "work_study_interaction",
        "hint": (
            "Federal work-study eligibility can affect which other financial "
            "benefits a student qualifies for. If the page mentions work-study, "
            "note whether it interacts with or replaces other aid the student "
            "may be receiving."
        ),
        "check": _has_fafsa,
    },
    {
        "name": "gov_benefits_interconnected",
        "hint": (
            "Government benefits like SNAP, Medicaid, CHIP, and Pell Grants "
            "often have interconnected eligibility -- qualifying for one may "
            "automatically qualify the applicant for others, or income limits "
            "for one program may affect another. Flag any cross-program "
            "eligibility connections mentioned on the page."
        ),
        "check": None,
    },
    {
        "name": "dependents_extra_aid",
        "hint": (
            "Students with dependents (children, elderly parents, disabled "
            "family members) often qualify for additional aid categories "
            "including childcare grants, increased loan limits, and housing "
            "assistance. If the page mentions dependent-related benefits, "
            "include them even if the student's profile doesn't explicitly "
            "mention dependents."
        ),
        "check": None,
    },
    {
        "name": "deadline_awareness",
        "hint": (
            "Many benefits have application deadlines tied to academic calendar "
            "cycles (fall/spring enrollment, priority filing dates, annual "
            "renewal windows). If the page mentions specific deadlines or "
            "time-sensitive application windows, always include them in the "
            "action details."
        ),
        "check": None,
    },
    {
        "name": "employed_student_benefits",
        "hint": (
            "Students who are employed may be eligible for employer-sponsored "
            "benefits, tuition reimbursement programs, or tax credits like the "
            "Lifetime Learning Credit. They may also need to consider how "
            "earned income affects need-based aid eligibility."
        ),
        "check": _employed_student,
    },
]


# Runs all rules against the user's answers and returns the list of
# hint strings that apply. These get injected into the LLM prompt.
def collect_hints(answers):
    hints = []
    for rule in RULES:
        check = rule.get("check")
        if check is None or check(answers):
            hints.append(rule["hint"])
    return hints


# Convenience: returns the hints as a single block of text ready for
# the system prompt, or empty string if none apply.
def format_hints_for_prompt(answers):
    hints = collect_hints(answers)
    if not hints:
        return ""
    numbered = [f"{i}. {h}" for i, h in enumerate(hints, 1)]
    return "## Benefit Heuristics\n" + "\n".join(numbered)
