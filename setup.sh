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
# Natural Kokoro voices need Python 3.12 or older (its dependencies don't support 3.13 yet).
WANT_KOKORO=0
if .venv/bin/python -c 'import kokoro' >/dev/null 2>&1; then
  WANT_KOKORO=1
else
  k="$(ask "Install natural neural voices (Kokoro: much more natural English, plus French; ~1.5 GB incl. PyTorch)? [y/N]" "N")"
  [[ "$k" =~ ^[Yy] ]] && WANT_KOKORO=1
fi
PY=""
for c in python3.12 python3.11 python3.13 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then PY="$c"; break; fi
done
if [[ -z "$PY" ]] && ! command -v uv >/dev/null 2>&1; then
  echo "Python 3.10+ not found. Install it with Homebrew:  brew install python@3.12"; exit 1
fi
PYVER="$([[ -n "$PY" ]] && "$PY" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' || echo none)"
if [[ $WANT_KOKORO == 1 && ( "$PYVER" == "3.13" || "$PYVER" == "none" ) ]]; then
  if command -v uv >/dev/null 2>&1; then
    PY="3.12"   # uv downloads a private Python 3.12 if needed
    echo "Using Python 3.12 (provided by uv) for the Kokoro voices."
  else
    echo "Kokoro needs Python 3.12. Install it with:  brew install python@3.12   (then run ./setup.sh again)."
    echo "Continuing without Kokoro for now."
    WANT_KOKORO=0
  fi
else
  echo "Using Python $PYVER"
fi
# Recreate the program's virtual environment if it was built with another Python version
# (this only contains installed packages — your data is elsewhere and is not touched).
if [[ -x .venv/bin/python ]]; then
  CUR="$(.venv/bin/python -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
  TARGET="$([[ "$PY" == "3.12" ]] && echo 3.12 || "$PY" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
  if [[ "$CUR" != "$TARGET" ]]; then echo "Rebuilding .venv for Python $TARGET (was $CUR)…"; rm -rf .venv; fi
fi

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
[[ $WANT_KOKORO == 1 ]] && EXTRAS="$EXTRAS,kokoro"
if command -v uv >/dev/null 2>&1; then
  uv venv --allow-existing --python "$PY" .venv </dev/null
  uv pip install --python .venv/bin/python -e ".[$EXTRAS]" </dev/null
else
  [[ -x .venv/bin/python ]] || "$PY" -m venv .venv
  .venv/bin/pip install --upgrade pip >/dev/null </dev/null
  .venv/bin/pip install -e ".[$EXTRAS]" </dev/null
fi

if [[ $WANT_KOKORO == 1 ]] && command -v brew >/dev/null 2>&1 && ! command -v espeak-ng >/dev/null 2>&1; then
  echo "Installing espeak-ng (pronunciation backend Kokoro uses for French and rare English words)…"
  brew install espeak-ng </dev/null || echo "Could not install espeak-ng; English will still work."
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
      -e "do script \"cd \" & quoted form of \"$ESCAPED\" & \" && ./run.sh; exit\"" \
      -e 'end tell'
    # Give the launcher a proper name/identifier so macOS prompts say "Parlera" (not "applet").
    # Editing Info.plist invalidates the ad-hoc signature, so re-sign it; if that fails, keep the
    # unmodified app (it still works, the prompt just says "applet").
    APP="$HOME/Applications/Parlera.app"
    PLIST="$APP/Contents/Info.plist"
    cp "$PLIST" "$PLIST.orig"
    # App icon: build an .icns from the Parlera logo (sips + iconutil ship with macOS).
    ICON_SRC="$HERE/parlera/static/icon-1024.png"
    if [[ -f "$ICON_SRC" ]] && command -v iconutil >/dev/null 2>&1; then
      ICONSET="$(mktemp -d)/Parlera.iconset"
      mkdir -p "$ICONSET"
      for s in 16 32 128 256 512; do
        sips -z "$s" "$s" "$ICON_SRC" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
        sips -z "$((s * 2))" "$((s * 2))" "$ICON_SRC" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
      done
      if iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/applet.icns"; then
        # newer osacompile apps also carry an asset catalog icon, which would win — remove it
        rm -f "$APP/Contents/Resources/Assets.car"
        plutil -remove CFBundleIconName "$PLIST" >/dev/null 2>&1 || true
        plutil -replace CFBundleIconFile -string "applet" "$PLIST"
      fi
      rm -rf "$(dirname "$ICONSET")"
    fi
    if plutil -replace CFBundleName -string "Parlera" "$PLIST" &&
       plutil -replace CFBundleDisplayName -string "Parlera" "$PLIST" &&
       plutil -replace CFBundleIdentifier -string "local.parlera.launcher" "$PLIST" &&
       codesign --force --sign - "$APP" >/dev/null 2>&1; then
      rm -f "$PLIST.orig"
      touch "$APP"   # refresh Finder/Dock icon cache
    else
      mv "$PLIST.orig" "$PLIST"
      codesign --force --sign - "$APP" >/dev/null 2>&1 || true
    fi
    echo "Created ~/Applications/Parlera.app — find it with Spotlight (⌘ Space → Parlera) and drag it to your Dock."
    echo "The first time you open it, macOS asks whether \"Parlera\" may control Terminal: click OK."
    echo "(It only opens a Terminal window and runs ./run.sh in this folder.)"
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
