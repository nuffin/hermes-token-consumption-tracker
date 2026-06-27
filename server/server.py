#!/usr/bin/env python3
"""Token Usage Web Server — HTTP API + static file server.

Provides 8 API endpoints + serves index.html dashboard.

Usage:
    python3 server.py [--port 9090]
    TOKEN_SERVER_PORT=9090 python3 server.py
"""

from __future__ import annotations

import json
import mimetypes
import os
import sqlite3
import sys
import urllib.parse
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

_HERE = Path(__file__).parent.resolve()
DB_PATH = os.environ.get("TOKEN_USAGE_DB",
                         str(Path.home() / ".hermes" / "token-usage.db"))
PORT = int(os.environ.get("TOKEN_SERVER_PORT", "9090"))
STATIC_DIR = str(_HERE)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ─── API handlers ──────────────────────────────────────────────────────────


def api_overview(query_params: dict = None) -> dict:
    """Overall statistics."""
    conn = _conn()
    c = conn.execute("SELECT COUNT(*) as cnt FROM token_usage")
    total_requests = c.fetchone()["cnt"]

    c = conn.execute("SELECT COUNT(DISTINCT model) as cnt FROM token_usage")
    total_models = c.fetchone()["cnt"]

    c = conn.execute("SELECT COUNT(DISTINCT session_id) as cnt FROM token_usage")
    total_sessions = c.fetchone()["cnt"]

    c = conn.execute(
        "SELECT COALESCE(SUM(prompt_tokens),0) as inp, "
        "COALESCE(SUM(completion_tokens),0) as out, "
        "COALESCE(SUM(total_tokens),0) as tot, "
        "COALESCE(SUM(cache_read_tokens),0) as cr, "
        "COALESCE(SUM(cache_write_tokens),0) as cw "
        "FROM token_usage"
    )
    row = c.fetchone()
    conn.close()

    return {
        "total_requests": total_requests,
        "total_models": total_models,
        "total_sessions": total_sessions,
        "total_input_tokens": row["inp"],
        "total_output_tokens": row["out"],
        "total_tokens": row["tot"],
        "total_cache_read": row["cr"],
        "total_cache_write": row["cw"],
    }


def api_summary(query_params: dict) -> dict:
    """Today / yesterday / this-week summary."""
    raw_date = query_params.get("date", "today")

    if raw_date == "today":
        date_str = datetime.now().strftime("%Y-%m-%d")
    elif raw_date == "yesterday":
        date_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    elif raw_date == "this-week":
        today = datetime.now()
        monday = today - timedelta(days=today.weekday())
        date_from = monday.strftime("%Y-%m-%d")
        date_to = today.strftime("%Y-%m-%d")
        return _summary_range(date_from, date_to, f"Week starting {monday.strftime('%Y-%m-%d')}")
    else:
        date_str = raw_date  # YYYY-MM-DD

    conn = _conn()
    c = conn.execute(
        "SELECT COUNT(*) as cnt, "
        "COALESCE(SUM(prompt_tokens),0) as inp, "
        "COALESCE(SUM(completion_tokens),0) as out, "
        "COALESCE(SUM(total_tokens),0) as tot, "
        "COALESCE(SUM(cache_read_tokens),0) as cr, "
        "COALESCE(SUM(cache_write_tokens),0) as cw "
        "FROM token_usage WHERE created_at >= ? AND created_at < ?",
        (f"{date_str} 00:00:00", f"{date_str} 23:59:59"),
    )
    row = c.fetchone()

    # by model
    c = conn.execute(
        "SELECT model, COUNT(*) as requests, "
        "COALESCE(SUM(prompt_tokens),0) as input_tokens, "
        "COALESCE(SUM(completion_tokens),0) as output_tokens, "
        "COALESCE(SUM(total_tokens),0) as total_tokens, "
        "COALESCE(SUM(cache_read_tokens),0) as cache_read, "
        "COALESCE(SUM(cache_write_tokens),0) as cache_write, "
        "ROUND(AVG(api_duration),2) as avg_duration "
        "FROM token_usage WHERE created_at >= ? AND created_at < ? "
        "GROUP BY model ORDER BY total_tokens DESC",
        (f"{date_str} 00:00:00", f"{date_str} 23:59:59"),
    )
    by_model = [dict(r) for r in c.fetchall()]

    # by workspace
    c = conn.execute(
        "SELECT workspace, COUNT(*) as requests, "
        "COALESCE(SUM(prompt_tokens),0) as input_tokens, "
        "COALESCE(SUM(completion_tokens),0) as output_tokens, "
        "COALESCE(SUM(total_tokens),0) as total_tokens "
        "FROM token_usage WHERE created_at >= ? AND created_at < ? "
        "GROUP BY workspace ORDER BY total_tokens DESC",
        (f"{date_str} 00:00:00", f"{date_str} 23:59:59"),
    )
    by_workspace = [dict(r) for r in c.fetchall()]

    conn.close()

    return {
        "date": date_str,
        "label": f"{date_str}",
        "requests": row["cnt"],
        "input_tokens": row["inp"],
        "output_tokens": row["out"],
        "total_tokens": row["tot"],
        "cache_read": row["cr"],
        "cache_write": row["cw"],
        "by_model": by_model,
        "by_workspace": by_workspace,
    }


