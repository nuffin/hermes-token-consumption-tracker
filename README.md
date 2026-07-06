# hermes-token-consumption-tracker

Hermes Agent plugin — track token consumption per API request.

Records usage (prompt/completion/total tokens, model, provider, cache stats,
duration) to a local SQLite database on every `post_api_request` hook.

## Install

Symlink into your Hermes plugins directory:

```bash
ln -s "$PWD" ~/.hermes/plugins/token-consumption-tracker
```

Or into a specific profile's plugins:

```bash
ln -s "$PWD" ~/.hermes/profiles/<profile>/plugins/token-consumption-tracker
```

Then enable in `config.yaml`:

```yaml
plugins:
  enabled:
    - token-consumption-tracker
```

## Configuration

```yaml
observability:
  default:
    data_dir: ~/.hermes/personal   # shared data dir for all observability plugins
  token-consumption-tracker:
    data_dir: ~/.hermes/custom     # plugin-specific override (optional)
```

Priority: `TOKEN_CONSUMPTION_DATA_DIR` env var → profile config → global
config (`~/.hermes/config.yaml`) → `~/.hermes`.

## Usage

### Slash commands (in-session)

- `/token list` — list saved daily reports
- `/token show [yesterday|2026-06-17]` — generate & print report (default today)
- `/token save [yesterday|2026-06-17]` — generate & save to file
- `/token status` — DB location, size, record count

### Standalone scripts

```bash
# Daily report
python3 scripts/report.py                 # yesterday
python3 scripts/report.py --today         # today so far

# Query DB
python3 scripts/query.py latest 10
python3 scripts/query.py summary --today
python3 scripts/query.py model deepseek-v4-flash

# Web dashboard
python3 server/server.py
```

### Cron (daily report)

```bash
hermes cron create \
  --name token-usage-daily-report \
  --schedule "0 0 * * *" \
  --script "$PWD/scripts/report.py" \
  --no-agent
```

## Data

| Path | Content |
|------|---------|
| `<data_dir>/token-usage.db` | SQLite database of all API requests |
| `<data_dir>/token-usage/` | Daily markdown reports |

## Schema

```sql
token_usage (
    id               INTEGER PRIMARY KEY,
    session_id       TEXT NOT NULL,
    model            TEXT NOT NULL,
    provider         TEXT NOT NULL,
    prompt_tokens    INTEGER,
    completion_tokens INTEGER,
    total_tokens     INTEGER,
    cache_read_tokens  INTEGER,
    cache_write_tokens INTEGER,
    api_duration     REAL,
    finish_reason    TEXT,
    profile          TEXT,
    workspace        TEXT,
    worker           TEXT,
    created_at       TEXT NOT NULL,
    raw_usage        TEXT
)
```
