# match.py — Runs the matching pipeline on scraped pages to find benefits
# that match the user's profile. Thin wrapper around matching/controller.py,
# same pattern as map.py wrapping mapper and scrape_all.py wrapping the worker.
# Usage: python match.py --user john_doe
#        python match.py --user john_doe --model phi3:mini --delay 3
#        python match.py --user john_doe --url https://example.edu/scholarships

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import ollama_client
from matching.controller import run_matching_pipeline, run_single_page


def main():
    parser = argparse.ArgumentParser(description="Match benefits using the local pipeline.")
    parser.add_argument("--user", required=True, help="Username from answers.json")
    parser.add_argument("--model", default="phi3:mini", help="Ollama model name")
    parser.add_argument("--delay", type=int, default=5,
                        help="Seconds between Ollama calls (default: 5)")
    parser.add_argument("--scraped-dir", type=Path, default=PROJECT_ROOT / "scraped_output",
                        help="Directory with scraped output files")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "matched_benefits.json",
                        help="Output path for matched benefits")
    parser.add_argument("--url", type=str, default=None,
                        help="Single URL for real-time matching (skips pipeline)")
    args = parser.parse_args()
    resolved_model = args.model or ollama_client.DEFAULT_MODEL

    print("=== LPBD Benefit Matcher ===\n")

    # Single-page real-time mode
    if args.url:
        print(f"Real-time matching: {args.url}\n")
        results = run_single_page(args.user, args.url, model=args.model)

        print(f"\n=== Real-time Matching Complete ===")
        print(f"Benefits found: {len(results)}")
        if results:
            for r in results:
                print(f"  - [{r.relevance_score}/5] {r.action}: {r.summary[:80]}")
        return

    # Full pipeline mode
    print(f"User: {args.user}")
    if args.model:
        print(f"Model: {resolved_model}")
    else:
        print(f"Model: {resolved_model} (default)")
    print(f"Delay: {args.delay}s")
    print(f"Scraped dir: {args.scraped_dir}")
    print(f"Output: {args.output}\n")

    envelope = run_matching_pipeline(
        user=args.user,
        model=args.model,
        delay=args.delay,
        scraped_dir=args.scraped_dir,
        output=args.output,
    )

    if envelope.results:
        print("\nTop matches:")
        for r in sorted(envelope.results,
                        key=lambda x: x.relevance_score, reverse=True)[:10]:
            print(f"  [{r.relevance_score}/5] {r.action}: {r.summary[:80]}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)
    except Exception as exc:
        print(f"\nError: {exc}")
        sys.exit(1)