def _summary_range(date_from: str, date_to: str, label: str) -> dict:
    conn = _conn()
    c = conn.execute(
        "SELECT COUNT(*) as cnt, "
        "COALESCE(SUM(prompt_tokens),0) as inp, "
        "COALESCE(SUM(completion_tokens),0) as out, "
        "COALESCE(SUM(total_tokens),0) as tot, "
        "COALESCE(SUM(cache_read_tokens),0) as cr, "
        "COALESCE(SUM(cache_write_tokens),0) as cw "
        "FROM token_usage WHERE created_at >= ? AND created_at <= ?",
        (f"{date_from} 00:00:00", f"{date_to} 23:59:59"),
    )
    row = c.fetchone()

    c = conn.execute(
        "SELECT model, COUNT(*) as requests, "
        "COALESCE(SUM(prompt_tokens),0) as input_tokens, "
        "COALESCE(SUM(completion_tokens),0) as output_tokens, "
        "COALESCE(SUM(total_tokens),0) as total_tokens, "
        "COALESCE(SUM(cache_read_tokens),0) as cache_read, "
        "COALESCE(SUM(cache_write_tokens),0) as cache_write "
        "FROM token_usage WHERE created_at >= ? AND created_at <= ? "
        "GROUP BY model ORDER BY total_tokens DESC",
        (f"{date_from} 00:00:00", f"{date_to} 23:59:59"),
    )
    by_model = [dict(r) for r in c.fetchall()]

    conn.close()
    return {
        "date": f"{date_from}_to_{date_to}",
        "label": label,
        "requests": row["cnt"],
        "input_tokens": row["inp"],
        "output_tokens": row["out"],
        "total_tokens": row["tot"],
        "cache_read": row["cr"],
        "cache_write": row["cw"],
        "by_model": by_model,
        "by_workspace": [],
    }


