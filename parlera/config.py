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

    def ensure(self) -> None:
        for p in (self.root, self.prompts, self.curricula, self.voices, self.media,
                  self.tts_cache, self.backups):
            p.mkdir(parents=True, exist_ok=True)
        # Copy editable defaults on first run (never overwrite user edits).
        for sub in ("prompts", "curricula"):
            src = DEFAULTS_DIR / sub
            dst = getattr(self, sub)
            for f in src.iterdir():
                if f.is_file() and not (dst / f.name).exists():
                    shutil.copy2(f, dst / f.name)


DEFAULT_SETTINGS: dict[str, Any] = {
    "ui": {"language": "sv", "theme": "auto"},
    "learner": {
        "name": "",
        "native_language": "English",
        "goals": {
            "fr": "Rebuild my school French from the basics, then prepare for the DELF exams (B1, later B2).",
            "sv": "Learn Swedish from zero. Long-term: pass Swedex B1/B2 and eventually TISUS.",
        },
    },
    "llm": {
        "base_url": "http://127.0.0.1:11434",
        "model": "gemma3:27b",
        "analysis_model": "",          # empty = same as model
        "temperature": 0.7,
        "num_ctx": 16384,
        "keep_alive": "30m",
        "disable_thinking": True,      # sends think:false for reasoning models (qwen3, ...)
        "context_messages": 40,        # how many recent messages are sent each turn
    },
    "stt": {
        "backend": "auto",             # auto | mlx | faster | off
        "model": "mlx-community/whisper-large-v3-turbo",
        "models": {"fr": "", "sv": ""},  # optional per-language override
        "default_input_language": "target",  # target | en | auto
        "pronunciation_hints": True,   # use Whisper word confidence + repeat comparison as pronunciation hints
        "confidence_threshold": 0.55,  # words recognised below this probability are flagged
    },
    "tts": {
        "engine": "auto",              # auto | macos | piper | browser | off
        "speed": 1.0,
        "beginner_slowdown": True,     # target language a bit slower at A1/A2
        "speak_corrections": True,
        "voices": {
            "macos": {"fr": "", "sv": "", "en": ""},   # empty = best installed voice
            "piper": {"fr": "fr_FR-siwis-medium", "sv": "sv_SE-nst-medium", "en": "en_US-lessac-medium"},
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
        "decks": {"sv": "Parlera::Swedish", "fr": "Parlera::French"},  # any existing or new deck
        "auto_add": True,              # push new words to Anki automatically after each session
        "deck_per_unit": False,
        "add_reverse": True,
        "include_audio": True,
        "auto_sync": True,
    },
    "vocab": {"max_cards_per_session": 15, "min_zipf": 2.0},
    "curriculum": {"advance_threshold": 0.75, "auto_advance": False},
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

    def _load(self) -> dict:
        user = {}
        if self.path.exists():
            try:
                user = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                user = {}
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
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
            return copy.deepcopy(self._data)

    def reload(self) -> None:
        with self._lock:
            self._data = self._load()
