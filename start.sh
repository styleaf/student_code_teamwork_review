#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

if command -v python3 >/dev/null 2>&1; then
  exec python3 server.py --port 8765 --open
fi

if command -v python >/dev/null 2>&1; then
  exec python server.py --port 8765 --open
fi

echo "Python 3 was not found. Install Python 3 and run this script again." >&2
exit 1
