---
name: token-consumption-web-server
description: Start the token consumption web dashboard. Serves real-time token usage
  data via HTTP API + static HTML dashboard at localhost:9090.
version: 1.0.0
category: hermes
tags:
- hermes
- token
- web
- dashboard
---

# Token Consumption Web Dashboard

Start the web UI for browsing token usage data recorded by the
`token-consumption-tracker` Hermes plugin.

## Quick Start

```bash
python3 server/server.py [--port 9090]
```

## Configuration

| Env Variable | Default | Description |
|---|---|---|
| `TOKEN_USAGE_DB` | `~/.hermes/token-usage.db` | Path to the token-usage SQLite DB |
| `TOKEN_SERVER_PORT` | `9090` | HTTP server port |

## API Endpoints

| Endpoint | Description |
|---|---|
| `/api/overview` | Total stats |
| `/api/summary/today` | Today aggregated by model |
| `/api/summary/yesterday` | Yesterday |
| `/api/summary/week` | Last 7 days |
| `/api/hourly?date=` | Hourly distribution for a date |
| `/api/models` | Stats grouped by model |
| `/api/sessions?limit=` | Stats grouped by session |
| `/api/latest?n=` | Latest N raw records |
| `/api/records?page=&per_page=` | Paginated record browser |
| `/api/raw?id= or ?n=` | Raw usage JSON |

## Data Source

Data comes from the `token-consumption-tracker` Hermes plugin, which writes to
the SQLite DB at the path configured via `observability.data_dir` in Hermes
config.yaml.  The web server reads the same DB — run the plugin first, then
start the dashboard.

## Installation

```bash
pip install -r requirements.txt   # empty — zero deps, pure Python stdlib
```

## Pitfalls

- Server uses Python stdlib `http.server` — no uvicorn / FastAPI needed.
- The DB must exist before the server starts (the tracker plugin creates it).
