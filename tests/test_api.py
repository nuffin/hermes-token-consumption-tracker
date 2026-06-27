#!/usr/bin/env python3
"""Tests for token-usage-web-server API endpoints.

Usage:
    python3 tests/test_api.py
    python3 -m pytest tests/
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

# Add server dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

PORT = 9099
BASE = f"http://localhost:{PORT}"

# Use a test DB if needed, but for now use the real one
os.environ["TOKEN_SERVER_PORT"] = str(PORT)


def setup_module():
    """Start the server in a background thread."""
    from server import main as _server_main
    # We can't easily call main() because it blocks.
    # Instead, use HTTPServer directly.
    from http.server import HTTPServer
    from server import Handler

    global _server
    _server = HTTPServer(("0.0.0.0", PORT), Handler)
    t = threading.Thread(target=_server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.5)


def teardown_module():
    _server.shutdown()


def _get(path):
    """GET and return parsed JSON or status."""
    try:
        r = urllib.request.urlopen(f"{BASE}{path}")
        return {"status": r.status, "data": json.loads(r.read())}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "data": json.loads(e.read())}


def test_overview():
    res = _get("/api/overview")
    assert res["status"] == 200, f"Expected 200, got {res}"
    d = res["data"]
    assert "total_requests" in d
    assert "total_tokens" in d
    assert d["total_requests"] > 0


def test_summary_today():
    res = _get("/api/summary?date=today")
    assert res["status"] == 200, f"Expected 200, got {res}"
    d = res["data"]
    assert "requests" in d
    assert "by_model" in d
    assert d["requests"] > 0


def test_summary_yesterday():
    res = _get("/api/summary?date=yesterday")
    assert res["status"] == 200
    d = res["data"]
    assert "requests" in d


def test_summary_this_week():
    res = _get("/api/summary?date=this-week")
    assert res["status"] == 200
    d = res["data"]
    assert "requests" in d


def test_summary_specific_date():
    res = _get("/api/summary?date=2026-06-17")
    assert res["status"] == 200
    d = res["data"]
    assert "requests" in d


def test_hourly():
    res = _get("/api/hourly")
    assert res["status"] == 200
    assert len(res["data"]) == 24  # Always 24 slots


def test_hourly_with_date():
    res = _get("/api/hourly?date=2026-06-17")
    assert res["status"] == 200
    assert len(res["data"]) == 24


def test_by_model():
    res = _get("/api/by-model")
    assert res["status"] == 200
    assert len(res["data"]) > 0
    assert "model" in res["data"][0]


def test_by_session():
    res = _get("/api/by-session?limit=5")
    assert res["status"] == 200
    assert len(res["data"]) <= 5


def test_latest():
    res = _get("/api/latest?limit=3")
    assert res["status"] == 200
    assert len(res["data"]["records"]) == 3


def test_list():
    res = _get("/api/list?page=1&per_page=10")
    assert res["status"] == 200
    d = res["data"]
    assert "records" in d
    assert "total" in d
    assert "page" in d
    assert len(d["records"]) <= 10


def test_list_page_2():
    res = _get("/api/list?page=2&per_page=5")
    assert res["status"] == 200
    assert res["data"]["page"] == 2


def test_raw_usage():
    # First get a valid ID from latest
    res = _get("/api/latest?limit=1")
    if not res["data"]["records"]:
        return  # skip if no data
    valid_id = res["data"]["records"][0]["id"]
    res = _get(f"/api/raw-usage?id={valid_id}")
    assert res["status"] == 200
    d = res["data"]
    assert "raw_usage" in d


def test_raw_usage_not_found():
    res = _get("/api/raw-usage?id=99999999")
    assert res["status"] == 404


def test_404():
    res = _get("/api/nonexistent")
    assert res["status"] == 404


def test_index_html():
    try:
        r = urllib.request.urlopen(f"{BASE}/")
        html = r.read()
        assert len(html) > 100
        assert b"Token Usage" in html
    except urllib.error.HTTPError as e:
        assert False, f"Index returned {e.code}"


if __name__ == "__main__":
    setup_module()
    passed = 0
    failed = 0
    tests = [
        test_overview,
        test_summary_today,
        test_summary_yesterday,
        test_summary_this_week,
        test_summary_specific_date,
        test_hourly,
        test_hourly_with_date,
        test_by_model,
        test_by_session,
        test_latest,
        test_list,
        test_list_page_2,
        test_raw_usage,
        test_raw_usage_not_found,
        test_404,
        test_index_html,
    ]
    for t in tests:
        try:
            t()
            print(f"  ✅ {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ❌ {t.__name__}: {e}")
            failed += 1
    teardown_module()
    print(f"\n{passed}/{passed+failed} passed")
    sys.exit(0 if failed == 0 else 1)
