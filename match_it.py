# match_it.py -- Convenience script for testing the matching pipeline.
# Runs against whatever is currently scraped and stored.
# Usage: python match_it.py
#        python match_it.py --user default_user --delay 0 --verbose

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from matching.controller import load_user_answers, DEFAULT_RESULTS, DEFAULT_STATE
from matching.pipeline import run_pipeline, load_results, load_state
from matching.matcher import load_scraped_lookup
import ollama_client


def print_validation_report(stats, verbose):
    llm_proposed = stats["llm_proposed"]
    llm_validated = stats["llm_validated"]
    rejected = stats["rejected"]
    pass2_rejected = stats.get("pass2_rejected", [])
    keyword_detected = stats["keyword_detected"]

    print("\n" + "=" * 60)
    print("  VALIDATION & DETECTION REPORT")
    print("=" * 60)
    print(f"  LLM proposed:             {llm_proposed}")
    print(f"  Passed validation:        {llm_validated}")
    print(f"  Rejected:                 {len(rejected)}")
    if pass2_rejected:
        print(f"    (pass-2 rejected:       {len(pass2_rejected)})")
    print(f"  Keyword-detected:         {len(keyword_detected)}")
    print(f"  Final total:              {llm_validated + len(keyword_detected)}")

    if rejected:
        print(f"\n  --- Rejected matches ({len(rejected)}) ---")
        if verbose:
            for r in rejected:
                reason = getattr(r, "rejection_reason", "unknown")
                name = r.benefit_name or "(no name)"
                print(f"    x {name}")
                print(f"      URL:    {r.page_url}")
                print(f"      Reason: {reason}")
        else:
            reasons = {}
            for r in rejected:
                reason = getattr(r, "rejection_reason", "unknown")
                reasons[reason] = reasons.get(reason, 0) + 1
            for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
                print(f"    {reason}: {count}")
            print("    (use --verbose to see each rejection)")

    if keyword_detected:
        print(f"\n  --- Keyword-detected benefits ({len(keyword_detected)}) ---")
        for km in keyword_detected:
            keyword_hint = ""
            reasoning = km.reasoning
            if "'" in reasoning:
                start = reasoning.index("'") + 1
                end = reasoning.index("'", start)
                keyword_hint = f" (keyword: '{reasoning[start:end]}')"
            print(f"    + {km.benefit_name}{keyword_hint}")
            print(f"      URL: {km.page_url}")

    print()


def print_summary(scraped_count, results_path, state_path, stats, verbose):
    state = load_state(state_path)
    envelope = load_results(results_path)
    results = envelope.results

    print("=" * 60)
    print("  MATCHING PIPELINE SUMMARY")
    print("=" * 60)
    print(f"  Scraped pages on disk:    {scraped_count}")
    print(f"  Passed keyword filter:    {stats.get('pages_relevant', 0)}")
    print(f"  Filtered out:             {stats.get('pages_filtered', 0)}")
    print(f"  Total matches found:      {len(results)}")

    if state:
        print(f"  Pipeline run ID:          {state.run_id}")
        print(f"  Final stage:              {state.current_stage}")

    if not results:
        print("\n  No matches to display.")
        print("=" * 60)
        return

    scores = [r.relevance_score for r in results]
    by_action = {}
    for r in results:
        by_action[r.action] = by_action.get(r.action, 0) + 1

    print("\n  Score distribution:")
    for s in range(5, 0, -1):
        count = scores.count(s)
        bar = "#" * count
        print(f"    {s}/5: {bar} ({count})")

    print("\n  Actions:")
    for action, count in sorted(by_action.items(), key=lambda x: -x[1]):
        print(f"    {action}: {count}")

    llm_count = sum(1 for r in results if r.evidence_type != "keyword-detection")
    kw_count = sum(1 for r in results if r.evidence_type == "keyword-detection")
    print("\n  Source:")
    print(f"    llm:     {llm_count}")
    print(f"    keyword: {kw_count}")

    top = sorted(results, key=lambda r: r.relevance_score, reverse=True)[:10]
    print(f"\n  Top {len(top)} matches:")
    print(f"  {'Score':<6} {'Action':<12} {'Via':<9} {'Source':<8} {'Summary'}")
    print(f"  {'-' * 5:<6} {'-' * 11:<12} {'-' * 8:<9} {'-' * 7:<8} {'-' * 35}")
    for r in top:
        via = "keyword" if r.evidence_type == "keyword-detection" else "llm"
        summary = r.summary[:50] + "..." if len(r.summary) > 50 else r.summary
        print(f"  {r.relevance_score}/5   {r.action:<12} {via:<9} {r.source_type:<8} {summary}")

    if verbose:
        print("\n  --- Full details ---")
        for i, r in enumerate(top, 1):
            via = "keyword" if r.evidence_type == "keyword-detection" else "llm"
            print(f"\n  [{i}] {r.benefit_name or r.page_title or r.page_url} [{via}]")
            print(f"      URL:      {r.page_url}")
            print(f"      Score:    {r.relevance_score}/5")
            print(f"      Action:   {r.action}")
            print(f"      Tags:     {', '.join(r.tags) if r.tags else 'none'}")
            print(f"      Summary:  {r.summary}")
            print(f"      Why:      {r.reasoning}")
            if r.evidence_quote:
                eq = r.evidence_quote[:120] + "..." if len(r.evidence_quote) > 120 else r.evidence_quote
                print(f"      Evidence: {eq}")
            print(f"      Steps:    {r.action_details}")
            if r.cross_references:
                print(f"      Related:  {len(r.cross_references)} cross-reference(s)")
            if r.inferred_from:
                print(f"      From:     {', '.join(r.inferred_from)}")

    print("\n" + "=" * 60)


