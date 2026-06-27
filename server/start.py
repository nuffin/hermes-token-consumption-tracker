#!/usr/bin/env python3
"""Start the token usage web dashboard.

Usage:
    python3 server/start.py                   # default port 9090
    python3 server/start.py --port 8080
    TOKEN_SERVER_PORT=8080 python3 server/start.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_HERE = Path(__file__).parent.resolve()
_SERVER_PY = _HERE / "server.py"


def main() -> None:
    if not _SERVER_PY.exists():
        print(f"Error: {_SERVER_PY} not found", file=sys.stderr)
        sys.exit(1)

    args = sys.argv[1:]

    # Forward --port flag to server.py
    cmd = [sys.executable, str(_SERVER_PY)] + args

    print(f"Starting token usage web server...")
    print(f"  DB:        {os.environ.get('TOKEN_USAGE_DB', '~/.hermes/token-usage.db')}")
    print(f"  Port:      {os.environ.get('TOKEN_SERVER_PORT', '9090')}")
    print(f"  Dashboard: http://localhost:{os.environ.get('TOKEN_SERVER_PORT', '9090')}")
    print()

    os.execvp(sys.executable, cmd)


if __name__ == "__main__":
    main()
