#!/usr/bin/env bash
# Start Parlera and open it in your browser.   ./run.sh [--port 8642] [--no-browser]
#
# - Starts Ollama if it isn't running yet: headless (`ollama serve`, no window) unless
#   Settings → Starting & quitting → Start Ollama is set to "the Ollama app".
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
setting() {  # read a Parlera setting (falls back to $2)
  .venv/bin/python -c "from parlera.config import Paths, Settings; print(Settings(Paths().settings).get('$1', '$2'))" 2>/dev/null || echo "$2"
}
# The Ollama server binary: the CLI if installed, otherwise the one inside the Ollama app
OLLAMA_BIN="$(command -v ollama 2>/dev/null || true)"
for cand in /Applications/Ollama.app/Contents/Resources/ollama "$HOME/Applications/Ollama.app/Contents/Resources/ollama"; do
  [[ -z "$OLLAMA_BIN" && -x "$cand" ]] && OLLAMA_BIN="$cand"
done
if [[ -n "$OLLAMA_BIN" || -d /Applications/Ollama.app ]]; then
  if ! curl -s -o /dev/null "$OLLAMA_URL"; then
    # Settings → Starting & quitting → "Start Ollama": headless (no window, default) | app (the Ollama app)
    mode="$(setting app.ollama_start headless)"
    if [[ "$mode" != "app" && -n "$OLLAMA_BIN" ]]; then
      echo "Starting Ollama in the background (no window)…"
      LOGDIR="${PARLERA_DATA:-$HOME/Parlera}/logs"; mkdir -p "$LOGDIR"
      "$OLLAMA_BIN" serve >"$LOGDIR/ollama.log" 2>&1 &
      OLLAMA_PID=$!
      STARTED_OLLAMA="serve"
    elif open -g -j -a Ollama 2>/dev/null; then   # -g: don't bring it to the front, -j: launch hidden
      echo "Starting the Ollama app…"
      STARTED_OLLAMA="app"
    fi
    for _ in $(seq 1 40); do curl -s -o /dev/null "$OLLAMA_URL" && break; sleep 0.5; done
  fi
fi

cleanup() {
  # Settings → General → "Quit Ollama when Parlera stops": never | if_started | always ("always" is handled by the server)
  local mode
  mode="$(setting app.quit_ollama if_started)"
  [[ "$mode" == "never" ]] && return
  if [[ "${PARLERA_QUIT_OLLAMA:-1}" == "1" ]]; then
    case "$STARTED_OLLAMA" in
      app) osascript -e 'quit app "Ollama"' >/dev/null 2>&1 || true ;;
      serve) kill "$OLLAMA_PID" >/dev/null 2>&1 || true ;;
    esac
  fi
}
trap cleanup EXIT

.venv/bin/python -m parlera "$@"
