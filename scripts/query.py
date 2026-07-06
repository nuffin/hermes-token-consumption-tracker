#!/usr/bin/env python3
"""Token usage DB query tool.

Usage:
    python3 scripts/query.py latest [N]          # 最近 N 条 (默认 10)
    python3 scripts/query.py session <prefix>     # 按 session 前缀
    python3 scripts/query.py model <name>         # 按模型名
    python3 scripts/query.py date <from> [to]     # 按日期
    python3 scripts/query.py summary [--today|<date>]  # 汇总
    python3 scripts/query.py raw <N>              # 最近 N 条 raw_usage
    python3 scripts/query.py raw --id <id>        # 指定 ID 的 raw_usage
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
from datetime import datetime, timedelta
from pathlib import Path

# Resolve DB path from Hermes config, fallback to ~/.hermes/token-usage.db
def _resolve_db_path() -> Path:
    """Resolve token-usage.db path with multi-layer config priority.

    Priority chain (highest to lowest):
      1. ``TOKEN_CONSUMPTION_DATA_DIR`` env var (plugin-specific)
      2. ``OBSERVABILITY_DATA_DIR`` env var (generic)
      3. Per-profile config:  ``observability.token-consumption-tracker.data_dir``
      4. Per-profile config:  ``observability.default.data_dir``
      5. Per-profile config:  ``observability.data_dir`` (legacy flat)
      6. Global config: same structure as steps 3-5
      7. Fallback:  ``~/.hermes``
    """
    hermes_home = os.environ.get("HERMES_HOME", "").strip()
    profile_config_path = Path(hermes_home) / "config.yaml" if hermes_home else None

    data_dir = None
    if profile_config_path:
        data_dir = _read_data_dir_from_config(profile_config_path)

    if not data_dir:
        try:
            from hermes_constants import get_default_hermes_root
            global_config_path = get_default_hermes_root() / "config.yaml"
            if (profile_config_path is None
                    or global_config_path.resolve() != profile_config_path.resolve()):
                data_dir = _read_data_dir_from_config(global_config_path)
        except ImportError:
            pass

    if not data_dir:
        data_dir = "~/.hermes"

    return Path(data_dir).expanduser() / "token-usage.db"


def _read_data_dir_from_config(config_path: Path | None) -> str | None:
    """Read ``observability`` data_dir from a YAML config file."""
    if not config_path or not config_path.exists():
        return None
    try:
        import yaml
        with open(config_path) as fh:
            config = yaml.safe_load(fh) or {}
        obs = config.get("observability")
        if not obs or not isinstance(obs, dict):
            return None
        # 1. Plugin-specific override
        plugin_cfg = obs.get("token-consumption-tracker")
        if isinstance(plugin_cfg, dict):
            val = plugin_cfg.get("data_dir")
            if val and isinstance(val, str):
                return val
        # 2. All-plugins default
        default_cfg = obs.get("default")
        if isinstance(default_cfg, dict):
            val = default_cfg.get("data_dir")
            if val and isinstance(val, str):
                return val
        # 3. Legacy flat
        val = obs.get("data_dir")
        if val and isinstance(val, str):
            return val
    except Exception:
        pass
    return None

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

    print(f"# 汇总 — {date_str}")
    print(f"请求数:        {cnt}")
    print(f"Input (新):    {actual_input:,}")
    print(f"Cache Read:    {cache_r:,}")
    if cache_w:
        print(f"Cache Write:   {cache_w:,}")
    print(f"Input (合计):  {inp:,}")
    print(f"Output:        {out:,}")
    print(f"Total:         {tot:,}")
    if cnt:
        print(f"平均/请求:     {tot // cnt:,}")
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
        print("Error: 至少指定一个条件 (--session / --before / --id)")
        sys.exit(1)

    where = " AND ".join(where_clauses)

    cur = conn.execute(f"SELECT COUNT(*) FROM token_usage WHERE {where}", params)
    count = cur.fetchone()[0]

    if count == 0:
        print("没有匹配的记录")
        conn.close()
        return

    print(f"将删除 {count} 条记录")
    print(f"条件: {' '.join(sys.argv[2:])}")

    if not args.force:
        try:
            confirm = input("确认删除？(y/N): ")
        except (EOFError, OSError):
            confirm = "n"
        if confirm.lower() != "y":
            print("已取消")
            conn.close()
            return

    conn.execute(f"DELETE FROM token_usage WHERE {where}", params)
    conn.commit()
    conn.close()
    print(f"已删除 {count} 条")


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
        print("Error: 指定 --after <date> 或 --all")
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

    p = sub.add_parser("latest", help="最新 N 条")
    p.add_argument("N", nargs="?", help="条数 (默认 10)")

    p = sub.add_parser("session", help="按 session 查")
    p.add_argument("prefix")

    p = sub.add_parser("model", help="按模型查")
    p.add_argument("name")

    p = sub.add_parser("date", help="按日期查")
    p.add_argument("from_date")
    p.add_argument("to_date", nargs="?")

    p = sub.add_parser("summary", help="汇总")
    p.add_argument("date", nargs="?", help="日期 YYYY-MM-DD")
    p.add_argument("--today", action="store_true", help="今天")

    p = sub.add_parser("raw", help="查看 raw_usage 原文")
    p.add_argument("N", nargs="?", help="最近 N 条")
    p.add_argument("--id", type=int, help="指定 ID")

    p = sub.add_parser("delete", help="删除记录")
    p.add_argument("--session", help="按 session 前缀")
    p.add_argument("--before", help="某天之前 (YYYY-MM-DD)")
    p.add_argument("--id", type=int, help="指定 ID")
    p.add_argument("--force", action="store_true", help="跳过确认")

    p = sub.add_parser("export", help="导出 JSONL")
    p.add_argument("--after", help="从某天开始")
    p.add_argument("--all", action="store_true", help="全部导出")

    args = parser.parse_args()

    dispatch = {
        "latest": cmd_latest,
        "session": cmd_session,
        "model": cmd_model,
        "date": cmd_date,
        "summary": cmd_summary,
        "raw": cmd_raw,
        "delete": cmd_delete,
        "export": cmd_export,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
