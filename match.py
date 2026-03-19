# match.py -- Reads the user's questionnaire answers and scraped page content,
# sends each page to Ollama for benefit matching, and writes the results to
# matched_benefits.json.
# Usage: python match.py --user john_doe
#        python match.py --user john_doe --model phi3:mini

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import ollama_client

PROJECT_ROOT = Path(__file__).resolve().parent


# Loads answers for a specific user from answers.json.
# Returns the nested {section: {question: answer}} dict or None.
def load_user_answers(username):
    candidates = [
        PROJECT_ROOT / "answers.json",
        PROJECT_ROOT / "GUI" / "answers.json",
    ]
    for path in candidates:
        if path.exists():
            data = json.loads(path.read_text())
            if username in data:
                return data[username]
    return None


# Turns the nested answers dict into a readable profile string for the prompt.
# Strips verbose question prefixes down to shorter labels.
def format_profile(answers):
    simplify = {
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
    for section, questions in answers.items():
        for question, answer in questions.items():
            label = simplify.get(question, question)
            lines.append(f"- {label}: {answer}")
    return "\n".join(lines)


# Parses a scraped output file and yields (url, title, text) for each page.
def load_scraped_pages(output_dir):
    for filepath in sorted(output_dir.glob("scraped_*.txt")):
        content = filepath.read_text(encoding="utf-8")

        # Split on the page delimiter
        pages = re.split(r"\n--- (https?://\S+) ---\n", content)

        # First chunk is the file header, skip it. Then pairs of (url, body).
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
                yield url, title, text


# Splits text into chunks that fit the LLM context window.
def chunk_text(text, max_words=2000):
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


MATCH_SYSTEM = """You are a student benefit matcher. You analyze web page content and identify benefits a specific student might qualify for.

For each benefit you find, return a JSON object with:
- "benefit_name": short name of the benefit
- "source_url": the URL this was found on
- "benefit_type": one of "scholarship", "grant", "loan", "health", "insurance", "employment", "other"
- "summary": 1-2 sentence description
- "relevance": why this matches the student's profile
- "eligibility_snippet": the exact text describing eligibility

Return a JSON array of benefits. If no relevant benefits are found, return [].
Only include benefits the student is likely eligible for based on their profile."""


# Builds the user prompt for one page chunk.
def build_prompt(profile_summary, url, title, text_chunk):
    return f"""## Student Profile
{profile_summary}

## Web Page Content (from {url})
Title: {title}
{text_chunk}

Identify all student benefits this person may qualify for."""


# Tries to extract a JSON array from the LLM response, which might have
# markdown code fences or commentary around it.
def parse_benefits(response_text):
    start = response_text.find("[")
    end = response_text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        return json.loads(response_text[start:end + 1])
    except json.JSONDecodeError:
        return []


def main():
    parser = argparse.ArgumentParser(description="Match student benefits using Ollama.")
    parser.add_argument("--user", required=True, help="Username from answers.json")
    parser.add_argument("--model", default="phi3:mini", help="Ollama model name")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "matched_benefits.json",
                        help="Output path for matched benefits")
    parser.add_argument("--scraped-dir", type=Path, default=PROJECT_ROOT / "scraped_output",
                        help="Directory with scraped output files")
    args = parser.parse_args()

    print("=== LPBD Benefit Matcher ===\n")

    ok, err = ollama_client.check_ollama(args.model)
    if not ok:
        print(f"Error: {err}")
        sys.exit(1)
    print(f"Ollama ready (model: {args.model})\n")

    answers = load_user_answers(args.user)
    if not answers:
        print(f"Error: No answers found for user '{args.user}'.")
        print("Complete the questionnaire in the GUI first.")
        sys.exit(1)

    profile_summary = format_profile(answers)
    print(f"Loaded profile for '{args.user}':")
    for line in profile_summary.splitlines():
        print(f"  {line}")
    print()

    if not args.scraped_dir.exists():
        print(f"Error: {args.scraped_dir} not found.")
        print("Run `python scrape_all.py` first.")
        sys.exit(1)

    pages = list(load_scraped_pages(args.scraped_dir))
    if not pages:
        print("No scraped pages found. Run `python scrape_all.py` first.")
        sys.exit(1)

    print(f"Found {len(pages)} scraped page(s).\n")

    all_benefits = []
    for i, (url, title, text) in enumerate(pages, 1):
        chunks = chunk_text(text)
        chunk_label = f" ({len(chunks)} chunks)" if len(chunks) > 1 else ""
        print(f"[{i}/{len(pages)}] Matching {url}{chunk_label}...")

        for chunk in chunks:
            prompt = build_prompt(profile_summary, url, title, chunk)
            try:
                response = ollama_client.generate(prompt, system=MATCH_SYSTEM, model=args.model)
                benefits = parse_benefits(response)

                # Tag each benefit with the source URL in case the model forgot
                for b in benefits:
                    b.setdefault("source_url", url)
                    all_benefits.extend([b])

                if benefits:
                    print(f"  Found {len(benefits)} benefit(s)")
                else:
                    print(f"  No matches")
            except Exception as exc:
                print(f"  Error: {exc}")

    # Deduplicate by (name, url)
    seen = set()
    unique = []
    for b in all_benefits:
        key = (b.get("benefit_name", "").lower(), b.get("source_url", ""))
        if key not in seen:
            seen.add(key)
            unique.append(b)

    output = {
        "user": args.user,
        "matched_at": datetime.now().isoformat(),
        "model": args.model,
        "total_pages_analyzed": len(pages),
        "total_benefits_found": len(unique),
        "benefits": unique,
    }

    args.output.write_text(json.dumps(output, indent=2), encoding="utf-8")

    print(f"\n=== Matching Complete ===")
    print(f"Pages analyzed: {len(pages)}")
    print(f"Benefits found: {len(unique)}")
    print(f"Output: {args.output}")

    if unique:
        print("\nMatched benefits:")
        for b in unique:
            print(f"  - {b.get('benefit_name', 'Unknown')} ({b.get('benefit_type', '?')})")
            print(f"    {b.get('summary', '')}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)
    except Exception as exc:
        print(f"\nError: {exc}")
        sys.exit(1)
