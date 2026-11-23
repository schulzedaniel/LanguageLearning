"""Paths and user settings.

All user data lives in one folder (default ``~/Parlera``, override with the
``PARLERA_DATA`` environment variable):

    ~/Parlera/
      parlera.db          SQLite database (sessions, messages, vocab, progress, memories)
      settings.json       your settings (merged over the defaults below)
      prompts/*.md        editable tutor/system prompts (Jinja2 templates)
      curricula/*.yaml    editable curricula
      voices/             Piper voice models (optional)
      media/              generated audio for Anki cards
      cache/tts/          cached speech audio
      backups/            automatic daily database backups
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parent
DEFAULTS_DIR = APP_DIR / "defaults"
STATIC_DIR = APP_DIR / "static"

LANGUAGES = {
    "fr": {"name": "French", "native_name": "Français", "flag": "🇫🇷"},
    "sv": {"name": "Swedish", "native_name": "Svenska", "flag": "🇸🇪"},
    "en": {"name": "English", "native_name": "English", "flag": "🇬🇧"},
}


def data_dir() -> Path:
    return Path(os.environ.get("PARLERA_DATA", Path.home() / "Parlera")).expanduser()


class Paths:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else data_dir()
        self.db = self.root / "parlera.db"
        self.settings = self.root / "settings.json"
        self.prompts = self.root / "prompts"
        self.curricula = self.root / "curricula"
        self.voices = self.root / "voices"
        self.media = self.root / "media"
        self.tts_cache = self.root / "cache" / "tts"
        self.backups = self.root / "backups"
        self.browser_profile = self.root / "browser"   # profile of the dedicated app window

    def ensure(self) -> list[str]:
        """Create the folder layout and install/upgrade the editable defaults.

        - Missing prompt/curriculum files are copied from the defaults.
        - A file that still equals an *older* built-in default (the user never edited it) is
          upgraded to the current default automatically.
        - Files the user edited are never touched (they can use "Reset" in the app).
        Returns the list of upgraded files (relative paths).
        """
        for p in (self.root, self.prompts, self.curricula, self.voices, self.media,
                  self.tts_cache, self.backups):
            p.mkdir(parents=True, exist_ok=True)
        known = _known_default_hashes()
        upgraded: list[str] = []
        for sub in ("prompts", "curricula"):
            src = DEFAULTS_DIR / sub
            dst = getattr(self, sub)
            for f in src.iterdir():
                if not f.is_file() or f.name.startswith("."):
                    continue
                target = dst / f.name
                if not target.exists():
                    shutil.copy2(f, target)
                    continue
                current = file_hash(target.read_bytes())
                if current == file_hash(f.read_bytes()):
                    continue
                if current in known.get(f"{sub}/{f.name}", ()):
                    shutil.copy2(f, target)
                    upgraded.append(f"{sub}/{f.name}")
        return upgraded


def file_hash(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data.replace(b"\r\n", b"\n").strip()).hexdigest()


def _known_default_hashes() -> dict[str, set[str]]:
    p = DEFAULTS_DIR / "known_hashes.json"
    if not p.exists():
        return {}
    try:
        return {k: set(v) for k, v in json.loads(p.read_text(encoding="utf-8")).items()}
    except (OSError, json.JSONDecodeError):
        return {}


DEFAULT_SETTINGS: dict[str, Any] = {
    "ui": {"language": "sv", "theme": "auto"},
    "app": {
        "auto_quit": True,             # stop Parlera when the last browser tab is closed (~45 s grace for reloads)
        "idle_quit_minutes": 30,       # fallback: stop if no tab was seen for this long (browsers pause hidden tabs)
        "quit_ollama": "if_started",   # on quit: if_started (only if Parlera started it) | always | never
        "window": "auto",              # auto | app (own window via Chrome/Edge/Brave) | browser (normal tab)
        "offline": "auto",             # auto: don't contact Hugging Face when all models are already downloaded
    },
    "teachers": {                      # name and gender per language; the voice follows the gender
        "sv": {"name": "Astrid", "gender": "female"},
        "fr": {"name": "Élodie", "gender": "female"},
        "en": {"name": "Oliver", "gender": "male"},
    },
    "learner": {
        "name": "",
        "native_language": "English",
        "goals": {
            "fr": "Rebuild my school French from the basics, then prepare for the DELF exams (B1, later B2).",
            "sv": "Learn Swedish from zero. Long-term: pass Swedex B1/B2 and eventually TISUS.",
            "en": "Move from B2/C1 to a confident C1–C2: precise grammar and sophisticated vocabulary. Target: top scores in IELTS Academic (8+), TOEFL iBT and the Duolingo English Test.",
        },
    },
    "llm": {
        "base_url": "http://127.0.0.1:11434",
        "model": "gemma4:26b",
        "analysis_model": "",          # empty = same as model
        "temperature": 0.7,
        "num_ctx": 16384,
        "keep_alive": "30m",
        "disable_thinking": True,      # sends think:false for reasoning models (qwen3, ...)
        "context_messages": 40,        # how many recent messages are sent each turn
        "exclusive_models": True,      # keep only one big model in memory (unload the other before loading)
        "big_model_gb": 6,             # models at least this large count as "big"
    },
    "stt": {
        "backend": "auto",             # auto | mlx | faster | off
        "model": "mlx-community/whisper-large-v3-turbo",
        "models": {"fr": "", "sv": "", "en": ""},  # optional per-language override
        "default_input_language": "target",  # target | en | auto
        "pronunciation_hints": True,   # use Whisper word confidence + repeat comparison as pronunciation hints
        "confidence_threshold": 0.55,  # words recognised below this probability are flagged
    },
    "tts": {
        "engine": "auto",              # auto | macos | piper | kokoro | browser | off
        "engines": {"fr": "", "sv": "", "en": ""},   # per-language override ("" = use "engine")
        "speed": 1.0,
        "beginner_slowdown": True,     # target language a bit slower at A1/A2
        "speak_corrections": True,
        "voices": {
            "macos": {"fr": "", "sv": "", "en": ""},   # empty = best installed voice
            "piper": {"fr": "", "sv": "", "en": ""},     # empty = best downloaded voice of the teacher's gender
            "kokoro": {"fr": "", "sv": "", "en": ""},    # empty = bm_george (male) / bf_emma (female); French: ff_siwis
            "browser": {"fr": "", "sv": "", "en": ""},
        },
    },
    "conversation": {
        "input_mode": "handsfree",     # handsfree | ptt | text
        "silence_ms": 1400,
        "barge_in": False,
        "immersion": "auto",           # auto | 0..100
        "show_text": True,
    },
    "anki": {
        "url": "http://127.0.0.1:8765",
        "decks": {"sv": "Parlera::Swedish", "fr": "Parlera::French", "en": "Parlera::English"},  # any existing or new deck
        "auto_add": True,              # push new words to Anki automatically after each session
        "deck_per_unit": False,
        "add_reverse": True,
        "include_audio": True,
        "auto_sync": True,
    },
    "vocab": {
        "max_cards_per_session": 15,
        "min_zipf": 2.0,
        "reinforce": True,             # weave recently learned words into sessions
        "reinforce_count": 6,          # candidates offered to the tutor per session (it uses a few)
    },
    "curriculum": {"advance_threshold": 0.75, "auto_advance": False},
    "practice": {
        "round_length": 10,            # questions per game round
        "lecture_thinking": True,      # let reasoning models think while writing grammar lectures
    },
    "workshop": {
        "interval_days": 7,            # suggest a mistake workshop this often
        "min_mistakes": 3,             # ...once at least this many new mistakes were collected
        "thinking": True,              # let reasoning models think while summarising (slower, better)
    },
}


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


class Settings:
    """Thread-safe settings stored as JSON, deep-merged over DEFAULT_SETTINGS."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._data = self._load()

    @property
    def backup_path(self) -> Path:
        return self.path.with_name(self.path.name + ".bak")

    def _load(self) -> dict:
        """Load settings; if the file is damaged, fall back to the last good copy (never silently to defaults)."""
        user: dict = {}
        for candidate in (self.path, self.backup_path, self.path.parent / "backups" / "settings-latest.json"):
            if not candidate.exists():
                continue
            try:
                user = json.loads(candidate.read_text(encoding="utf-8"))
                if candidate != self.path:
                    import logging
                    logging.getLogger("parlera").warning("settings.json unreadable — restored from %s", candidate)
                break
            except (OSError, json.JSONDecodeError):
                continue
        return deep_merge(DEFAULT_SETTINGS, user)

    def all(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data)

    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self._data
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return copy.deepcopy(cur)

    def update(self, patch: dict) -> dict:
        with self._lock:
            self._data = deep_merge(self._data, patch)
            if self.path.exists():  # keep the previous good version next to it
                try:
                    json.loads(self.path.read_text(encoding="utf-8"))
                    shutil.copy2(self.path, self.backup_path)
                except (OSError, json.JSONDecodeError):
                    pass
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
            return copy.deepcopy(self._data)

    def reload(self) -> None:
        with self._lock:
            self._data = self._load()
