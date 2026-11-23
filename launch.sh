#!/usr/bin/env bash
# Start Parlera without a Terminal window (used by ~/Applications/Parlera.app).
#
# - Already running? Just open its window.
# - Not set up yet? Open Terminal and run the setup instead (it asks questions).
# - Otherwise start run.sh in the background, logging to <data folder>/logs/parlera.log,
#   and show a message if it doesn't come up.
# For a visible log in Terminal, use ./run.sh or double-click Parlera.command instead.
cd "$(dirname "$0")"
HERE="$(pwd)"
if [[ -f parlera.env ]]; then set -a; source parlera.env; set +a; fi
DATA="${PARLERA_DATA:-$HOME/Parlera}"
PORT="${PARLERA_PORT:-8642}"
URL="http://127.0.0.1:$PORT"

open_window() {
  .venv/bin/python - "$URL" <<'PY' 2>/dev/null || open "$1"
import sys
from parlera.config import Paths, Settings
from parlera.system import open_ui
p = Paths()
open_ui(sys.argv[1], Settings(p.settings).get("app.window", "auto"), p.browser_profile)
PY
}

if [[ ! -x .venv/bin/python ]]; then
  osascript -e "tell application \"Terminal\" to activate" \
            -e "tell application \"Terminal\" to do script \"cd \" & quoted form of \"$HERE\" & \" && ./run.sh\"" >/dev/null
  exit 0
fi

if curl -s -o /dev/null --max-time 2 "$URL/api/status"; then
  open_window "$URL"
  exit 0
fi

mkdir -p "$DATA/logs"
LOG="$DATA/logs/parlera.log"
[[ -f "$LOG" ]] && mv -f "$LOG" "$DATA/logs/parlera.previous.log"
nohup ./run.sh --port "$PORT" >"$LOG" 2>&1 </dev/null &

for _ in $(seq 1 90); do
  curl -s -o /dev/null --max-time 1 "$URL/api/status" && exit 0   # the server opens its own window
  sleep 0.5
done

choice="$(osascript -e "display dialog \"Parlera didn't start within 45 seconds. The log may show why.\" with title \"Parlera\" buttons {\"Close\", \"Open log\", \"Start in Terminal\"} default button \"Open log\" with icon caution" -e 'button returned of result' 2>/dev/null || true)"
case "$choice" in
  "Open log") open -a Console "$LOG" 2>/dev/null || open "$LOG" ;;
  "Start in Terminal") osascript -e "tell application \"Terminal\" to activate" \
       -e "tell application \"Terminal\" to do script \"cd \" & quoted form of \"$HERE\" & \" && ./run.sh\"" >/dev/null ;;
esac
