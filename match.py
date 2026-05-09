# match.py — Runs the matching pipeline on scraped pages to find benefits
# that match the user's profile. Thin wrapper around matching/controller.py,
# same pattern as map.py wrapping mapper and scrape_all.py wrapping the worker.
# Usage: python match.py --user john_doe
#        python match.py --user john_doe --model phi3:mini --delay 3
#        python match.py --user john_doe --url https://example.edu/scholarships

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import ollama_client
from matching.controller import run_matching_pipeline, run_single_page
from viewer.parsers import slim_benefits
from viewer.templates import BENEFITS_HTML


# Duplicates writes to both a terminal stream and a log file.
class _Tee:
    def __init__(self, original, log_file):
        self.original = original
        self.log_file = log_file

    def write(self, data):
        self.original.write(data)
        self.log_file.write(data)

    def flush(self):
        self.original.flush()
        self.log_file.flush()


def _render_benefits_html(results, out_path):
    envelope = {
        "pipeline_status": "complete",
        "results": [r.to_dict() for r in results],
        "result_count": len(results),
    }
    payload = json.dumps(slim_benefits(envelope), ensure_ascii=False).replace("</", "<\\/")
    out_path.write_text(BENEFITS_HTML.replace("__DATA__", payload), encoding="utf-8")
    return out_path


def _build_report_from_json(json_path, out_path):
    envelope = json.loads(json_path.read_text(encoding="utf-8"))
    payload = json.dumps(slim_benefits(envelope), ensure_ascii=False).replace("</", "<\\/")
    out_path.write_text(BENEFITS_HTML.replace("__DATA__", payload), encoding="utf-8")
    return out_path


def main():
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = open(log_dir / "match.log", "w", encoding="utf-8")
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    sys.stdout = _Tee(original_stdout, log_file)
    sys.stderr = _Tee(original_stderr, log_file)

    try:
        _main_inner()
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        log_file.close()


def _main_inner():
    parser = argparse.ArgumentParser(description="Match benefits using the local pipeline.")
    parser.add_argument("--user", required=True, help="Username from answers.json")
    parser.add_argument("--model", default="phi3:mini", help="Ollama model name")
    parser.add_argument("--delay", type=int, default=5,
                        help="Seconds between Ollama calls (default: 5)")
    parser.add_argument(
        "--verify-pass2",
        dest="verify_pass2",
        action="store_true",
        help="Enable a second strict LLM verification pass before deterministic validation (default: on)",
    )
    parser.add_argument(
        "--no-verify-pass2",
        dest="verify_pass2",
        action="store_false",
        help="Disable the second strict LLM verification pass",
    )
    parser.add_argument(
        "--low-priority",
        action="store_true",
        help="Run matcher process at lower OS priority (best effort)",
    )
    parser.add_argument(
        "--num-threads",
        type=int,
        default=None,
        help="Cap Ollama generation threads (maps to options.num_thread)",
    )
    parser.add_argument(
        "--profile-keywords",
        dest="profile_keywords",
        action="store_true",
        help="Use profile-derived LLM keyword suggestions in addition to base keywords (default: on)",
    )
    parser.add_argument(
        "--no-profile-keywords",
        dest="profile_keywords",
        action="store_false",
        help="Disable profile-derived keyword suggestions and use only base keywords",
    )
    parser.set_defaults(verify_pass2=True, profile_keywords=True)
    parser.add_argument("--scraped-dir", type=Path, default=PROJECT_ROOT / "scraped_output",
                        help="Directory with scraped output files")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "matched_benefits.json",
                        help="Output path for matched benefits")
    parser.add_argument("--html-output", type=Path, default=None,
                        help="Output path for the generated HTML report")
    parser.add_argument("--url", type=str, default=None,
                        help="Single URL to fetch, scrape, and run through the matching pipeline")
    args = parser.parse_args()
    resolved_model = args.model or ollama_client.DEFAULT_MODEL

    print("=== LPBD Benefit Matcher ===\n")

    # Single-page mode: fetch/scrape one URL, then run the normal matcher pipeline.
    if args.url:
        print(f"Real-time matching: {args.url}\n")
        results = run_single_page(
            args.user,
            args.url,
            model=args.model,
            delay=args.delay,
            output=args.output,
            verify_pass2=args.verify_pass2,
            low_priority=args.low_priority,
            num_threads=args.num_threads,
            profile_keywords=args.profile_keywords,
        )

        print(f"\n=== Real-time Matching Complete ===")
        print(f"Benefits found: {len(results)}")
        if results:
            for r in results:
                print(f"  - [{r.relevance_score}/5] {r.action}: {r.summary[:80]}")
        html_path = args.html_output or PROJECT_ROOT / "single_run.html"
        report = _render_benefits_html(results, html_path)
        print(f"HTML report: {report}")
        print(f"Log: {PROJECT_ROOT / 'logs' / 'match.log'}")
        return

    # Full pipeline mode
    print(f"User: {args.user}")
    if args.model:
        print(f"Model: {resolved_model}")
    else:
        print(f"Model: {resolved_model} (default)")
    print(f"Delay: {args.delay}s")
    print(f"Pass2 verify: {'on' if args.verify_pass2 else 'off'}")
    print(f"Low priority: {'on' if args.low_priority else 'off'}")
    if args.num_threads:
        print(f"Ollama threads: {args.num_threads}")
    else:
        print("Ollama threads: default")
    print(f"Profile keywords: {'on' if args.profile_keywords else 'off'}")
    print(f"Scraped dir: {args.scraped_dir}")
    print(f"Output: {args.output}\n")

    envelope = run_matching_pipeline(
        user=args.user,
        model=args.model,
        delay=args.delay,
        scraped_dir=args.scraped_dir,
        output=args.output,
        verify_pass2=args.verify_pass2,
        low_priority=args.low_priority,
        num_threads=args.num_threads,
        profile_keywords=args.profile_keywords,
    )

    if envelope.results:
        print("\nTop matches:")
        for r in sorted(envelope.results,
                        key=lambda x: x.relevance_score, reverse=True)[:10]:
            print(f"  [{r.relevance_score}/5] {r.action}: {r.summary[:80]}")

    html_path = args.html_output or PROJECT_ROOT / "benefits.html"
    report = _build_report_from_json(args.output, html_path)
    print(f"\nHTML report: {report}")
    print(f"Log: {PROJECT_ROOT / 'logs' / 'match.log'}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)
    except Exception as exc:
        print(f"\nError: {exc}")
        sys.exit(1)
