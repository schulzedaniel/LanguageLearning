"""Text-to-speech engines.

* ``macos``  – the built-in ``say`` command. Free, no install, and the downloadable
               Premium/Enhanced system voices (System Settings → Accessibility →
               Spoken Content → System voice → Manage Voices) sound very good,
               including Swedish (Alva, Klara, Oskar) and French (Thomas, Amélie, Audrey…).
* ``piper``  – neural offline voices (pip install piper-tts), works on any OS.
* ``kokoro`` – Kokoro-82M neural voices (pip install kokoro). Very natural English
               (American and British) and one French voice; no Swedish. Runs locally, ~330 MB model.
* ``browser``– the browser's speechSynthesis (no server audio; not usable for Anki audio).

Engines can be chosen per language (``tts.engines``), e.g. Kokoro for English and macOS for Swedish.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import re
import shutil
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Callable

from .audio import concat_wavs

LOCALE_PREFIX = {"fr": "fr", "sv": "sv", "en": "en"}
PREFERRED_LOCALE = {"fr": "fr_FR", "sv": "sv_SE", "en": "en_US"}
MACOS_GOOD_VOICES = {
    "sv": ["Alva", "Klara", "Oskar"],
    "fr": ["Thomas", "Audrey", "Aurélie", "Amélie", "Marie", "Jacques"],
    "en": ["Ava", "Zoe", "Samantha", "Allison", "Evan", "Tom", "Daniel", "Serena"],
}
MACOS_NOVELTY = {"Albert", "Bad News", "Bahh", "Bells", "Boing", "Bubbles", "Cellos", "Good News", "Jester",
                 "Organ", "Superstar", "Trinoids", "Whisper", "Wobble", "Zarvox", "Fred", "Junior", "Kathy",
                 "Ralph", "Grandma", "Grandpa", "Rocko", "Shelley", "Sandy", "Flo", "Eddy", "Reed"}

PIPER_CATALOG = [
    {"name": "fr_FR-siwis-medium", "lang": "fr", "path": "fr/fr_FR/siwis/medium", "desc": "French, female"},
    {"name": "fr_FR-tom-medium", "lang": "fr", "path": "fr/fr_FR/tom/medium", "desc": "French, male"},
    {"name": "fr_FR-upmc-medium", "lang": "fr", "path": "fr/fr_FR/upmc/medium", "desc": "French, 2 speakers"},
    {"name": "sv_SE-nst-medium", "lang": "sv", "path": "sv/sv_SE/nst/medium", "desc": "Swedish, male"},
    {"name": "en_US-lessac-medium", "lang": "en", "path": "en/en_US/lessac/medium", "desc": "English (US), female"},
    {"name": "en_GB-alba-medium", "lang": "en", "path": "en/en_GB/alba/medium", "desc": "English (UK), female"},
    {"name": "en_US-ryan-medium", "lang": "en", "path": "en/en_US/ryan/medium", "desc": "English (US), male"},
]
PIPER_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

# Kokoro voices: the first letter is the language (a = American English, b = British English, f = French)
KOKORO_VOICES = [
    {"name": "bm_george", "lang": "en", "desc": "British English, male"},
    {"name": "bm_fable", "lang": "en", "desc": "British English, male"},
    {"name": "bm_lewis", "lang": "en", "desc": "British English, male"},
    {"name": "bf_emma", "lang": "en", "desc": "British English, female"},
    {"name": "bf_isabella", "lang": "en", "desc": "British English, female"},
    {"name": "af_heart", "lang": "en", "desc": "American English, female (highest rated)"},
    {"name": "af_bella", "lang": "en", "desc": "American English, female"},
    {"name": "am_michael", "lang": "en", "desc": "American English, male"},
    {"name": "am_fenrir", "lang": "en", "desc": "American English, male"},
    {"name": "ff_siwis", "lang": "fr", "desc": "French, female"},
]
SERVER_ENGINES = ("macos", "piper", "kokoro")


class TTSError(RuntimeError):
    pass


class TTSManager:
    def __init__(self, settings_getter: Callable[[], dict], voices_dir: Path, cache_dir: Path):
        self._settings = settings_getter
        self.voices_dir = Path(voices_dir)
        self.cache_dir = Path(cache_dir)
        self._piper: dict[str, object] = {}
        self._lock = threading.Lock()
        self._macos_voices: list[dict] | None = None
        self._kokoro: dict[str, object] = {}

    @property
    def cfg(self) -> dict:
        return self._settings()["tts"]

    # -- engine selection -------------------------------------------------
    def available_engines(self) -> dict[str, bool]:
        return {
            "macos": shutil.which("say") is not None,
            "piper": importlib.util.find_spec("piper") is not None and any(self.voices_dir.glob("*.onnx")),
            "kokoro": importlib.util.find_spec("kokoro") is not None,
            "browser": True,
        }

    def engine_for(self, lang: str) -> str:
        """Engine used for one language: the per-language override if set and usable, else the main engine."""
        override = (self.cfg.get("engines") or {}).get(lang) or ""
        if override and override != "auto":
            if override in ("off", "browser") or self.available_engines().get(override):
                return override
        return self.engine()

    def engine(self) -> str:
        want = self.cfg.get("engine", "auto")
        avail = self.available_engines()
        if want == "off":
            return "off"
        if want != "auto":
            return want if avail.get(want) else "browser"
        if avail["macos"]:
            return "macos"
        if avail["piper"]:
            return "piper"
        return "browser"

    def server_side(self, langs: tuple[str, ...] | None = None) -> bool:
        """True if the server produces the audio (for all of the given languages)."""
        if langs is None:
            return self.engine() in SERVER_ENGINES
        return all(self.engine_for(lang) in SERVER_ENGINES for lang in langs)

    def status(self) -> dict:
        return {"engine": self.engine(), "engines": self.available_engines()}

    # -- voices -------------------------------------------------------------
    def macos_voices(self, refresh: bool = False) -> list[dict]:
        if self._macos_voices is not None and not refresh:
            return self._macos_voices
        voices: list[dict] = []
        if shutil.which("say"):
            try:
                out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=15).stdout
            except (subprocess.SubprocessError, OSError):
                out = ""
            for line in out.splitlines():
                m = re.match(r"^(?P<name>.*?)\s+(?P<loc>[a-z]{2,3}_[A-Z0-9]{2,3})\s+#", line)
                if m:
                    name = m.group("name").strip()
                    base = name.split(" (")[0]
                    if base in MACOS_NOVELTY:
                        continue
                    voices.append({"name": name, "locale": m.group("loc"),
                                   "quality": 2 if "Premium" in name else 1 if "Enhanced" in name else 0})
        self._macos_voices = voices
        return voices

    def piper_voices(self) -> list[dict]:
        out = []
        for f in sorted(self.voices_dir.glob("*.onnx")):
            lang = f.stem.split("_")[0]
            out.append({"name": f.stem, "locale": f.stem.split("-")[0], "lang": lang})
        return out

    def voices(self, engine: str, lang: str) -> list[dict]:
        if engine == "macos":
            vs = [v for v in self.macos_voices() if v["locale"].startswith(LOCALE_PREFIX[lang] + "_")]
            return sorted(vs, key=lambda v: (-v["quality"], v["locale"] != PREFERRED_LOCALE[lang], v["name"]))
        if engine == "piper":
            return [v for v in self.piper_voices() if v["lang"] == lang]
        if engine == "kokoro":
            return [v for v in KOKORO_VOICES if v["lang"] == lang]
        return []

    def _macos_voice(self, lang: str) -> str | None:
        chosen = (self.cfg["voices"].get("macos") or {}).get(lang)
        if chosen:
            return chosen
        vs = self.voices("macos", lang)
        if not vs:
            return None
        good = MACOS_GOOD_VOICES.get(lang, [])

        def rank(v: dict) -> tuple:
            base = v["name"].split(" (")[0]
            return (-v["quality"], v["locale"] != PREFERRED_LOCALE[lang],
                    good.index(base) if base in good else 99)
        return sorted(vs, key=rank)[0]["name"]

    # -- synthesis ----------------------------------------------------------
    def synth(self, text: str, lang: str, rate: float = 1.0) -> bytes:
        text = (text or "").strip()
        if not text:
            return b""
        engine = self.engine_for(lang)
        speed = float(self.cfg.get("speed", 1.0)) * rate
        if engine == "macos":
            voice = self._macos_voice(lang)
            key = f"macos|{voice}|{speed:.2f}|{text}"
            return self._cached(key, lambda: self._say(text, voice, speed))
        if engine == "piper":
            voice = (self.cfg["voices"].get("piper") or {}).get(lang) or ""
            key = f"piper|{voice}|{speed:.2f}|{text}"
            return self._cached(key, lambda: self._piper_synth(text, voice, speed))
        if engine == "kokoro":
            voice = (self.cfg["voices"].get("kokoro") or {}).get(lang) or ""
            key = f"kokoro|{voice}|{speed:.2f}|{text}"
            return self._cached(key, lambda: self._kokoro_synth(text, voice, speed))
        raise TTSError(f"TTS engine '{engine}' does not produce audio on the server.")

    def synth_segments(self, segments: list[dict], rates: dict[str, float] | None = None) -> bytes:
        rates = rates or {}
        return concat_wavs([self.synth(s["text"], s["lang"], rates.get(s["lang"], 1.0)) for s in segments])

    def _cached(self, key: str, fn: Callable[[], bytes]) -> bytes:
        h = hashlib.sha1(key.encode("utf-8")).hexdigest()
        p = self.cache_dir / f"{h}.wav"
        if p.exists():
            return p.read_bytes()
        data = fn()
        if data:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        return data

    def _say(self, text: str, voice: str | None, speed: float) -> bytes:
        wpm = max(80, min(320, int(180 * speed)))
        if text.startswith("-"):
            text = " " + text
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out.wav"
            cmd = ["say", "-r", str(wpm), "-o", str(out), "--file-format=WAVE", "--data-format=LEI16@22050"]
            if voice:
                cmd += ["-v", voice]
            cmd.append(text)
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=60)
            except subprocess.CalledProcessError as e:
                raise TTSError(f"say failed: {e.stderr.decode('utf-8', 'replace')[:200]}") from e
            return out.read_bytes()

    def _piper_synth(self, text: str, voice_name: str, speed: float) -> bytes:
        voice = self._load_piper(voice_name)
        length_scale = 1.0 / max(0.5, min(2.0, speed))
        buf = io.BytesIO()
        with self._lock, wave.open(buf, "wb") as wf:
            try:
                from piper import SynthesisConfig  # piper-tts >= 1.3
                voice.synthesize_wav(text, wf, syn_config=SynthesisConfig(length_scale=length_scale))
            except ImportError:
                voice.synthesize(text, wf, length_scale=length_scale)  # piper-tts 1.2
        return buf.getvalue()

    def _kokoro_synth(self, text: str, voice: str, speed: float) -> bytes:
        if not voice:
            raise TTSError("No Kokoro voice for this language (Kokoro has English and French voices, not Swedish).")
        try:
            from kokoro import KPipeline
        except ImportError as e:
            raise TTSError("Kokoro is not installed. Run ./setup.sh and answer yes to natural voices, "
                           "or: .venv/bin/pip install kokoro soundfile") from e
        import numpy as np
        from .audio import float32_to_wav
        lang_code = voice[0]  # a/b = American/British English, f = French
        with self._lock:
            pipe = self._kokoro.get(lang_code)
            if pipe is None:
                pipe = KPipeline(lang_code=lang_code)   # downloads hexgrad/Kokoro-82M on first use
                self._kokoro[lang_code] = pipe
            chunks = []
            for result in pipe(text, voice=voice, speed=max(0.5, min(2.0, speed))):
                audio = result[2] if isinstance(result, tuple) else getattr(result, "audio", None)
                if audio is not None:
                    if hasattr(audio, "detach"):  # torch tensor (possibly on the GPU)
                        audio = audio.detach().cpu().numpy()
                    chunks.append(np.asarray(audio, dtype=np.float32).reshape(-1))
        if not chunks:
            return b""
        return float32_to_wav(np.concatenate(chunks), 24000)

    def _load_piper(self, voice_name: str):
        if not voice_name:
            raise TTSError("No Piper voice selected for this language (Settings → Voice).")
        if voice_name in self._piper:
            return self._piper[voice_name]
        path = self.voices_dir / f"{voice_name}.onnx"
        if not path.exists():
            raise TTSError(f"Piper voice '{voice_name}' is not downloaded (Settings → Voice).")
        from piper import PiperVoice
        v = PiperVoice.load(str(path))
        self._piper[voice_name] = v
        return v

    def cleanup_cache(self, max_age_days: int = 30) -> None:
        cutoff = time.time() - max_age_days * 86400
        for p in self.cache_dir.glob("*.wav"):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
            except OSError:
                pass
