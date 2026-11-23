#!/usr/bin/env bash
# Start Parlera and open it in your browser.   ./run.sh [--port 8642] [--no-browser]
#
# - Starts Ollama if it isn't running yet.
# - When you quit Parlera (Ctrl+C or close the Terminal window) the model is unloaded from
#   memory, and Ollama is quit again if Parlera started it. If Ollama was already running
#   before, it is left running. Set PARLERA_QUIT_OLLAMA=0 to never quit Ollama.
set -euo pipefail
cd "$(dirname "$0")"

# Where your data lives (written by setup.sh). Default: ~/Parlera
if [[ -f parlera.env ]]; then set -a; source parlera.env; set +a; fi

if [[ ! -x .venv/bin/python ]]; then
  echo "Parlera isn't set up yet — running ./setup.sh first."; ./setup.sh
fi

OLLAMA_URL="http://127.0.0.1:11434/api/tags"
STARTED_OLLAMA=""
OLLAMA_PID=""
if command -v ollama >/dev/null 2>&1 || [[ -d /Applications/Ollama.app ]]; then
  if ! curl -s -o /dev/null "$OLLAMA_URL"; then
    echo "Starting Ollama…"
    if open -g -a Ollama 2>/dev/null; then
      STARTED_OLLAMA="app"
    else
      ollama serve >/dev/null 2>&1 &
      OLLAMA_PID=$!
      STARTED_OLLAMA="serve"
    fi
    for _ in $(seq 1 30); do curl -s -o /dev/null "$OLLAMA_URL" && break; sleep 0.5; done
  fi
fi

cleanup() {
  if [[ "${PARLERA_QUIT_OLLAMA:-1}" == "1" ]]; then
    case "$STARTED_OLLAMA" in
      app) osascript -e 'quit app "Ollama"' >/dev/null 2>&1 || true ;;
      serve) kill "$OLLAMA_PID" >/dev/null 2>&1 || true ;;
    esac
  fi
}
trap cleanup EXIT

.venv/bin/python -m parlera "$@"
