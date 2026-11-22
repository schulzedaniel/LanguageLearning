#!/usr/bin/env bash
# Parlera setup for macOS (Apple Silicon). Safe to run again at any time (e.g. after updating).
#   ./setup.sh             interactive setup (recommended)
#   ./setup.sh --no-model  never download an Ollama model
#   ./setup.sh --yes       accept all defaults without asking
set -euo pipefail
cd "$(dirname "$0")"
HERE="$(pwd)"

bold() { printf "\n\033[1m%s\033[0m\n" "$*"; }
SKIP_MODEL=0; ASSUME_YES=0
for a in "$@"; do
  case "$a" in --no-model) SKIP_MODEL=1 ;; --yes|-y) ASSUME_YES=1 ;; esac
done
# ask "question" "default" -> echoes the answer (default when non-interactive)
ask() {
  local reply=""
  if [[ $ASSUME_YES == 0 && -t 0 ]]; then read -r -p "$1 " reply; fi
  echo "${reply:-$2}"
}
DEFAULT_MODEL="gemma4:26b"

bold "1/6  Python"
PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then PY="$c"; break; fi
done
if [[ -z "$PY" ]]; then
  echo "Python 3.10+ not found. Install it with Homebrew:  brew install python@3.12"; exit 1
fi
echo "Using $($PY --version)"

bold "2/6  Where to keep your data"
# Your progress, sessions, words, memories, prompts and curricula. The program code stays in this folder.
if [[ -f parlera.env ]]; then set -a; source parlera.env; set +a; fi
CURRENT="${PARLERA_DATA:-$HOME/Parlera}"
DATA_DIR="$(ask "Data folder [$CURRENT]:" "$CURRENT")"
DATA_DIR="${DATA_DIR/#\~/$HOME}"
mkdir -p "$DATA_DIR"
printf 'PARLERA_DATA=%q\n' "$DATA_DIR" > parlera.env
echo "Data folder: $DATA_DIR   (saved in parlera.env)"

bold "3/6  Python packages (web app, Whisper for Apple Silicon, Piper voices…)"
EXTRAS="mac,piper"
[[ "$(uname -m)" != "arm64" ]] && EXTRAS="faster,piper"
if command -v uv >/dev/null 2>&1; then
  uv venv --allow-existing --python "$PY" .venv </dev/null
  uv pip install --python .venv/bin/python -e ".[$EXTRAS]" </dev/null
else
  [[ -x .venv/bin/python ]] || "$PY" -m venv .venv
  .venv/bin/pip install --upgrade pip >/dev/null </dev/null
  .venv/bin/pip install -e ".[$EXTRAS]" </dev/null
fi

bold "4/6  Language model (Ollama)"
# Ollama keeps ALL models in its own store (~/.ollama/models). Parlera only talks to Ollama,
# so models you already have are reused — nothing is ever downloaded twice.
MODEL=""
if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama is not installed. Download it from https://ollama.com/download (or: brew install --cask ollama),"
  echo "then run ./setup.sh again."
else
  if ! curl -s -o /dev/null http://127.0.0.1:11434/api/tags; then
    (open -g -a Ollama 2>/dev/null || (ollama serve >/dev/null 2>&1 &)); sleep 3
  fi
  INSTALLED="$(ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -v -i embed || true)"
  # If a Gemma 4 model is already installed, pressing Enter uses it (no download).
  PREFERRED="$(grep -m1 -i '^gemma4' <<< "$INSTALLED" || true)"
  [[ -n "$PREFERRED" ]] && DEFAULT_MODEL="$PREFERRED"
  if [[ -n "$INSTALLED" ]]; then
    echo "Models you already have in Ollama (they're shared, not copied):"
    i=1; while read -r m; do echo "   $i) $m"; i=$((i+1)); done <<< "$INSTALLED"
    pick="$(ask "Type a number to use one of them, or press Enter for $DEFAULT_MODEL:" "")"
    if [[ "$pick" =~ ^[0-9]+$ ]]; then MODEL="$(sed -n "${pick}p" <<< "$INSTALLED")"; fi
  fi
  MODEL="${MODEL:-$DEFAULT_MODEL}"
  if grep -qx "$MODEL" <<< "$INSTALLED"; then
    echo "Using $MODEL (already installed)."
  elif [[ $SKIP_MODEL == 1 ]]; then
    echo "Skipping download. Later run:  ollama pull $MODEL"
  else
    ans="$(ask "Download $MODEL now (~17 GB)? [Y/n]" "Y")"
    if [[ ! "$ans" =~ ^[Nn] ]]; then ollama pull "$MODEL" </dev/null; else echo "Later run:  ollama pull $MODEL"; fi
  fi
  PARLERA_DATA="$DATA_DIR" .venv/bin/python - "$MODEL" <<'PYEOF'
import sys
from parlera.config import Paths, Settings
p = Paths(); p.ensure()
Settings(p.settings).update({"llm": {"model": sys.argv[1]}})
print(f"Parlera will use {sys.argv[1]} (change it any time in Settings).")
PYEOF
fi

bold "5/6  Speech recognition model (Whisper large-v3-turbo, ~1.6 GB)"
# Stored in the shared Hugging Face cache (~/.cache/huggingface) — reused if you already have it.
if [[ "$(uname -m)" == "arm64" ]]; then
  .venv/bin/python - <<'PYEOF' || echo "Could not prefetch now — it will download on first use."
from huggingface_hub import snapshot_download
snapshot_download("mlx-community/whisper-large-v3-turbo")
print("Whisper model ready.")
PYEOF
else
  echo "faster-whisper downloads its model on first use."
fi

bold "6/6  App launcher"
if command -v osacompile >/dev/null 2>&1; then
  mk="$(ask "Create a 'Parlera' app in ~/Applications (Spotlight/Dock)? [Y/n]" "Y")"
  if [[ ! "$mk" =~ ^[Nn] ]]; then
    mkdir -p "$HOME/Applications"
    rm -rf "$HOME/Applications/Parlera.app"
    ESCAPED="${HERE//\"/\\\"}"
    osacompile -o "$HOME/Applications/Parlera.app" \
      -e 'tell application "Terminal"' \
      -e 'activate' \
      -e "do script \"cd \" & quoted form of \"$ESCAPED\" & \" && ./run.sh\"" \
      -e 'end tell'
    echo "Created ~/Applications/Parlera.app — find it with Spotlight (⌘ Space → Parlera) and drag it to your Dock."
  fi
fi

cat <<'TXT'

Optional but recommended:
 • Better voices (free): System Settings → Accessibility → Spoken Content → System voice →
   Manage Voices… → e.g. "Alva (Premium)" (Swedish), a French Premium/Enhanced voice, and an
   English one like "Ava (Premium)". Choose them in Parlera → Settings → Tutor voice.
 • Anki: install Anki (apps.ankiweb.net), then Tools → Add-ons → Get Add-ons → code 2055492159
   (AnkiConnect) and restart Anki. Pick your decks in Parlera → Settings → Anki.
TXT

bold "Done!  Start Parlera with the Parlera app, ./run.sh, or by double-clicking Parlera.command."
