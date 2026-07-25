# hermes-token-consumption-tracker

A Hermes Agent plugin that tracks token consumption per API request and
generates daily usage reports.

## Installation

### Via symlink (recommended for development)

```bash
ln -sf $(pwd) ~/.hermes/plugins/token-consumption-tracker
```

### Via pip

```bash
pip install hermes-token-consumption-tracker
```

Enable the plugin in your Hermes `config.yaml`:

```yaml
plugins:
  enabled:
    - token-consumption-tracker
```

## Configuration

```yaml
observability:
  default:
    data_dir: ~/.hermes/personal
  token-consumption-tracker:
    data_dir: ~/.hermes/custom   # optional override
```

Priority: `TOKEN_CONSUMPTION_DATA_DIR` env var → profile config →
global config (`~/.hermes/config.yaml`) → `~/.hermes`.

## Usage

In-session slash commands:

- `/token list` — list saved daily reports
- `/token show [date]` — generate and print a report (default: today)
- `/token save [date]` — generate and save to file
- `/token status` — database path, size, record count

Standalone scripts:

```bash
cd ~/.hermes/plugins/token-consumption-tracker
python3 scripts/report.py              # yesterday's report
python3 scripts/report.py --today      # today's report
python3 scripts/query.py latest 10     # last 10 API calls
python3 scripts/query.py summary --today
```

## License

MIT


## Repositories

| Role | Repo | PyPI |
|------|------|------|
| Plugin code (this repo) | `hermes-token-consumption-tracker` | — |
| Pip wrapper | `hermes-token-consumption-tracker-pip` | `hermes-token-consumption-tracker` |
