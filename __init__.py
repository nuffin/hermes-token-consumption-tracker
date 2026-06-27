"""token-consumption-tracker plugin.

Hooks into ``post_api_request`` to record per-request token consumption
(prompt_tokens, completion_tokens, total_tokens, model, provider, session_id)
into a local SQLite database at ``~/.hermes/personal/token-usage.db``.

Provides ``generate_report()`` for daily/weekly summary generation.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---- paths ------------------------------------------------------------------

def _resolve_data_dir() -> Path:
    """Resolve observability data directory from Hermes config.

    Reads ``$HERMES_HOME/config.yaml``, extracts ``observability.data_dir``
    (with per-plugin ``observability.token-consumption-tracker.data_dir``
    override).  Falls back to ``~/.hermes/`` when config is missing or
    unreadable.
    """
    hermes_home = os.environ.get("HERMES_HOME", "")
    config_path = Path(hermes_home) / "config.yaml" if hermes_home else None

    data_dir = None
    if config_path and config_path.exists():
        try:
            import yaml
            with open(config_path) as fh:
                config = yaml.safe_load(fh) or {}
            obs = config.get("observability", {})
            # Per-plugin override takes priority
            data_dir = (
                obs.get("token-consumption-tracker", {}).get("data_dir")
                or obs.get("data_dir")
            )
        except Exception:
            pass

    if not data_dir:
        data_dir = "~/.hermes"

    return Path(data_dir).expanduser()


_HERMES_PERSONAL = _resolve_data_dir()
_DB_PATH = _HERMES_PERSONAL / "token-usage.db"
_REPORT_DIR = _HERMES_PERSONAL / "token-usage"

# ---- thread-safe write queue ------------------------------------------------
# Post_API_request fires synchronously in the LLM call path — we must NOT block
# the caller with a SQLite write.  Queue the record and flush asynchronously.

_lock = threading.Lock()
_queue: list[dict[str, Any]] = []
_flush_timer: threading.Timer | None = None
_FLUSH_INTERVAL = 3.0  # flush every 3 seconds (or on session end)


def _init_db() -> None:
    """Create the database and table if they don't exist."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS token_usage (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT NOT NULL,
                turn_id     TEXT,
                api_request_id TEXT,
                model       TEXT NOT NULL,
                provider    TEXT NOT NULL,
                profile     TEXT DEFAULT '',
                prompt_tokens   INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                cache_read_tokens  INTEGER DEFAULT 0,
                cache_write_tokens INTEGER DEFAULT 0,
                workspace       TEXT DEFAULT '',
                worker          TEXT DEFAULT '',
                total_tokens    INTEGER DEFAULT 0,
                api_duration    REAL DEFAULT 0.0,
                finish_reason   TEXT,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_token_usage_created_at
            ON token_usage(created_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_token_usage_session
            ON token_usage(session_id)
            """
        )
        # Add columns if missing (schema migration)
        for col, col_type in (("raw_usage", "TEXT"), ("cache_read_tokens", "INTEGER DEFAULT 0"),
                               ("cache_write_tokens", "INTEGER DEFAULT 0"),
                               ("workspace", "TEXT DEFAULT ''"), ("worker", "TEXT DEFAULT ''"),
                               ("profile", "TEXT DEFAULT ''")):
            try:
                conn.execute(f"ALTER TABLE token_usage ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass
        conn.commit()
    finally:
        conn.close()


def _flush_queue() -> None:
    """Write all queued records to the database in a single transaction."""
    global _flush_timer
    _flush_timer = None

    with _lock:
        records = list(_queue)
        _queue.clear()

    if not records:
        return

    try:
        conn = sqlite3.connect(str(_DB_PATH))
        try:
            conn.executemany(
                """
                INSERT INTO token_usage
                    (session_id, turn_id, api_request_id, model, provider, profile,
                     prompt_tokens, completion_tokens, total_tokens,
                     cache_read_tokens, cache_write_tokens,
                     workspace, worker,
                     api_duration, finish_reason, created_at, raw_usage)
                VALUES
                    (:session_id, :turn_id, :api_request_id, :model, :provider, :profile,
                     :prompt_tokens, :completion_tokens, :total_tokens,
                     :cache_read_tokens, :cache_write_tokens,
                     :workspace, :worker,
                     :api_duration, :finish_reason, :created_at, :raw_usage)
                """,
                records,
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.warning("token-consumption-tracker: _flush_queue failed", exc_info=True)


def _schedule_flush() -> None:
    """Start or restart the async flush timer."""
    global _flush_timer

    if _flush_timer is not None and _flush_timer.is_alive():
        # Already scheduled — cancel and restart
        _flush_timer.cancel()

    _flush_timer = threading.Timer(_FLUSH_INTERVAL, _flush_queue)
    _flush_timer.daemon = True
    _flush_timer.start()


def flush_now() -> None:
    """Force an immediate flush.  Safe to call from any thread."""
    if _flush_timer is not None:
        _flush_timer.cancel()
    _flush_queue()


# ---- hook handler -----------------------------------------------------------


def _has_token_usage(usage: Any) -> bool:
    """Check if the usage dict has meaningful token counts."""
    if usage is None:
        return False
    if isinstance(usage, dict):
        return bool(usage.get("prompt_tokens") or usage.get("total_tokens"))
    if isinstance(usage, (int, float)):
        return usage > 0
    return True


def _on_post_api_request(**kw: Any) -> None:
    """Record token usage per API request."""
    usage: Any = kw.get("usage")

    if not _has_token_usage(usage):
        return
    # After _has_token_usage returns True, usage is guaranteed non-None
    usage_dict: dict = usage if isinstance(usage, dict) else {}

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    record = {
        "session_id": kw.get("session_id", ""),
        "turn_id": kw.get("turn_id", ""),
        "api_request_id": kw.get("api_request_id", ""),
        "model": kw.get("model", "unknown"),
        "provider": kw.get("provider", "unknown"),
        "profile": kw.get("profile", os.environ.get("HERMES_PROFILE", "")),
        "prompt_tokens": int(usage_dict.get("prompt_tokens", 0)),
        "completion_tokens": int(usage_dict.get("output_tokens", 0)),
        "total_tokens": int(usage_dict.get("total_tokens", 0)),
        "cache_read_tokens": int(usage_dict.get("cache_read_tokens", 0)),
        "cache_write_tokens": int(usage_dict.get("cache_write_tokens", 0)),
        "workspace": os.environ.get("HERMES_KANBAN_WORKSPACE", ""),
        "worker": os.environ.get("HERMES_KANBAN_TASK", ""),
        "api_duration": float(kw.get("api_duration", 0)),
        "finish_reason": kw.get("finish_reason", ""),
        "created_at": now,
        "raw_usage": json.dumps(usage_dict, ensure_ascii=False),
    }

    with _lock:
        _queue.append(record)

    _schedule_flush()


def _on_session_end(**kw: Any) -> None:
    """Flush any remaining records when the session ends."""
    flush_now()


# ---- report generation ------------------------------------------------------


def _db_connect() -> sqlite3.Connection:
    """Open a read-only connection to the token usage DB."""
    _init_db()
    return sqlite3.connect(str(_DB_PATH))


def generate_report(date_str: str | None = None) -> str:
    """Generate a daily usage report in markdown format.

    Args:
        date_str: Date in ``YYYY-MM-DD`` format.  Defaults to yesterday.

    Returns:
        Markdown report string.
    """
    # Ensure any pending records are written before querying
    flush_now()

    if date_str is None:
        date_str = (
            datetime.datetime.now() - datetime.timedelta(days=1)
        ).strftime("%Y-%m-%d")

    conn = _db_connect()
    try:
        cursor = conn.cursor()

        # ---- totals (with cache) ----
        cursor.execute(
            """
            SELECT COUNT(*),
                   COALESCE(SUM(prompt_tokens), 0),
                   COALESCE(SUM(completion_tokens), 0),
                   COALESCE(SUM(total_tokens), 0),
                   COALESCE(SUM(cache_read_tokens), 0),
                   COALESCE(SUM(cache_write_tokens), 0)
            FROM token_usage
            WHERE created_at >= ? AND created_at < ?
            """,
            (f"{date_str} 00:00:00", f"{date_str} 23:59:59"),
        )
        total_count, total_prompt, total_completion, total_all, total_cache_read, total_cache_write = cursor.fetchone()

        # ---- by model ----
        cursor.execute(
            """
            SELECT model,
                   COUNT(*),
                   SUM(prompt_tokens),
                   SUM(completion_tokens),
                   SUM(total_tokens),
                   ROUND(AVG(api_duration), 2)
            FROM token_usage
            WHERE created_at >= ? AND created_at < ?
            GROUP BY model
            ORDER BY SUM(total_tokens) DESC
            """,
            (f"{date_str} 00:00:00", f"{date_str} 23:59:59"),
        )
        by_model = cursor.fetchall()

        # ---- by session ----
        cursor.execute(
            """
            SELECT session_id,
                   COUNT(*),
                   SUM(prompt_tokens),
                   SUM(completion_tokens),
                   SUM(total_tokens)
            FROM token_usage
            WHERE created_at >= ? AND created_at < ?
            GROUP BY session_id
            ORDER BY SUM(total_tokens) DESC
            LIMIT 10
            """,
            (f"{date_str} 00:00:00", f"{date_str} 23:59:59"),
        )
        by_session = cursor.fetchall()

        # ---- by provider ----
        cursor.execute(
            """
            SELECT provider,
                   COUNT(*),
                   SUM(total_tokens)
            FROM token_usage
            WHERE created_at >= ? AND created_at < ?
            GROUP BY provider
            ORDER BY SUM(total_tokens) DESC
            """,
            (f"{date_str} 00:00:00", f"{date_str} 23:59:59"),
        )
        by_provider = cursor.fetchall()

        # ---- hourly breakdown ----
        cursor.execute(
            """
            SELECT strftime('%H', created_at) as hour,
                   COUNT(*),
                   SUM(total_tokens)
            FROM token_usage
            WHERE created_at >= ? AND created_at < ?
            GROUP BY hour
            ORDER BY hour
            """,
            (f"{date_str} 00:00:00", f"{date_str} 23:59:59"),
        )
        by_hour = cursor.fetchall()

    finally:
        conn.close()

    # ---- build report ----
    lines: list[str] = []
    lines.append(f"# Token Usage Report — {date_str}")
    lines.append("")

    # Summary header
    lines.append("## 当日汇总")
    lines.append("")
    actual_input = total_prompt - total_cache_read - total_cache_write
    lines.append(f"| 指标 | 数值 |")
    lines.append(f"|------|------|")
    lines.append(f"| API 请求数 | {total_count} |")
    lines.append(f"| Input (新) | {actual_input:,} |")
    lines.append(f"| Cache Read | {total_cache_read:,} |")
    if total_cache_write:
        lines.append(f"| Cache Write | {total_cache_write:,} |")
    lines.append(f"| Input (合计) | {total_prompt:,} |")
    lines.append(f"| Output | {total_completion:,} |")
    lines.append(f"| 总计 | {total_all:,} |")
    if total_count > 0:
        avg_tokens = total_all // total_count
        lines.append(f"| 平均/请求 | {avg_tokens:,} |")
    lines.append("")

    # By model
    if by_model:
        lines.append("## 按模型统计")
        lines.append("")
        lines.append("| 模型 | 请求数 | Input | Output | 总计 | 平均耗时(s) |")
        lines.append("|------|--------|-------|--------|------|------------|")
        for row in by_model:
            model_name, cnt, inp, out, tot, avg_dur = row
            lines.append(f"| {model_name} | {cnt} | {inp:,} | {out:,} | {tot:,} | {avg_dur} |")
        lines.append("")

    # By provider
    if by_provider:
        lines.append("## 按 Provider 统计")
        lines.append("")
        lines.append("| Provider | 请求数 | 总 Tokens |")
        lines.append("|----------|--------|-----------|")
        for row in by_provider:
            prov, cnt, tot = row
            lines.append(f"| {prov} | {cnt} | {tot:,} |")
        lines.append("")

    # By session
    if by_session:
        lines.append("## 按 Session 统计 (Top 10)")
        lines.append("")
        lines.append("| Session | 请求数 | Input | Output | 总计 |")
        lines.append("|---------|--------|-------|--------|------|")
        for row in by_session:
            sid, cnt, inp, out, tot = row
            short_sid = sid[:16] + "..." if len(sid) > 20 else sid
            lines.append(f"| {short_sid} | {cnt} | {inp:,} | {out:,} | {tot:,} |")
        lines.append("")

    # Hourly
    if by_hour:
        lines.append("## 小时级分布")
        lines.append("")
        lines.append("| 时段 | 请求数 | Tokens |")
        lines.append("|------|--------|--------|")
        for row in by_hour:
            hour, cnt, tot = row
            lines.append(f"| {hour}:00 | {cnt} | {tot:,} |")
        lines.append("")

    lines.append("---")
    lines.append(f"*由 token-consumption-tracker 生成于 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    lines.append("")

    return "\n".join(lines)


def save_report_to_file(date_str: str | None = None) -> str:
    """Generate and save a daily report.

    Returns the file path of the saved report.
    """
    if date_str is None:
        date_str = (
            datetime.datetime.now() - datetime.timedelta(days=1)
        ).strftime("%Y-%m-%d")

    report = generate_report(date_str)
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = _REPORT_DIR / f"{date_str}.md"
    report_path.write_text(report, encoding="utf-8")
    return str(report_path)


# ---- plugin entry point -----------------------------------------------------


def register(ctx: Any) -> None:
    """Register the post_api_request hook for token tracking."""
    _init_db()

    try:
        _log_path = _HERMES_PERSONAL / "logs" / "token-consumption-tracker.log"
        _log_path.parent.mkdir(parents=True, exist_ok=True)
        # Don't configure root logger — just use the module logger
        logger.info("token-consumption-tracker: plugin loaded, DB at %s", _DB_PATH)
    except Exception:
        pass

    ctx.register_hook("post_api_request", _on_post_api_request)
    ctx.register_hook("on_session_end", _on_session_end)
