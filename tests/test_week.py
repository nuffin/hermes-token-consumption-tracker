"""Regression tests for the `week` subcommand (weekly report + charts).

Builds an in-memory DB with a known dataset spanning two weeks and drives
cmd_week() via argparse Namespaces, capturing stdout. Color output is checked
structurally (ANSI escapes present/absent) rather than byte-exact.
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import sqlite3
import sys
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]

# 2026-09-21 is a Monday; the test week is 2026-09-21 .. 2026-09-27.
WEEK_MONDAY = date(2026, 9, 21)
OTHER_WEEK_DAY = date(2026, 9, 15)  # Tuesday of the previous week


def _load_query_module():
    spec = importlib.util.spec_from_file_location(
        "tct_query_test_module", PLUGIN_ROOT / "scripts" / "query.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


Q = _load_query_module()


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE token_usage (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL,
            turn_id     TEXT,
            api_request_id TEXT,
            model       TEXT NOT NULL,
            provider    TEXT NOT NULL,
            prompt_tokens   INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            cache_read_tokens  INTEGER DEFAULT 0,
            cache_write_tokens INTEGER DEFAULT 0,
            workspace       TEXT DEFAULT '',
            worker          TEXT DEFAULT '',
            total_tokens    INTEGER DEFAULT 0,
            api_duration    REAL DEFAULT 0.0,
            finish_reason   TEXT,
            created_at  TEXT NOT NULL
        )
        """
    )
    return conn


def _insert(conn, day: date, model: str, prompt: int, completion: int,
            cache_read: int, total: int, hour: int = 12) -> None:
    conn.execute(
        "INSERT INTO token_usage (session_id, model, provider, prompt_tokens, completion_tokens,"
        " cache_read_tokens, cache_write_tokens, total_tokens, api_duration, created_at)"
        " VALUES (?, ?, 'test', ?, ?, ?, 0, ?, 0.1, ?)",
        (f"sess-{day}", model, prompt, completion, cache_read, total,
         f"{day.isoformat()} {hour:02d}:00:00"),
    )


def _seed(conn: sqlite3.Connection) -> None:
    # Monday: two models, dominant cache
    _insert(conn, WEEK_MONDAY, "glm-5.3", 1_000_000, 10_000, 950_000, 1_010_000)
    _insert(conn, WEEK_MONDAY, "deepseek", 500_000, 5_000, 450_000, 505_000)
    # Wednesday: one model, no cache at all
    _insert(conn, WEEK_MONDAY + timedelta(days=2), "glm-5.3", 80_000, 8_000, 0, 88_000)
    # Sunday (end of week boundary — 23:59 must be included)
    _insert(conn, WEEK_MONDAY + timedelta(days=6), "glm-5.3", 200_000, 20_000, 150_000,
            220_000, hour=23)
    # Previous week (must be excluded)
    _insert(conn, OTHER_WEEK_DAY, "glm-5.3", 9_999_999, 999, 0, 9_999_999)


def _run_week(date_arg: str | None, offset: int = 0, mono: bool = False,
              width: int = 40) -> str:
    conn = _make_db()
    _seed(conn)
    orig_conn = Q._conn
    Q._conn = lambda: conn
    try:
        buf = io.StringIO()
        ns = argparse.Namespace(date=date_arg, offset=offset, mono=mono, width=width)
        with redirect_stdout(buf):
            Q.cmd_week(ns)
        return buf.getvalue()
    finally:
        Q._conn = orig_conn
        conn.close()


def test_week_bounds_monday_start():
    # 2026-09-27 is a Sunday; its week starts 2026-09-21 (Monday)
    mon, sun = Q._week_bounds(date(2026, 9, 27))
    assert mon == date(2026, 9, 21)
    assert sun == date(2026, 9, 27)
    # 2026-09-21 itself (Monday)
    mon, sun = Q._week_bounds(date(2026, 9, 21))
    assert mon == date(2026, 9, 21) and sun == date(2026, 9, 27)
    # offset shifts whole weeks
    mon, sun = Q._week_bounds(date(2026, 9, 23), offset=1)
    assert mon == date(2026, 9, 14) and sun == date(2026, 9, 20)


def test_week_header_and_exclusion():
    out = _run_week(None)
    assert "Week 2026-09-21 .. 2026-09-27" in out
    # previous week's record must not leak in
    assert "9,999,999" not in out
    assert "10.0M" not in out  # 9,999,999 formats as 10.0M


def test_week_totals():
    out = _run_week("2026-09-23")  # same week as Monday anchor
    # requests: 4, prompt sum = 1,780,000; cached = 1,550,000; output = 43,000
    assert "Requests:      4" in out
    assert "Input (New):   230,000" in out
    assert "Cache Read:    1,550,000" in out
    assert "Output:        43,000" in out
    assert "Total:         1,823,000" in out


