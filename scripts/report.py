#!/usr/bin/env python3
"""Daily token usage report generator.

Standalone script for cron job usage:
    python3 scripts/report.py                     # yesterday's report
    python3 scripts/report.py 2026-06-17          # specific date
    python3 scripts/report.py --today             # today so far
"""
from __future__ import annotations

import sys
import os

# Add plugin directory to path so we can import __init__ module
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PLUGIN_DIR = os.path.dirname(_SCRIPT_DIR)
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)

# Import the plugin module (__init__.py)
from __init__ import save_report_to_file, generate_report  # type: ignore[import]


def main() -> None:
    args = sys.argv[1:]

    if "--today" in args:
        from datetime import datetime
        date_str = datetime.now().strftime("%Y-%m-%d")
    elif args and not args[0].startswith("--"):
        date_str = args[0]
    else:
        date_str = None  # yesterday

    path = save_report_to_file(date_str)
    print(f"Report saved to: {path}")
    print()

    # Also print a short summary to stdout
    report = generate_report(date_str)
    lines = report.split("\n")
    for line in lines:
        if line.startswith("# Token") or line.startswith("## Daily"):
            print(line)
        if "| Metric" in line or "|------" in line:
            print(line)
        if "| Total" in line or "| Avg" in line or "| API" in line:
            print(line)
        if line.startswith("---"):
            break


if __name__ == "__main__":
    main()
