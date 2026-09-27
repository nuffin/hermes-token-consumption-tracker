"""Regression tests for token-consumption-tracker lifecycle flushing."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def _load_plugin():
    spec = importlib.util.spec_from_file_location("token_tracker_test_module", PLUGIN_ROOT / "__init__.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Context:
    def __init__(self):
        self.hooks = {}
        self.commands = {}

    def register_hook(self, name, handler):
        self.hooks[name] = handler

    def register_command(self, **kwargs):
        self.commands[kwargs["name"]] = kwargs


def test_finalize_hook_flushes_queued_usage_to_isolated_database(tmp_path):
    tracker = _load_plugin()
    old_db_path = tracker._DB_PATH
    old_report_dir = tracker._REPORT_DIR
    old_queue = tracker._queue
    old_timer = tracker._flush_timer
    try:
        setattr(tracker, "_DB_PATH", tmp_path / "token-usage.db")
        setattr(tracker, "_REPORT_DIR", tmp_path / "reports")
        setattr(tracker, "_queue", [])
        setattr(tracker, "_flush_timer", None)

        ctx = _Context()
        tracker.register(ctx)
        assert "post_api_request" in ctx.hooks
        assert "on_session_end" in ctx.hooks
        assert "on_session_finalize" in ctx.hooks

        ctx.hooks["post_api_request"](
            session_id="s-finalize",
            turn_id="t-1",
            api_request_id="r-1",
            model="local-test-model",
            provider="custom",
            usage={"input_tokens": 7, "output_tokens": 3, "prompt_tokens": 7, "total_tokens": 10},
        )
        assert tracker._queue

        ctx.hooks["on_session_finalize"](session_id="s-finalize", platform="cli")

        import sqlite3

        with sqlite3.connect(tracker._DB_PATH) as conn:
            row = conn.execute(
                "SELECT session_id, model, provider, prompt_tokens, completion_tokens, total_tokens, raw_usage "
                "FROM token_usage"
            ).fetchone()
        assert row[:6] == ("s-finalize", "local-test-model", "custom", 7, 3, 10)
        assert json.loads(row[6])["output_tokens"] == 3
    finally:
        tracker.flush_now()
        setattr(tracker, "_DB_PATH", old_db_path)
        setattr(tracker, "_REPORT_DIR", old_report_dir)
        setattr(tracker, "_queue", old_queue)
        setattr(tracker, "_flush_timer", old_timer)
