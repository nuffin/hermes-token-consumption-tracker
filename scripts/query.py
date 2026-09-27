#!/usr/bin/env python3
"""Token usage DB query tool.

Usage:
    python3 scripts/query.py latest [N]          # last N records (default 10)
    python3 scripts/query.py session <prefix>     # by session prefix
    python3 scripts/query.py model <name>         # by model name
    python3 scripts/query.py date <from> [to]     # by date range
    python3 scripts/query.py summary [--today|<date>]  # daily summary
    python3 scripts/query.py week [date] [--offset N] [--mono] [--width W]  # weekly report
    python3 scripts/query.py raw <N>              # last N raw_usage
    python3 scripts/query.py raw --id <id>        # raw_usage by ID
    python3 scripts/query.py delete --session <prefix> [--force]
    python3 scripts/query.py delete --before <date> [--force]
    python3 scripts/query.py delete --id <id> [--force]
    python3 scripts/query.py export [--after <date>] [--all]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Resolve DB path from Hermes config, fallback to ~/.hermes/personal/token-usage.db
def _resolve_db_path() -> Path:
    hermes_home = os.environ.get("HERMES_HOME", "")
    config_path = Path(hermes_home) / "config.yaml" if hermes_home else None
    data_dir = None
    if config_path and config_path.exists():
        try:
            import yaml
            with open(config_path) as fh:
                config = yaml.safe_load(fh) or {}
            obs = config.get("observability", {})
            data_dir = (
                obs.get("token-consumption-tracker", {}).get("data_dir")
                or obs.get("data_dir")
            )
        except Exception:
            pass
    if not data_dir:
        data_dir = "~/.hermes/personal"
    return Path(data_dir).expanduser() / "token-usage.db"

_DB = _resolve_db_path()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB))
    conn.row_factory = sqlite3.Row
    return conn


# ---- latest -----------------------------------------------------------------


def cmd_latest(args: argparse.Namespace) -> None:
    n = int(args.N) if args.N else 10
    conn = _conn()
    cur = conn.execute(
        "SELECT * FROM token_usage ORDER BY id DESC LIMIT ?", (n,)
    )
    rows = cur.fetchall()
    conn.close()
    _print_table(rows)


# ---- by session


def cmd_session(args: argparse.Namespace) -> None:
    conn = _conn()
    cur = conn.execute(
        "SELECT * FROM token_usage WHERE session_id LIKE ? ORDER BY id DESC LIMIT 50",
        (f"{args.prefix}%",),
    )
    rows = cur.fetchall()
    conn.close()
    _print_table(rows)


# ---- by model


def cmd_model(args: argparse.Namespace) -> None:
    conn = _conn()
    cur = conn.execute(
        "SELECT * FROM token_usage WHERE model LIKE ? ORDER BY id DESC LIMIT 50",
        (f"%{args.name}%",),
    )
    rows = cur.fetchall()
    conn.close()
    _print_table(rows)


# ---- by date


def cmd_date(args: argparse.Namespace) -> None:
    date_from = args.from_date
    date_to = args.to_date if args.to_date else date_from
    conn = _conn()
    cur = conn.execute(
        "SELECT * FROM token_usage WHERE created_at >= ? AND created_at <= ? ORDER BY id DESC LIMIT 100",
        (f"{date_from} 00:00:00", f"{date_to} 23:59:59"),
    )
    rows = cur.fetchall()
    conn.close()
    _print_table(rows)


# ---- summary


def cmd_summary(args: argparse.Namespace) -> None:
    if args.today:
        date_str = datetime.now().strftime("%Y-%m-%d")
    elif args.date:
        date_str = args.date
    else:
        date_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    conn = _conn()
    c = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(prompt_tokens),0), COALESCE(SUM(completion_tokens),0), "
        "COALESCE(SUM(total_tokens),0), COALESCE(SUM(cache_read_tokens),0), COALESCE(SUM(cache_write_tokens),0) "
        "FROM token_usage WHERE created_at >= ? AND created_at < ?",
        (f"{date_str} 00:00:00", f"{date_str} 23:59:59"),
    )
    cnt, inp, out, tot, cache_r, cache_w = c.fetchone()
    actual_input = inp - cache_r - cache_w

    print(f"# Summary — {date_str}")
    print(f"Requests:      {cnt}")
    print(f"Input (New):   {actual_input:,}")
    print(f"Cache Read:    {cache_r:,}")
    if cache_w:
        print(f"Cache Write:   {cache_w:,}")
    print(f"Input (Total): {inp:,}")
    print(f"Output:        {out:,}")
    print(f"Total:         {tot:,}")
    if cnt:
        print(f"Avg/Request:   {tot // cnt:,}")
    print()

    # by model
    c = conn.execute(
        "SELECT model, COUNT(*), SUM(prompt_tokens), SUM(completion_tokens), SUM(total_tokens),"
        "COALESCE(SUM(cache_read_tokens),0), COALESCE(SUM(cache_write_tokens),0), ROUND(AVG(api_duration),2) "
        "FROM token_usage WHERE created_at >= ? AND created_at < ? "
        "GROUP BY model ORDER BY SUM(total_tokens) DESC",
        (f"{date_str} 00:00:00", f"{date_str} 23:59:59"),
    )
    rows = c.fetchall()
    if rows:
        print(f"{'Model':<25}  {'Req':>4}  {'Input':>10}  {'Out':>6}  {'CacheR':>8}  {'CacheW':>8}  {'Total':>10}  {'Avg(s)':>6}")
        print("-" * 90)
        for r in rows:
            print(f"{r[0]:<25}  {r[1]:>4}  {r[2]:>10,}  {r[3]:>6,}  {r[5]:>8,}  {r[6]:>8,}  {r[4]:>10,}  {r[7]:>6}")

    # by workspace
    c = conn.execute(
        "SELECT workspace, COUNT(*), SUM(prompt_tokens), SUM(completion_tokens), SUM(total_tokens) "
        "FROM token_usage WHERE created_at >= ? AND created_at < ? "
        "GROUP BY workspace ORDER BY SUM(total_tokens) DESC",
        (f"{date_str} 00:00:00", f"{date_str} 23:59:59"),
    )
    ws_rows = c.fetchall()
    if ws_rows and len(ws_rows) > 1:
        print()
        print(f"{'Workspace':<12}  {'Req':>4}  {'Input':>10}  {'Out':>6}  {'Total':>10}")
        print("-" * 52)
        for r in ws_rows:
            print(f"{(r[0] or '-'):<12}  {r[1]:>4}  {r[2]:>10,}  {r[3]:>6,}  {r[4]:>10,}")
    conn.close()


# ---- week -------------------------------------------------------------------


# Chart segment semantics (same as summary): cached = cache_read + cache_write,
# new_input = prompt − cached (floored at 0), output = completion.
_WEEK_SEGMENTS = ("cached", "new_input", "output")

# 24-bit ANSI truecolor; --mono switches to brightness-only grayscale.
_SEGMENT_COLORS = {
    "cached": (110, 155, 255),    # blue
    "new_input": (255, 179, 71),  # amber
    "output": (120, 224, 143),    # green
}
_MONO_SHADES = {
    "cached": (255, 255, 255),    # brightest
    "new_input": (170, 170, 170),
    "output": (96, 96, 96),       # darkest
}
_SEGMENT_GLYPHS = {"cached": "█", "new_input": "▓", "output": "░"}
_RESET = "\033[0m"


def _week_bounds(anchor: date, offset: int = 0) -> tuple[date, date]:
    """Monday-start week containing `anchor`, shifted back `offset` weeks."""
    monday = anchor - timedelta(days=anchor.weekday()) - timedelta(weeks=offset)
    return monday, monday + timedelta(days=6)


def _fmt_tokens(n: float) -> str:
    n = int(n)
    if n >= 1_000_000_000:
        return f"{n / 1e9:.2f}B"
    if n >= 1_000_000:
        return f"{n / 1e6:.1f}M"
    if n >= 1_000:
        return f"{n / 1e3:.1f}K"
    return str(n)


def _seg_escape(idx: int, mono: bool) -> str:
    """ANSI escape for segment color; grayscale when mono."""
    seg = _WEEK_SEGMENTS[idx]
    rgb = _MONO_SHADES[seg] if mono else _SEGMENT_COLORS[seg]
    return f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m"


def _allocate_run(counts: list[int], width: int) -> list[int]:
    """Split `width` cells across segments proportionally to counts.

    Largest-remainder allocation; segments with count > 0 get at least one
    cell (stolen from the largest run when needed).
    """
    total = sum(counts)
    if width <= 0 or total <= 0:
        return [0] * len(counts)
    raw = [c / total * width for c in counts]
    alloc = [int(r) for r in raw]
    leftover = width - sum(alloc)
    order = sorted(range(len(counts)), key=lambda i: raw[i] - alloc[i], reverse=True)
    for k in range(max(leftover, 0)):
        alloc[order[k % len(counts)]] += 1
    for i in range(len(counts)):
        if counts[i] > 0 and alloc[i] == 0:
            donor = max(range(len(counts)), key=lambda j: alloc[j])
            if alloc[donor] > 1:
                alloc[donor] -= 1
                alloc[i] += 1
    return alloc


def _render_bar(total: int, seg_counts: list[int], width: int, mono: bool) -> str:
    """One stacked bar; length proportional to total / chart peak."""
    if total <= 0:
        return " " * width
    n = max(round(total / _RENDER_MAX[0] * width), 1)
    alloc = _allocate_run(seg_counts, n)
    out = []
    for i, a in enumerate(alloc):
        if a > 0:
            out.append(f"{_seg_escape(i, mono)}{_SEGMENT_GLYPHS[_WEEK_SEGMENTS[i]] * a}{_RESET}")
    return "".join(out)


_RENDER_MAX = [1]  # set per chart: peak value for full-width scaling


_WEEKDAY_ZH = "一二三四五六日"


def _legend(x: dict) -> str:
    return (
        f'{_fmt_tokens(x["total"])} ({x["req"]:,} req / {_fmt_tokens(x["cached"])}'
        f' / {_fmt_tokens(x["new_input"])} / {_fmt_tokens(x["output"])})'
    )


def _print_week_chart(days: dict, mono: bool, width: int) -> None:
    """Chart 1: one stacked bar per day."""
    _RENDER_MAX[0] = max((d["total"] for d in days.values()), default=1)
    print()
    print(f"# Weekly chart — by day (1 cell ≈ {_fmt_tokens(_RENDER_MAX[0] / width)} at peak)")
    if mono:
        print("    █ cached   ▓ new input   ░ output  (mono grayscale)")
    else:
        print("    █ cached   ▓ new input   ░ output  (truecolor)")
    for d in sorted(days):
        x = days[d]
        wd = _WEEKDAY_ZH[datetime.strptime(d, "%Y-%m-%d").weekday()]
        bar = _render_bar(x["total"], [x["cached"], x["new_input"], x["output"]], width, mono)
        print(f"{d[5:]} 周{wd} │{bar}│ {_legend(x)}")
    if days:
        print("─" * 10 + "┼" + "─" * width + "┼" + "─" * 40)
        print("    legend: TOTAL (req / cached / new input / output); bar length = day total")


def _print_week_model_chart(days_models: dict, mono: bool, width: int) -> None:
    """Chart 2: grouped bars — one row per (day, model), blank line between days."""
    max_val = max(
        (m["total"] for dms in days_models.values() for m in dms.values()), default=0
    )
    if max_val == 0:
        return
    _RENDER_MAX[0] = max_val
    print()
    print("# Weekly chart — by day × model")
    print(f"    bar length = model-day total (peak day-model = {width} cells)")
    first = True
    for d in sorted(days_models):
        if not first:
            print()
        first = False
        wd = _WEEKDAY_ZH[datetime.strptime(d, "%Y-%m-%d").weekday()]
        print(f"—— {d[5:]} 周{wd} ——")
        for m, x in sorted(days_models[d].items(), key=lambda kv: -kv[1]["total"]):
            bar = _render_bar(x["total"], [x["cached"], x["new_input"], x["output"]], width, mono)
            print(f"  {m[:24]:<24} │{bar}│ {_legend(x)}")
    print("─" * 27 + "┼" + "─" * width + "┼" + "─" * 40)
    print("    legend: TOTAL (req / cached / new input / output); bar length = model-day total")


def _week_summary_block(
    from_d: str, to_d: str, cnt: int, inp: int, actual_input: int,
    cache_r: int, cache_w: int, out: int, tot: int,
) -> None:
    """Weekly totals — mirrors daily summary layout."""
    print()
    print(f"# Weekly summary — {from_d} .. {to_d}")
    print(f"Requests:      {cnt:,}")
    print(f"Input (New):   {actual_input:,}")
    print(f"Cache Read:    {cache_r:,}")
    if cache_w:
        print(f"Cache Write:   {cache_w:,}")
    print(f"Input (Total): {inp:,}")
    print(f"Output:        {out:,}")
    print(f"Total:         {tot:,}")
    if cnt:
        print(f"Avg/Request:   {tot // cnt:,}")
    print(f"Avg/Day:       {tot // 7:,}")
    if cnt:
        print(f"Requests/Day:  {cnt / 7:.0f}")


def _model_table(model_rows: list, title: str = "By model") -> None:
    """Reuse of the daily-summary by-model table for week scope."""
    if not model_rows:
        return
    print()
    print(f"[{title}]")
    print(f"{'Model':<25}  {'Req':>4}  {'Input':>10}  {'Out':>6}  {'CacheR':>8}  {'CacheW':>8}  {'Total':>10}  {'Avg(s)':>6}")
    print("-" * 90)
    for r in model_rows:
        print(f"{r[0]:<25}  {r[1]:>4}  {r[2]:>10,}  {r[3]:>6,}  {r[5]:>8,}  {r[6]:>8,}  {r[4]:>10,}  {r[7]:>6}")


def _ws_table(ws_rows: list) -> None:
    if ws_rows and len(ws_rows) > 1:
        print()
        print("[By workspace]")
        print(f"{'Workspace':<12}  {'Req':>4}  {'Input':>10}  {'Out':>6}  {'Total':>10}")
        print("-" * 52)
        for r in ws_rows:
            print(f"{(r[0] or '-'):<12}  {r[1]:>4}  {r[2]:>10,}  {r[3]:>6,}  {r[4]:>10,}")


def cmd_week(args: argparse.Namespace) -> None:
    # week window (Monday-start); `date` anchors its week, `offset` shifts back
    anchor = (
        datetime.strptime(args.date, "%Y-%m-%d").date()
        if args.date
        else date.today()
    )
    monday, sunday = _week_bounds(anchor, args.offset)
    from_ts = f"{monday.isoformat()} 00:00:00"
    to_ts = f"{sunday.isoformat()} 23:59:59"

    conn = _conn()

    # week totals
    cnt, inp, out, tot, cache_r, cache_w = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(prompt_tokens),0), COALESCE(SUM(completion_tokens),0), "
        "COALESCE(SUM(total_tokens),0), COALESCE(SUM(cache_read_tokens),0), COALESCE(SUM(cache_write_tokens),0) "
        "FROM token_usage WHERE created_at >= ? AND created_at <= ?",
        (from_ts, to_ts),
    ).fetchone()
    actual_input = inp - cache_r - cache_w

    # by day
    days: dict[str, dict] = {}
    for d, c, p, o, t, cr, cw in conn.execute(
        "SELECT substr(created_at,1,10) d, COUNT(*), COALESCE(SUM(prompt_tokens),0), COALESCE(SUM(completion_tokens),0), "
        "COALESCE(SUM(total_tokens),0), COALESCE(SUM(cache_read_tokens),0), COALESCE(SUM(cache_write_tokens),0) "
        "FROM token_usage WHERE created_at >= ? AND created_at <= ? GROUP BY d ORDER BY d",
        (from_ts, to_ts),
    ).fetchall():
        cached = cr + cw
        days[d] = {
            "req": c, "prompt": p, "output": o, "total": t,
            "cached": cached, "new_input": max(p - cached, 0),
        }

    # by day × model
    days_models: dict[str, dict[str, dict]] = {}
    for d, m, c, p, o, t, cr, cw in conn.execute(
        "SELECT substr(created_at,1,10) d, model, COUNT(*), COALESCE(SUM(prompt_tokens),0), COALESCE(SUM(completion_tokens),0), "
        "COALESCE(SUM(total_tokens),0), COALESCE(SUM(cache_read_tokens),0), COALESCE(SUM(cache_write_tokens),0) "
        "FROM token_usage WHERE created_at >= ? AND created_at <= ? GROUP BY d, model",
        (from_ts, to_ts),
    ).fetchall():
        cached = cr + cw
        days_models.setdefault(d, {})[m] = {
            "req": c, "prompt": p, "output": o, "total": t,
            "cached": cached, "new_input": max(p - cached, 0),
        }

    width = args.width
    mono = args.mono

    # header
    label = f"Week {monday.isoformat()} .. {sunday.isoformat()}"
    if tot == 0:
        print(f"{label}")
        print("(no records in this week)")
        return

    print(f"Token usage — {label}")

    # chart 1: by day
    _print_week_chart(days, mono, width)

    # chart 2: by day × model
    _print_week_model_chart(days_models, mono, width)

    # summary block
    _week_summary_block(
        monday.isoformat(), sunday.isoformat(), cnt, inp, actual_input,
        cache_r, cache_w, out, tot,
    )

    # by model (reuse week-scoped query)
    model_rows = conn.execute(
        "SELECT model, COUNT(*), SUM(prompt_tokens), SUM(completion_tokens), SUM(total_tokens),"
        "COALESCE(SUM(cache_read_tokens),0), COALESCE(SUM(cache_write_tokens),0), ROUND(AVG(api_duration),2) "
        "FROM token_usage WHERE created_at >= ? AND created_at <= ? "
        "GROUP BY model ORDER BY SUM(total_tokens) DESC",
        (from_ts, to_ts),
    ).fetchall()
    _model_table(model_rows, title="By model — week")

    # by workspace
    ws_rows = conn.execute(
        "SELECT workspace, COUNT(*), SUM(prompt_tokens), SUM(completion_tokens), SUM(total_tokens) "
        "FROM token_usage WHERE created_at >= ? AND created_at <= ? "
        "GROUP BY workspace ORDER BY SUM(total_tokens) DESC",
        (from_ts, to_ts),
    ).fetchall()
    _ws_table(ws_rows)
    conn.close()


# ---- raw_usage


def cmd_raw(args: argparse.Namespace) -> None:
    conn = _conn()
    if args.id:
        cur = conn.execute("SELECT id, created_at, raw_usage FROM token_usage WHERE id = ?", (args.id,))
    else:
        n = int(args.N) if args.N else 5
        cur = conn.execute("SELECT id, created_at, raw_usage FROM token_usage ORDER BY id DESC LIMIT ?", (n,))
    rows = cur.fetchall()
    conn.close()

    if not rows:
        print("(no records)")
        return

    for r in rows:
        print(f"--- ID={r['id']}  {r['created_at']} ---")
        raw = r["raw_usage"]
        if raw:
            try:
                parsed = json.loads(raw)
                print(json.dumps(parsed, ensure_ascii=False, indent=2))
            except json.JSONDecodeError:
                print(raw)
        else:
            print("(not recorded)")
        print()


# ---- delete


def cmd_delete(args: argparse.Namespace) -> None:
    conn = _conn()

    where_clauses: list[str] = []
    params: list = []

    if args.session:
        where_clauses.append("session_id LIKE ?")
        params.append(f"{args.session}%")
    if args.before:
        where_clauses.append("created_at < ?")
        params.append(f"{args.before} 00:00:00")
    if args.id:
        where_clauses.append("id = ?")
        params.append(args.id)

    if not where_clauses:
        print("Error: specify at least one filter (--session / --before / --id)")
        sys.exit(1)

    where = " AND ".join(where_clauses)

    cur = conn.execute(f"SELECT COUNT(*) FROM token_usage WHERE {where}", params)
    count = cur.fetchone()[0]

    if count == 0:
        print("No matching records.")
        conn.close()
        return

    print(f"Will delete {count} record(s)")
    print(f"Filter: {' '.join(sys.argv[2:])}")

    if not args.force:
        try:
            confirm = input("Confirm deletion? (y/N): ")
        except (EOFError, OSError):
            confirm = "n"
        if confirm.lower() != "y":
            print("Cancelled.")
            conn.close()
            return

    conn.execute(f"DELETE FROM token_usage WHERE {where}", params)
    conn.commit()
    conn.close()
    print(f"Deleted {count} record(s).")


# ---- export


def cmd_export(args: argparse.Namespace) -> None:
    conn = _conn()
    if args.all:
        cur = conn.execute("SELECT * FROM token_usage ORDER BY id")
    elif args.after:
        cur = conn.execute(
            "SELECT * FROM token_usage WHERE created_at >= ? ORDER BY id",
            (f"{args.after} 00:00:00",),
        )
    else:
        print("Error: specify --after <date> or --all")
        conn.close()
        return

    for row in cur.fetchall():
        d = dict(row)
        if d.get("raw_usage"):
            try:
                d["raw_usage"] = json.loads(d["raw_usage"])
            except (json.JSONDecodeError, TypeError):
                pass
        print(json.dumps(d, ensure_ascii=False, default=str))
    conn.close()


# ---- helpers


def _print_table(rows: list[sqlite3.Row]) -> None:
    if not rows:
        print("(no records)")
        return
    print(f"{'ID':>4}  {'Time':<19}  {'Model':<25}  {'Input':>8}  {'Out':>6}  {'CacheR':>7}  {'CacheW':>7}  {'Total':>8}  {'WS':<8}  {'Worker':<12}")
    print("-" * 125)
    for r in rows:
        cache_r = r['cache_read_tokens'] or 0
        cache_w = r['cache_write_tokens'] or 0
        ws = (r['workspace'] or '')[:8] if 'workspace' in r.keys() else ''
        wkr = (r['worker'] or '')[:12] if 'worker' in r.keys() else ''
        print(f"{r['id']:>4}  {r['created_at']:<19}  {r['model']:<25}  {r['prompt_tokens']:>8,}  {r['completion_tokens']:>6,}  {cache_r:>7,}  {cache_w:>7,}  {r['total_tokens']:>8,}  {ws:<8}  {wkr:<12}")


# ---- main


def main() -> None:
    parser = argparse.ArgumentParser(description="Token usage DB query tool")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("latest", help="latest N records (default 10)")
    p.add_argument("N", nargs="?", help="count (default 10)")

    p = sub.add_parser("session", help="query by session prefix")
    p.add_argument("prefix")

    p = sub.add_parser("model", help="query by model name")
    p.add_argument("name")

    p = sub.add_parser("date", help="query by date range")
    p.add_argument("from_date")
    p.add_argument("to_date", nargs="?")

    p = sub.add_parser("summary", help="daily summary")
    p.add_argument("date", nargs="?", help="date YYYY-MM-DD")
    p.add_argument("--today", action="store_true", help="show today's summary")

    p = sub.add_parser("week", help="weekly report (Monday-start)")
    p.add_argument("date", nargs="?", help="anchor date YYYY-MM-DD — shows its week")
    p.add_argument("--offset", type=int, default=0, help="shift N weeks back from the anchor week")
    p.add_argument("--mono", action="store_true", help="grayscale instead of truecolor")
    p.add_argument("--width", type=int, default=40, help="bar width in cells (default 40)")

    p = sub.add_parser("raw", help="view raw_usage JSON")
    p.add_argument("N", nargs="?", help="last N records (default 5)")
    p.add_argument("--id", type=int, help="record ID")

    p = sub.add_parser("delete", help="delete records")
    p.add_argument("--session", help="session prefix")
    p.add_argument("--before", help="before date (YYYY-MM-DD)")
    p.add_argument("--id", type=int, help="record ID")
    p.add_argument("--force", action="store_true", help="skip confirmation")

    p = sub.add_parser("export", help="export as JSONL")
    p.add_argument("--after", help="from date (YYYY-MM-DD)")
    p.add_argument("--all", action="store_true", help="export all records")

    args = parser.parse_args()

    dispatch = {
        "latest": cmd_latest,
        "session": cmd_session,
        "model": cmd_model,
        "date": cmd_date,
        "summary": cmd_summary,
        "week": cmd_week,
        "raw": cmd_raw,
        "delete": cmd_delete,
        "export": cmd_export,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
