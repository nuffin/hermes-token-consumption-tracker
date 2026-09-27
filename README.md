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
- `/token week [date] [--offset N] [--mono] [--width N]` — weekly report
  (charts + summary; Monday-start weeks)
- `/token status` — database path, size, record count

Standalone scripts:

```bash
cd ~/.hermes/plugins/token-consumption-tracker
python3 scripts/report.py              # yesterday's report
python3 scripts/report.py --today      # today's report
python3 scripts/query.py latest 10     # last 10 API calls
python3 scripts/query.py summary --today
python3 scripts/query.py week          # weekly report: charts + summary
python3 scripts/query.py week --offset 1        # previous week
python3 scripts/query.py week 2026-09-23        # week containing that date
python3 scripts/query.py week --mono --width 30 # grayscale, narrower bars
```

### Weekly report

`week` renders (Monday-start weeks):

1. Daily stacked bar chart — each bar is one day, stacked into
   cached (blue `█`) / new input (amber `▓`) / output (green `░`)
   using 24-bit ANSI truecolor. `--mono` switches to grayscale.
2. Grouped chart by day × model — one bar per model per day,
   blank line between days.
3. Weekly summary block — same layout as the daily summary
   (Requests, Input New/Total, Cache Read/Write, Output, Total, averages).
4. By-model and by-workspace tables for the whole week.

Legend format per row: `TOTAL (req / cached / new input / output)`.

## License

MIT


## Repositories

| Role | Repo | PyPI |
|------|------|------|
| Plugin code (this repo) | [hermes-token-consumption-tracker](https://github.com/nuffin/hermes-token-consumption-tracker) | — |
| Pip wrapper | [hermes-token-consumption-tracker-pip](https://github.com/nuffin/hermes-token-consumption-tracker-pip) | [hermes-token-consumption-tracker](https://pypi.org/project/hermes-token-consumption-tracker/) |
