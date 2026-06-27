# hermes-token-consumption-tracker

Hermes plugin: track token consumption per API request.

Hooks into `post_api_request` to record per-request token usage (prompt_tokens,
completion_tokens, total_tokens, model, provider, session_id, cache tokens)
into a local SQLite database.

## Data Location

Configured via `observability.data_dir` in Hermes `config.yaml`.
Defaults to `~/.hermes/` (database: `<data_dir>/token-usage.db`).

## Installation

```bash
ln -sf /path/to/hermes-token-consumption-tracker ~/.hermes/plugins/token-consumption-tracker
hermes plugins enable token-consumption-tracker
```

## Query Tools

```bash
python3 scripts/query.py latest 10          # latest 10 records
python3 scripts/query.py summary --today     # today's summary
python3 scripts/query.py model deepseek-v4   # filter by model
python3 scripts/query.py date 2026-06-17     # filter by date
python3 scripts/query.py export --all        # export JSONL
```

## Report Generation

```bash
python3 scripts/report.py              # yesterday
python3 scripts/report.py 2026-06-17   # specific date
python3 scripts/report.py --today      # today so far
```

## Web Dashboard

This repo includes a self-contained web dashboard in `server/`:

```bash
python3 server/server.py
# → http://localhost:9090
```

No external dependencies — pure Python stdlib.  Set `TOKEN_USAGE_DB` env var
to point at a custom DB path, or `TOKEN_SERVER_PORT` for a different port.

See `server/SKILL.md` for API docs and the `token-consumption-web-server`
Hermes skill.

## Related Projects

- **`hermes-token-consumption-tracker`** — Hermes plugin (this repo).
  Both the plugin (`__init__.py`) and the web dashboard (`server/`) live here.
  Install the plugin to record token data, start the dashboard to browse it.
