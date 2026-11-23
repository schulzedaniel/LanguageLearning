"""Demo mode: run Parlera on a throwaway copy of the data, so showing it to others leaves no traces.

The demo is a separate server process with its own temporary data folder:
- "copy": your real progress, sessions, prompts and settings are copied (database via SQLite's
  backup API, so the copy is consistent even while Parlera runs);
- "fresh": only your settings (models, voices) are copied, everything else starts empty.
Anki is disabled in the demo, the demo never unloads models or quits Ollama, and the
temporary folder is deleted when the demo stops.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .config import Paths, deep_merge

DEMO_OVERRIDES = {
    "anki": {"auto_add": False, "auto_sync": False, "url": "http://127.0.0.1:9"},  # never touch real Anki
    "app": {"quit_ollama": "never", "idle_quit_minutes": 60},
}


def prepare_demo_dir(source: Paths, mode: str = "copy") -> Path:
    if mode not in ("copy", "fresh"):
        raise ValueError("Demo mode must be 'copy' or 'fresh'.")
    target = Path(tempfile.mkdtemp(prefix="parlera-demo-"))
    settings = {}
    if source.settings.exists():
        try:
            settings = json.loads(source.settings.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            settings = {}
    settings = deep_merge(settings, DEMO_OVERRIDES)
    settings.setdefault("app", {})["demo"] = mode
    (target / "settings.json").write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
    if mode == "copy":
        if source.db.exists():
            src = sqlite3.connect(source.db)
            dst = sqlite3.connect(target / "parlera.db")
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
        for sub in ("prompts", "curricula"):
            if getattr(source, sub).exists():
                shutil.copytree(getattr(source, sub), target / sub)
    if source.voices.exists() and any(source.voices.iterdir()):
        try:
            os.symlink(source.voices, target / "voices")  # read-only use; avoids copying large voice files
        except OSError:
            pass
    return target


def free_port(preferred: int = 8650) -> int:
    for port in [preferred, *range(preferred + 1, preferred + 40)]:
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def spawn_demo(source_root: Path, mode: str, open_window: bool = True) -> dict:
    """Start a demo server process (it creates and later deletes its own temporary copy)."""
    port = free_port()
    env = {**os.environ, "PARLERA_DATA": str(source_root)}
    args = [sys.executable, "-m", "parlera", "--demo", mode, "--port", str(port)]
    if not open_window:
        args.append("--no-browser")
    log = open(Path(tempfile.gettempdir()) / "parlera-demo.log", "w")  # last demo's output, for troubleshooting
    proc = subprocess.Popen(args, env=env, stdout=log, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    for _ in range(60):  # wait until it answers (up to ~15 s)
        if proc.poll() is not None:
            raise RuntimeError("The demo could not start (see the Terminal / log).")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return {"url": url, "port": port, "pid": proc.pid, "process": proc}
        except OSError:
            time.sleep(0.25)
    return {"url": url, "port": port, "pid": proc.pid, "process": proc}