def api_hourly(query_params: dict) -> list:
    """24h hourly distribution."""
    raw_date = query_params.get("date", datetime.now().strftime("%Y-%m-%d"))
    conn = _conn()
    c = conn.execute(
        "SELECT CAST(strftime('%H',created_at) AS INTEGER) as hour, "
        "COUNT(*) as requests, "
        "COALESCE(SUM(prompt_tokens),0) as input_tokens, "
        "COALESCE(SUM(completion_tokens),0) as output_tokens, "
        "COALESCE(SUM(total_tokens),0) as total_tokens "
        "FROM token_usage WHERE created_at >= ? AND created_at < ? "
        "GROUP BY hour ORDER BY hour",
        (f"{raw_date} 00:00:00", f"{raw_date} 23:59:59"),
    )
    rows = c.fetchall()
    conn.close()

    # Pad to 24 slots
    by_hour = {r["hour"]: dict(r) for r in rows}
    result = []
    for h in range(24):
        if h in by_hour:
            result.append(by_hour[h])
        else:
            result.append({"hour": h, "requests": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
    return result


def api_by_model(query_params: dict) -> list:
    """All-time model statistics."""
    raw_date = query_params.get("date")
    conn = _conn()
    if raw_date:
        c = conn.execute(
            "SELECT model, COUNT(*) as requests, "
            "COALESCE(SUM(prompt_tokens),0) as input_tokens, "
            "COALESCE(SUM(completion_tokens),0) as output_tokens, "
            "COALESCE(SUM(total_tokens),0) as total_tokens, "
            "COALESCE(SUM(cache_read_tokens),0) as cache_read, "
            "COALESCE(SUM(cache_write_tokens),0) as cache_write, "
            "ROUND(AVG(api_duration),2) as avg_duration "
            "FROM token_usage WHERE created_at >= ? AND created_at < ? "
            "GROUP BY model ORDER BY total_tokens DESC",
            (f"{raw_date} 00:00:00", f"{raw_date} 23:59:59"),
        )
    else:
        c = conn.execute(
            "SELECT model, COUNT(*) as requests, "
            "COALESCE(SUM(prompt_tokens),0) as input_tokens, "
            "COALESCE(SUM(completion_tokens),0) as output_tokens, "
            "COALESCE(SUM(total_tokens),0) as total_tokens, "
            "COALESCE(SUM(cache_read_tokens),0) as cache_read, "
            "COALESCE(SUM(cache_write_tokens),0) as cache_write, "
            "ROUND(AVG(api_duration),2) as avg_duration "
            "FROM token_usage GROUP BY model ORDER BY total_tokens DESC"
        )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def api_by_session(query_params: dict) -> list:
    """Session ranking."""
    limit = int(query_params.get("limit", 10))
    conn = _conn()
    c = conn.execute(
        "SELECT session_id, COUNT(*) as requests, "
        "COALESCE(SUM(prompt_tokens),0) as input_tokens, "
        "COALESCE(SUM(completion_tokens),0) as output_tokens, "
        "COALESCE(SUM(total_tokens),0) as total_tokens, "
        "MIN(created_at) as first_seen, MAX(created_at) as last_seen "
        "FROM token_usage GROUP BY session_id "
        "ORDER BY total_tokens DESC LIMIT ?",
        (limit,),
    )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def api_latest(query_params: dict) -> dict:
    """Latest N records with pagination info."""
    limit = int(query_params.get("limit", 50))
    conn = _conn()
    c = conn.execute(
        "SELECT id, session_id, turn_id, model, provider, "
        "prompt_tokens, completion_tokens, total_tokens, "
        "cache_read_tokens, cache_write_tokens, "
        "api_duration, finish_reason, created_at, "
        "workspace, worker, api_request_id, raw_usage "
        "FROM token_usage ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return {"records": rows, "count": len(rows)}


def api_list(query_params: dict) -> dict:
    """Paginated all records."""
    page = int(query_params.get("page", 1))
    per_page = int(query_params.get("per_page", 50))
    offset = (page - 1) * per_page

    conn = _conn()
    c = conn.execute("SELECT COUNT(*) as cnt FROM token_usage")
    total = c.fetchone()["cnt"]

    c = conn.execute(
        "SELECT id, session_id, turn_id, model, provider, "
        "prompt_tokens, completion_tokens, total_tokens, "
        "cache_read_tokens, cache_write_tokens, "
        "api_duration, finish_reason, created_at, "
        "workspace, worker, api_request_id, raw_usage "
        "FROM token_usage ORDER BY id DESC LIMIT ? OFFSET ?",
        (per_page, offset),
    )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()

    return {
        "records": rows,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": max(1, (total + per_page - 1) // per_page),
    }


def api_raw_usage(query_params: dict) -> dict | None:
    """Raw usage JSON for a specific ID."""
    id_str = query_params.get("id")
    if not id_str:
        return None
    try:
        record_id = int(id_str)
    except ValueError:
        return None

    conn = _conn()
    c = conn.execute(
        "SELECT id, created_at, model, provider, raw_usage FROM token_usage WHERE id = ?",
        (record_id,),
    )
    row = c.fetchone()
    conn.close()

    if not row:
        return None

    result = dict(row)
    if result.get("raw_usage"):
        try:
            result["raw_usage"] = json.loads(result["raw_usage"])
        except (json.JSONDecodeError, TypeError):
            pass
    return result


# ─── Call Detail (from llm-call-log.db) ─────────────────────────────────────


def api_call_detail(query_params: dict) -> dict | None:
    """Return raw_response from llm-call-log.db for a record's api_request_id."""
    rid = query_params.get("record_id")
    if not rid:
        return None
    try:
        record_id = int(rid)
    except ValueError:
        return None
    
    # Get api_request_id from token-usage.db
    conn = _conn()
    c = conn.execute("SELECT api_request_id, session_id FROM token_usage WHERE id=?", (record_id,))
    row = c.fetchone()
    conn.close()
    if not row or not row["api_request_id"]:
        return None
    
    api_req_id = row["api_request_id"]
    
    # Query llm-call-log.db — try exact match first, then by session_id
    log_db = str(Path.home() / ".hermes" / "personal" / "llm-call-log.db")
    if not os.path.exists(log_db):
        return None
    
    conn2 = sqlite3.connect(log_db)
    conn2.row_factory = sqlite3.Row
    c2 = conn2.execute(
        "SELECT id, api_request_id, turn_id, model, provider, "
        "prompt_tokens, completion_tokens, total_tokens, "
        "cache_read_tokens, cache_write_tokens, "
        "reasoning_tokens, finish_reason, api_duration, "
        "message_count, assistant_content_chars, "
        "assistant_tool_call_count, raw_response, "
        "tool_count, approx_input_tokens, request_char_count, raw_request "
        "FROM llm_api_calls WHERE api_request_id=?",
        (api_req_id,),
    )
    rows = [dict(r) for r in c2.fetchall()]
    
    # Fallback: match by session_id
    if not rows and row["session_id"]:
        c2 = conn2.execute(
            "SELECT id, api_request_id, turn_id, model, provider, "
            "prompt_tokens, completion_tokens, total_tokens, "
            "cache_read_tokens, cache_write_tokens, "
            "reasoning_tokens, finish_reason, api_duration, "
            "message_count, assistant_content_chars, "
            "assistant_tool_call_count, raw_response, "
            "tool_count, approx_input_tokens, request_char_count, raw_request "
            "FROM llm_api_calls WHERE session_id=? ORDER BY id DESC LIMIT 1",
            (row["session_id"],),
        )
        rows = [dict(r) for r in c2.fetchall()]
    conn2.close()
    
    if not rows:
        return None
    
    result = rows[0]
    # Parse JSON string fields
    for field in ["raw_response", "raw_request"]:
        if result.get(field) and isinstance(result[field], str):
            try:
                result[field] = json.loads(result[field])
            except (json.JSONDecodeError, TypeError):
                pass
    return result


_ROUTES = {
    "/api/overview": api_overview,
    "/api/summary": api_summary,
    "/api/hourly": api_hourly,
    "/api/by-model": api_by_model,
    "/api/by-session": api_by_session,
    "/api/latest": api_latest,
    "/api/list": api_list,
    "/api/raw-usage": api_raw_usage,
    "/api/call-detail": api_call_detail,
    # Aliases for frontend compatibility
    "/api/summary/today": lambda q: api_summary({"date": "today"}),
    "/api/summary/yesterday": lambda q: api_summary({"date": "yesterday"}),
    "/api/summary/week": lambda q: api_summary({"date": "this-week"}),
    "/api/models": lambda q: api_by_model(q),
    "/api/sessions": lambda q: api_by_session({"limit": q.get("limit", "20")}),
    "/api/records": lambda q: api_list(q),
    "/api/raw": lambda q: api_raw_usage(q) if q.get("id") else api_latest({"limit": q.get("n", "20")}),
}


class Handler(BaseHTTPRequestHandler):
    """HTTP request handler."""

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"))

    def _send_file(self, path: str):
        if not os.path.isfile(path):
            self._send_json({"error": "Not Found"}, 404)
            return
        mime_type, _ = mimetypes.guess_type(path)
        if mime_type is None:
            mime_type = "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        with open(path, "rb") as f:
            self.wfile.write(f.read())

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        query_params = {k: v[0] if v else "" for k, v in query.items()}

        # API routes
        if path in _ROUTES:
            try:
                result = _ROUTES[path](query_params)
                if result is None:
                    self._send_json({"error": "Not Found"}, 404)
                else:
                    self._send_json(result)
            except Exception as e:
                self._send_json({"error": str(e)}, 500)
            return

        # Static files
        if path == "" or path == "/":
            path = "/index.html"
        file_path = os.path.normpath(os.path.join(STATIC_DIR, path.lstrip("/")))
        # Security: only serve from the static directory
        if not file_path.startswith(STATIC_DIR):
            self._send_json({"error": "Forbidden"}, 403)
            return
        self._send_file(file_path)

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[token-usage-server] {args[0]} {args[1]} {args[2]}\n")


def main():
    os.chdir(STATIC_DIR)
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[token-usage-server] http://localhost:{PORT}")
    print(f"[token-usage-server] DB: {DB_PATH}")
    print("Endpoints:")
    for route in sorted(_ROUTES):
        print(f"  GET {route}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
