#!/usr/bin/env bash
# Start Parlera and open it in your browser.   ./run.sh [--port 8642] [--no-browser]
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo "Parlera isn't set up yet — running ./setup.sh first."; ./setup.sh
fi
if command -v ollama >/dev/null 2>&1 && ! curl -s -o /dev/null http://127.0.0.1:11434/api/tags; then
  echo "Starting Ollama…"; (open -a Ollama 2>/dev/null || (ollama serve >/dev/null 2>&1 &)); sleep 3
fi
exec .venv/bin/python -m parlera "$@"
