"""System helpers: dedicated app window, offline mode, cache sizes/clearing."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import webbrowser
from pathlib import Path

# Chromium-based browsers that can open a site as its own app window (--app=URL)
MAC_APP_BROWSERS = ["Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium", "Vivaldi"]
LINUX_APP_BROWSERS = ["google-chrome", "chromium", "chromium-browser", "microsoft-edge", "brave-browser"]

KOKORO_REPO = "hexgrad/Kokoro-82M"


# ---------------------------------------------------------------------------
# dedicated window
# ---------------------------------------------------------------------------
def find_app_browser() -> str | None:
    """Path/name of a browser that supports app windows, or None."""
    if platform.system() == "Darwin":
        for name in MAC_APP_BROWSERS:
            for base in ("/Applications", str(Path.home() / "Applications")):
                if Path(base, f"{name}.app").exists():
                    return str(Path(base, f"{name}.app"))
        return None
    for name in LINUX_APP_BROWSERS:
        if shutil.which(name):
            return shutil.which(name)
    return None


def open_ui(url: str, mode: str, profile_dir: Path) -> str:
    """Open Parlera. mode: auto | app | browser. Returns what was used ("app:<browser>" or "browser")."""
    if mode in ("auto", "app"):
        browser = find_app_browser()
        if browser:
            profile_dir.mkdir(parents=True, exist_ok=True)
            args = [f"--app={url}", f"--user-data-dir={profile_dir}", "--no-first-run",
                    "--no-default-browser-check", "--window-size=1380,900"]
            try:
                if browser.endswith(".app"):
                    subprocess.Popen(["open", "-na", browser, "--args", *args])
                else:
                    subprocess.Popen([browser, *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return f"app:{Path(browser).stem}"
            except OSError:
                pass
    webbrowser.open(url)
    return "browser"


# ---------------------------------------------------------------------------
# offline mode
# ---------------------------------------------------------------------------
def hf_hub_dir() -> Path:
    if os.environ.get("HF_HUB_CACHE"):
        return Path(os.environ["HF_HUB_CACHE"]).expanduser()
    home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")).expanduser()
    return home / "hub"


def hf_cached(repo: str) -> bool:
    d = hf_hub_dir() / ("models--" + repo.replace("/", "--")) / "snapshots"
    return d.exists() and any(d.iterdir())


def needed_hf_models(settings: dict) -> list[str]:
    """Hugging Face repos the current settings need at runtime."""
    repos = []
    stt = settings.get("stt", {})
    if stt.get("backend", "auto") != "off":
        for m in [stt.get("model", ""), *(stt.get("models") or {}).values()]:
            if m and "/" in m:
                repos.append(m)
    tts = settings.get("tts", {})
    engines = [tts.get("engine"), *(tts.get("engines") or {}).values()]
    if "kokoro" in engines:
        repos.append(KOKORO_REPO)
    return sorted(set(repos))


def configure_offline(settings: dict) -> dict:
    """If every needed model is already downloaded, stop libraries from contacting Hugging Face.

    Without this, loading a cached model may still try a network check (slow when offline).
    """
    mode = settings.get("app", {}).get("offline", "auto")
    needed = needed_hf_models(settings)
    missing = [r for r in needed if not hf_cached(r)]
    offline = mode == "always" or (mode == "auto" and not missing)
    if offline:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    return {"offline": offline, "needed": needed, "missing": missing}


# ---------------------------------------------------------------------------
# cache
# ---------------------------------------------------------------------------
def dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                pass
    return total


BROWSER_CACHE_DIRS = ["Default/Cache", "Default/Code Cache", "Default/GPUCache", "Default/Service Worker/CacheStorage",
                      "GrShaderCache", "ShaderCache", "GraphiteDawnCache"]


def cache_info(paths, profile_dir: Path) -> dict:
    backups = sorted(paths.backups.glob("parlera-20*.db"))
    old_backups = backups[:-3]
    return {
        "tts": {"label": "Speech audio cache", "bytes": dir_size(paths.tts_cache),
                "hint": "Recreated automatically when needed."},
        "media": {"label": "Flashcard audio (already copied to Anki)", "bytes": dir_size(paths.media),
                  "hint": "Anki keeps its own copy."},
        "old_backups": {"label": "Older daily backups (keeps the newest 3)",
                        "bytes": sum(dir_size(b) for b in old_backups), "hint": f"{len(old_backups)} files"},
        "browser": {"label": "App-window browser cache", "bytes": sum(dir_size(profile_dir / d) for d in BROWSER_CACHE_DIRS),
                    "hint": "Cached pages of the dedicated window; your microphone permission is kept."},
        "models": {"label": "Downloaded speech models (not cleared here)", "bytes": dir_size(hf_hub_dir()),
                   "hint": str(hf_hub_dir()), "readonly": True},
    }


def clear_cache(paths, profile_dir: Path, targets: list[str]) -> dict:
    freed = 0
    for t in targets:
        if t == "tts":
            freed += dir_size(paths.tts_cache)
            shutil.rmtree(paths.tts_cache, ignore_errors=True)
            paths.tts_cache.mkdir(parents=True, exist_ok=True)
        elif t == "media":
            freed += dir_size(paths.media)
            shutil.rmtree(paths.media, ignore_errors=True)
            paths.media.mkdir(parents=True, exist_ok=True)
        elif t == "old_backups":
            for b in sorted(paths.backups.glob("parlera-20*.db"))[:-3]:
                freed += dir_size(b)
                b.unlink(missing_ok=True)
        elif t == "browser":
            for d in BROWSER_CACHE_DIRS:
                freed += dir_size(profile_dir / d)
                shutil.rmtree(profile_dir / d, ignore_errors=True)
    return {"freed": freed}
