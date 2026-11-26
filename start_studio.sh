#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
echo "Launching SchemForge Interactive Inspector Studio at http://127.0.0.1:8765 ..."
PYTHONPATH=src .venv/bin/python -m schemforge.cli serve --host 127.0.0.1 --port 8765
