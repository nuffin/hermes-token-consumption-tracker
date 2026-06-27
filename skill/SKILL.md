---
name: token-consumption-query
description: Query, filter, delete, and export token consumption data from the
  token-usage DB written by token-consumption-tracker plugin.
version: 1.0.0
category: hermes
tags:
- hermes
- token
- query
- report
---

# Token Consumption Query

Load this skill when the user asks about token consumption — daily usage,
latest requests, by model, etc.

Data source: `token-consumption-tracker` Hermes plugin → `token-usage.db`
(default `~/.hermes/token-usage.db`).  The query scripts (`scripts/query.py`)
automatically resolve the DB path from the same `observability.data_dir`
config key.

For a Web dashboard, see the `server/` subdirectory — load the
`token-consumption-web-server` skill via `skill_load("token-consumption-web-server")`.

## Query Scripts

```bash
python3 scripts/query.py latest [N]          # most recent N records (default 10)
python3 scripts/query.py session <prefix>     # by session ID prefix
python3 scripts/query.py model <name>         # by model name
python3 scripts/query.py date <from> [to]     # by date range (YYYY-MM-DD)
python3 scripts/query.py summary [--today|<date>]  # daily summary
python3 scripts/query.py raw <N>              # raw_usage JSON for recent records
python3 scripts/query.py raw --id <id>        # raw_usage for a specific record
python3 scripts/query.py delete --session ... # delete records (with confirmation)
python3 scripts/query.py delete --before <date>
python3 scripts/query.py delete --id <id>
python3 scripts/query.py export [--after <date>] [--all]  # export JSONL
```

## Daily Report

```bash
python3 scripts/report.py                     # yesterday
python3 scripts/report.py --today             # today so far
python3 scripts/report.py 2026-06-17          # specific date
```

## DB Schema

```sql
token_usage (
    id               INTEGER PRIMARY KEY,
    session_id       TEXT NOT NULL,
    turn_id          TEXT,
    api_request_id   TEXT,
    model            TEXT NOT NULL,
    provider         TEXT NOT NULL,
    profile          TEXT DEFAULT '',
    prompt_tokens    INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_write_tokens INTEGER DEFAULT 0,
    workspace        TEXT DEFAULT '',
    worker           TEXT DEFAULT '',
    total_tokens     INTEGER DEFAULT 0,
    api_duration     REAL DEFAULT 0.0,
    finish_reason    TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    raw_usage        TEXT
)
```

## Pitfalls

- `completion_tokens` maps to the provider's `output_tokens`, not the field name.
- `cache_read_tokens` is separate from `prompt_tokens` — don't lump.
- Old records may have `NULL` in columns added by ALTER TABLE — query scripts
  handle this with `COALESCE` / `or 0`.
