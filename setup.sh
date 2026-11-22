#!/usr/bin/env bash
# Parlera setup for macOS (Apple Silicon). Safe to run again at any time.
#   ./setup.sh            install everything (recommended)
#   ./setup.sh --no-model skip the large Ollama model download
set -euo pipefail
cd "$(dirname "$0")"

bold() { printf "\n\033[1m%s\033[0m\n" "$*"; }
SKIP_MODEL=0
[[ "${1:-}" == "--no-model" ]] && SKIP_MODEL=1
MODEL="${PARLERA_MODEL:-gemma3:27b}"

bold "1/5  Python"
PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then PY="$c"; break; fi
done
if [[ -z "$PY" ]]; then
  echo "Python 3.10+ not found. Install it with Homebrew:  brew install python@3.12"; exit 1
fi
echo "Using $($PY --version)"

bold "2/5  Python packages (FastAPI, Whisper for Apple Silicon, Piper voices…)"
EXTRAS="mac,piper"
[[ "$(uname -m)" != "arm64" ]] && EXTRAS="faster,piper"
if command -v uv >/dev/null 2>&1; then
  uv venv --python "$PY" .venv
  uv pip install --python .venv/bin/python -e ".[$EXTRAS]"
else
  "$PY" -m venv .venv
  .venv/bin/pip install --upgrade pip >/dev/null
  .venv/bin/pip install -e ".[$EXTRAS]"
fi

bold "3/5  Ollama (local language model)"
if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama is not installed. Download it from https://ollama.com/download (or: brew install --cask ollama),"
  echo "start it once, then run ./setup.sh again to download the model."
else
  if ollama list 2>/dev/null | awk '{print $1}' | grep -qx "$MODEL"; then
    echo "Model $MODEL is already installed."
  elif [[ $SKIP_MODEL == 1 ]]; then
    echo "Skipping model download. Later run:  ollama pull $MODEL"
  else
    read -r -p "Download $MODEL now (~17 GB)? [Y/n] " ans
    if [[ ! "$ans" =~ ^[Nn] ]]; then ollama pull "$MODEL"; else echo "Later run:  ollama pull $MODEL"; fi
  fi
fi

bold "4/5  Speech recognition model (Whisper large-v3-turbo, ~1.6 GB)"
if [[ "$(uname -m)" == "arm64" ]]; then
  .venv/bin/python - <<'PYEOF' || echo "Could not prefetch now — it will download on first use."
from huggingface_hub import snapshot_download
snapshot_download("mlx-community/whisper-large-v3-turbo")
print("Whisper model ready.")
PYEOF
else
  echo "faster-whisper downloads its model on first use."
fi

bold "5/5  Voices & Anki (manual, optional but recommended)"
cat <<'TXT'
 • Better voices (free): System Settings → Accessibility → Spoken Content → System voice →
   Manage Voices… → download e.g. "Alva (Premium)" or "Klara" (Swedish) and "Thomas" /
   "Audrey (Premium)" (French), plus an English voice such as "Ava (Premium)".
 • Anki: install Anki (apps.ankiweb.net), then Tools → Add-ons → Get Add-ons → code 2055492159
   (AnkiConnect) and restart Anki. Keep Anki open while you study to sync cards automatically.
TXT

bold "Done!  Start Parlera with:  ./run.sh   (or double-click Parlera.command)"
