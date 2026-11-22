"""Speech-to-text with Whisper. Prefers mlx-whisper on Apple Silicon, falls back to faster-whisper."""
from __future__ import annotations

import importlib.util
import platform
import re
import threading
from typing import Callable

from .audio import rms, wav_to_float32

# Whisper famously "hears" these on silence/noise (they come from subtitle training data).
HALLUCINATIONS = [
    "tack för att du tittade", "tack för att ni tittade", "tack för att ni har tittat", "textning",
    "undertexter", "svensktextning", "sous-titrage", "sous-titres", "merci d'avoir regardé",
    "thanks for watching", "thank you for watching", "subtitles by", "amara.org", "you",
    "musique", "music", "applause", "...",
]


def _has(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


class STTManager:
    def __init__(self, settings_getter: Callable[[], dict]):
        self._settings = settings_getter
        self._lock = threading.Lock()
        self._faster_models: dict[str, object] = {}

    @property
    def cfg(self) -> dict:
        return self._settings()["stt"]

    def available_backends(self) -> dict[str, bool]:
        is_apple = platform.system() == "Darwin" and platform.machine() == "arm64"
        return {"mlx": is_apple and _has("mlx_whisper"), "faster": _has("faster_whisper")}

    def backend(self) -> str | None:
        want = self.cfg.get("backend", "auto")
        avail = self.available_backends()
        if want == "off":
            return None
        if want in avail:
            return want if avail[want] else None
        for name in ("mlx", "faster"):
            if avail[name]:
                return name
        return None

    def model_for(self, language: str | None) -> str:
        override = (self.cfg.get("models") or {}).get(language or "", "")
        model = override or self.cfg.get("model") or "mlx-community/whisper-large-v3-turbo"
        if self.backend() == "faster" and model.startswith("mlx-community/"):
            # mlx repos can't be loaded by faster-whisper; use the equivalent CTranslate2 model
            model = "large-v3-turbo" if "turbo" in model else "large-v3"
        return model

    def status(self) -> dict:
        b = self.backend()
        return {"backend": b, "available": b is not None, "backends": self.available_backends(),
                "model": self.model_for(None) if b else None}

    def preload(self, language: str | None = None) -> None:
        """Load the model in the background (first load downloads it)."""
        import numpy as np
        try:
            self._run(np.zeros(16000, dtype="float32"), language, None)
        except Exception:
            pass

    def transcribe(self, wav: bytes, language: str | None, prompt: str | None = None) -> dict:
        audio = wav_to_float32(wav, 16000)
        if len(audio) < 16000 * 0.25 or rms(audio) < 0.003:
            return {"text": "", "language": language, "reason": "too short or silent"}
        text, lang, words = self._run(audio, language, prompt, word_timestamps=True)
        text = clean_transcript(text)
        return {"text": text, "language": lang or language, "words": words if text else []}

    def _run(self, audio, language: str | None, prompt: str | None,
             word_timestamps: bool = False) -> tuple[str, str | None, list[dict]]:
        backend = self.backend()
        if backend is None:
            raise RuntimeError("No speech recognition backend installed. On a Mac run: pip install mlx-whisper")
        model = self.model_for(language)
        with self._lock:
            if backend == "mlx":
                import mlx_whisper
                res = mlx_whisper.transcribe(
                    audio, path_or_hf_repo=model, language=language,
                    initial_prompt=prompt or None, condition_on_previous_text=False,
                    no_speech_threshold=0.6, verbose=None, word_timestamps=word_timestamps)
                words = [{"word": w.get("word", "").strip(), "p": round(float(w.get("probability", 1.0)), 3)}
                         for seg in res.get("segments", []) for w in (seg.get("words") or [])]
                return res.get("text", ""), res.get("language"), words
            from faster_whisper import WhisperModel
            m = self._faster_models.get(model)
            if m is None:
                m = WhisperModel(model, device="auto", compute_type="int8")
                self._faster_models = {model: m}
            segments, info = m.transcribe(audio, language=language, initial_prompt=prompt or None,
                                          vad_filter=True, condition_on_previous_text=False,
                                          word_timestamps=word_timestamps)
            segments = list(segments)
            words = [{"word": w.word.strip(), "p": round(float(w.probability), 3)}
                     for seg in segments for w in (seg.words or [])]
            return " ".join(seg.text for seg in segments), getattr(info, "language", None), words


def clean_transcript(text: str) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    simple = re.sub(r"[^\w\s']", "", t.lower()).strip()
    if not simple:
        return ""
    for h in HALLUCINATIONS:
        hs = re.sub(r"[^\w\s']", "", h).strip()
        if hs and (simple == hs or (len(simple) < 60 and simple.startswith(hs) and hs != "you")):
            return ""
    return t