def test_day_rows_present():
    out = _run_week(None)
    assert "09-21 周一" in out
    assert "09-23 周三" in out
    assert "09-27 周日" in out
    # days without records do not appear
    assert "09-22" not in out


def test_model_chart_grouping():
    out = _run_week(None)
    assert "# Weekly chart — by day × model" in out
    assert "glm-5.3" in out
    assert "deepseek" in out
    # blank line between day groups: a line ending in "——" followed by a blank
    lines = out.splitlines()
    day_headers = [i for i, ln in enumerate(lines) if ln.startswith("—— ")]
    assert len(day_headers) == 3  # three days with data
    for i in day_headers[1:]:
        assert lines[i - 1].strip() == ""  # blank line before each subsequent day


def test_truecolor_and_mono():
    color = _run_week(None, mono=False)
    assert "\033[38;2;110;155;255m" in color  # cached blue
    assert "\033[38;2;255;179;71m" in color   # new input amber
    assert "\033[38;2;120;224;143m" in color  # output green
    mono = _run_week(None, mono=True)
    assert "\033[38;2;255;255;255m" in mono   # cached white
    assert "\033[38;2;110;155;255m" not in mono
    assert "(mono grayscale)" in mono


def test_legend_format():
    out = _run_week(None)
    # Monday row: total 1,515,000 → 1.5M; 2 req; cached 1,400,000 → 1.4M;
    # new (1,500,000−1,400,000) → 100.0K; out 15,000 → 15.0K
    assert "1.5M (2 req / 1.4M / 100.0K / 15.0K)" in out


def test_offset_shifts_week():
    out = _run_week(None, offset=1)
    assert "Week 2026-09-14 .. 2026-09-20" in out
    assert "10.0M (1 req" in out  # the excluded record is now the only one


def test_empty_week():
    out = _run_week("2026-06-01")
    assert "(no records in this week)" in out


def test_by_model_table_and_summary_labels():
    out = _run_week(None)
    assert "[By model — week]" in out
    assert "# Weekly summary — 2026-09-21 .. 2026-09-27" in out
    assert "Avg/Day:" in out


def test_no_ansi_leak_into_labels_when_mono():
    mono = _run_week(None, mono=True)
    # legend text itself must be clean of escape sequences
    for ln in mono.splitlines():
        if " req / " in ln:
            after_bar = ln.split("│")[-1]
            assert "\033" not in after_bar


def test_allocate_run_minimum_one_cell():
    # output > 0 but tiny — must still get a cell
    alloc = Q._allocate_run([1000, 100, 1], 10)
    assert sum(alloc) == 10
    assert alloc[2] >= 1
    # zero-width and zero-total guards
    assert Q._allocate_run([1, 2, 3], 0) == [0, 0, 0]
    assert Q._allocate_run([0, 0, 0], 10) == [0, 0, 0]


# ---- /token week slash command -------------------------------------------------


def _load_plugin_module():
    spec = importlib.util.spec_from_file_location(
        "tct_plugin_test_module", PLUGIN_ROOT / "__init__.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_slash_command_week(tmp_path, monkeypatch):
    plugin = _load_plugin_module()
    # build a real temp DB file with one seeded week
    db_path = tmp_path / "token-usage.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE token_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL, turn_id TEXT, api_request_id TEXT,
            model TEXT NOT NULL, provider TEXT NOT NULL,
            prompt_tokens INTEGER DEFAULT 0, completion_tokens INTEGER DEFAULT 0,
            cache_read_tokens INTEGER DEFAULT 0, cache_write_tokens INTEGER DEFAULT 0,
            workspace TEXT DEFAULT '', worker TEXT DEFAULT '',
            total_tokens INTEGER DEFAULT 0, api_duration REAL DEFAULT 0.0,
            finish_reason TEXT, created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO token_usage (session_id, model, provider, prompt_tokens,"
        " completion_tokens, cache_read_tokens, total_tokens, created_at)"
        " VALUES ('s', 'glm-5.3', 't', 100000, 5000, 90000, 105000, '2026-09-23 10:00:00')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(plugin, "_DB_PATH", db_path)

    out = plugin._handle_slash_command("week 2026-09-23 --mono")
    assert "Week 2026-09-21 .. 2026-09-27" in out
    assert "09-23 周三" in out
    assert "glm-5.3" in out
    assert "\033[38;2;110;155;255m" not in out  # mono requested → no truecolor

    # default (this week) and error paths
    out2 = plugin._handle_slash_command("week --offset abc")
    assert "Invalid --offset value" in out2
    out3 = plugin._handle_slash_command("week bogusarg")
    assert "Unrecognized argument" in out3


def test_slash_command_help_lists_week():
    plugin = _load_plugin_module()
    help_text = plugin._handle_slash_command("")
    assert "/token week" in help_text
