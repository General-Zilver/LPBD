"""CLI to build LPBD HTML reports from pipeline outputs."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from viewer.parsers import parse_map_log, parse_scrape_log, slim_benefits
from viewer.templates import MAP_HTML, SCRAPE_HTML, BENEFITS_HTML


def _render(template: str, data: object) -> str:
    # Serialize data and safely embed inside a <script> tag
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return template.replace("__DATA__", payload)


def build_map_report(log_path: Path, out_path: Path) -> Path:
    lines = log_path.read_text(encoding="utf-8").splitlines()
    data = parse_map_log(lines)
    html = _render(MAP_HTML, data)
    out_path.write_text(html, encoding="utf-8")
    return out_path


def build_scrape_report(log_path: Path, out_path: Path) -> Path:
    lines = log_path.read_text(encoding="utf-8").splitlines()
    data = parse_scrape_log(lines)
    html = _render(SCRAPE_HTML, data)
    out_path.write_text(html, encoding="utf-8")
    return out_path


def build_benefits_report(json_path: Path, out_path: Path) -> Path:
    envelope = json.loads(json_path.read_text(encoding="utf-8"))
    data = slim_benefits(envelope)
    html = _render(BENEFITS_HTML, data)
    out_path.write_text(html, encoding="utf-8")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build LPBD HTML reports")
    parser.add_argument(
        "stage",
        choices=["map", "scrape", "match", "all"],
        help="Which report to build",
    )
    parser.add_argument("--log", type=Path, default=None, help="Path to log file")
    parser.add_argument("--json", type=Path, default=None, help="Path to matched_benefits.json")
    parser.add_argument("--out", type=Path, default=None, help="Output HTML path")
    args = parser.parse_args()

    root = Path(".")
    stages = [args.stage] if args.stage != "all" else ["map", "scrape", "match"]

    for stage in stages:
        try:
            if stage == "map":
                log_path = args.log or root / "logs" / "map.log"
                out_path = args.out or root / "map_report.html"
                if not log_path.exists():
                    print(f"Warning: {log_path} not found, skipping map report.")
                    continue
                result = build_map_report(log_path, out_path)
                print(f"Built: {result} ({result.stat().st_size:,} bytes)")

            elif stage == "scrape":
                log_path = args.log or root / "logs" / "scrape_all.log"
                out_path = args.out or root / "scrape_report.html"
                if not log_path.exists():
                    print(f"Warning: {log_path} not found, skipping scrape report.")
                    continue
                result = build_scrape_report(log_path, out_path)
                print(f"Built: {result} ({result.stat().st_size:,} bytes)")

            elif stage == "match":
                json_path = args.json or root / "matched_benefits.json"
                out_path = args.out or root / "benefits.html"
                if not json_path.exists():
                    print(f"Warning: {json_path} not found, skipping benefits report.")
                    continue
                result = build_benefits_report(json_path, out_path)
                print(f"Built: {result} ({result.stat().st_size:,} bytes)")

        except Exception as e:
            print(f"Error building {stage} report: {e}", file=sys.stderr)
            if args.stage != "all":
                sys.exit(1)


if __name__ == "__main__":
    main()
