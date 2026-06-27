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