def _fmt_time(seconds):
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m {secs:.0f}s"


def print_performance(stats):
    timings = stats.get("timings", {})
    wall_time = stats.get("wall_time", 0)
    peak_ram = stats.get("peak_ram_mb", 0)
    model = stats.get("model", "?")
    llm_proposed = stats.get("llm_proposed", 0)
    llm_validated = stats.get("llm_validated", 0)

    print("\n" + "=" * 60)
    print("  PERFORMANCE")
    print("=" * 60)
    print(f"  Model:                    {model}")
    print(f"  Total wall time:          {_fmt_time(wall_time)}")

    if timings:
        print("\n  Time per stage:")
        for stage in ["profile_keywords", "filter", "match", "validate", "detect"]:
            t = timings.get(stage)
            if t is not None:
                print(f"    {stage:<12} {_fmt_time(t)}")

    if peak_ram > 0:
        print(f"\n  Peak RAM:                 {peak_ram:.0f} MB")

    if llm_proposed > 0:
        pct = (llm_validated / llm_proposed) * 100
        print("\n  LLM efficiency:")
        print(f"    Proposed:    {llm_proposed}")
        print(f"    Validated:   {llm_validated}")
        print(f"    Pass rate:   {pct:.0f}%")
    elif llm_proposed == 0:
        print("\n  LLM efficiency:           no proposals this run")

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Test the matching pipeline against current scraped data."
    )
    parser.add_argument(
        "--user",
        default="default_user",
        help="Username from answers.json (default: default_user)",
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=5,
        help="Seconds between Ollama calls (default: 5, use 0 for fast testing)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Ollama model name (default: llama3:8b)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print full details for top results",
    )
    parser.add_argument(
        "--verify-pass2",
        action="store_true",
        help="Enable a second strict LLM verification pass before deterministic validation",
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
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-scrape all pages (bypass change detection) before matching",
    )
    parser.set_defaults(profile_keywords=True)
    args = parser.parse_args()

    scraped_dir = PROJECT_ROOT / "scraped_output"
    resolved_model = args.model or ollama_client.DEFAULT_MODEL

    print("=== LPBD Matching Pipeline Test ===\n")

    # Check prerequisites
    answers = load_user_answers(args.user)
    if not answers:
        available = []
        for path in [PROJECT_ROOT / "answers.json", PROJECT_ROOT / "GUI" / "answers.json"]:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                available.extend(data.keys())
        print(f"Error: No answers found for user '{args.user}'.")
        if available:
            print(f"Available users: {', '.join(available)}")
            print(f"Try: python match_it.py --user {available[0]}")
        else:
            print("No users found. Complete the questionnaire in the GUI first.")
        sys.exit(1)

    # Re-scrape everything fresh when --force is passed
    if args.force:
        print("Force mode: re-scraping all pages before matching...\n")
        import subprocess as _sp
        scrape_cmd = [sys.executable, str(PROJECT_ROOT / "scrape_all.py"), "--force"]
        scrape_result = _sp.run(scrape_cmd, cwd=str(PROJECT_ROOT))
        if scrape_result.returncode != 0:
            print("Warning: scrape_all.py exited with errors, continuing anyway.\n")
        else:
            print()

    if not scraped_dir.exists() or not list(scraped_dir.glob("scraped_*.txt")):
        print(f"Error: No scraped data found in {scraped_dir}")
        print("Run `python scrape_all.py` first.")
        sys.exit(1)

    scraped_lookup = load_scraped_lookup(scraped_dir)
    scraped_count = len(scraped_lookup)

    print(f"User:       {args.user}")
    if args.model:
        print(f"Model:      {resolved_model}")
    else:
        print(f"Model:      {resolved_model} (default)")
    print(f"Delay:      {args.delay}s")
    print(f"Pass2:      {'on' if args.verify_pass2 else 'off'}")
    print(f"Priority:   {'low' if args.low_priority else 'normal'}")
    print(f"Threads:    {args.num_threads if args.num_threads else 'default'}")
    print(f"Profile KW: {'on' if args.profile_keywords else 'off'}")
    print(f"Force:      {'on' if args.force else 'off'}")
    print(f"Pages:      {scraped_count} scraped")
    print()

    # Run the pipeline
    _envelope, stats = run_pipeline(
        user=args.user,
        answers=answers,
        scraped_dir=scraped_dir,
        results_path=DEFAULT_RESULTS,
        state_path=DEFAULT_STATE,
        model=args.model,
        delay=args.delay,
        verbose=args.verbose,
        verify_pass2=args.verify_pass2,
        low_priority=args.low_priority,
        num_threads=args.num_threads,
        use_profile_keywords=args.profile_keywords,
    )

    # Validation report first (what happened during this run)
    print_validation_report(stats, args.verbose)

    # Then the full summary (cumulative results on disk)
    print_summary(scraped_count, DEFAULT_RESULTS, DEFAULT_STATE, stats, args.verbose)

    # Performance section
    print_performance(stats)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)
    except Exception as exc:
        print(f"\nError: {exc}")
        if "--verbose" in sys.argv:
            import traceback

            traceback.print_exc()
        sys.exit(1)
