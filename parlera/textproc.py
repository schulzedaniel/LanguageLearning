"""Text utilities for speech: sentence streaming, markdown stripping, language routing.

The tutor is instructed to wrap every target-language word/phrase in **bold**.
We use that (plus a language detector as a safety net) to send each piece of a
reply to the right voice, e.g.:

    "Hello is **hej**. Try: **Hej, jag heter Sam.**"
    -> [("en", "Hello is"), ("sv", "hej."), ("en", "Try:"), ("sv", "Hej, jag heter Sam.")]
"""
from __future__ import annotations

import re
from functools import lru_cache

EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF️‍←-⇿]"
)
CORRECTION_MARK = "✏️"
ABBREVIATIONS = ("t.ex.", "bl.a.", "dvs.", "osv.", "etc.", "e.g.", "i.e.", "mr.", "mrs.", "dr.",
                 "m.", "mme.", "mlle.", "p.ex.", "ca.", "st.", "nr.", "vs.", "ex.")
END_PUNCT = ".!?…"
TRAILING_CLOSERS = "\"'»”’)*]"


def strip_for_speech(text: str) -> str:
    t = text or ""
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.M)
    t = re.sub(r"^\s*>\s?", "", t, flags=re.M)
    t = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", t, flags=re.M)
    t = t.replace("**", "").replace("__", "")
    t = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", r"\1", t)
    t = re.sub(r"(?<![\w_])_(?!\s)([^_\n]+?)(?<!\s)_(?![\w_])", r"\1", t)
    t = t.replace("→", ", ").replace("–", ", ").replace("—", ", ")
    t = EMOJI_RE.sub("", t)
    t = re.sub(r"\s+([,.!?;:])", r"\1", t)
    t = re.sub(r"(,\s*){2,}", ", ", t)
    t = re.sub(r"\s+", " ", t).strip(" ,")
    return t


class SentenceStream:
    """Accumulates streamed tokens and yields complete sentences.

    Never splits inside **bold** spans. Each emitted item is ``(text, is_correction)``
    where ``is_correction`` is True for sentences on a line starting with ✏️.
    """

    def __init__(self, min_chars: int = 8):
        self.buf = ""
        self.min_chars = min_chars
        self.line_is_correction = False

    def feed(self, text: str) -> list[tuple[str, bool]]:
        self.buf += text
        out: list[tuple[str, bool]] = []
        while True:
            cut = self._boundary()
            if cut is None:
                break
            piece, self.buf = self.buf[:cut], self.buf[cut:]
            ends_line = piece.endswith("\n")
            self._emit(piece, out)
            if ends_line:
                self.line_is_correction = False
        return out

    def flush(self) -> list[tuple[str, bool]]:
        out: list[tuple[str, bool]] = []
        self._emit(self.buf, out)
        self.buf = ""
        self.line_is_correction = False
        return out

    def _emit(self, piece: str, out: list) -> None:
        s = piece.strip()
        if not s:
            return
        if s.lstrip("> ").startswith(CORRECTION_MARK):
            self.line_is_correction = True
        out.append((s, self.line_is_correction))

    def _boundary(self) -> int | None:
        buf = self.buf
        bold = False
        i, n = 0, len(buf)
        while i < n:
            if buf.startswith("**", i):
                bold = not bold
                i += 2
                continue
            c = buf[i]
            if c == "\n":
                if buf[:i].strip():
                    return i + 1
                i += 1
                continue
            if c.isspace() and not bold:
                head = buf[:i].rstrip()
                core = head.rstrip(TRAILING_CLOSERS)
                if core and core[-1] in END_PUNCT and len(head.strip()) >= self.min_chars:
                    low = core.lower()
                    if not any(low.endswith(" " + a) or low == a for a in ABBREVIATIONS):
                        return i + 1
            i += 1
        return None


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------
STOPWORDS = {
    "en": set("the a an and is are was were i you he she it we they to of in on for with that this "
              "what how do does did not no yes my your can will would say means word try good great "
              "let's lets now here there very nice so but or if just like".split()),
    "fr": set("le la les un une des et est sont je tu il elle nous vous ils elles de du au aux en "
              "que qui ne pas oui non mon ma mes ton ta tes avec pour dans sur ce cette c'est très "
              "bien merci bonjour suis es sommes êtes ont avez ai as je m'appelle".split()),
    "sv": set("och är jag du han hon vi ni de det en ett att som på i med för inte ja nej min mitt "
              "mina din ditt har heter vad var hur kan vill ska till från av om men eller så bra "
              "tack hej mycket också här där den detta".split()),
}
DIACRITICS = {"fr": set("éèêëàâçùûîïôœ"), "sv": set("åäö"), "en": set()}

_LINGUA_CODES = {"en": "ENGLISH", "fr": "FRENCH", "sv": "SWEDISH"}


@lru_cache(maxsize=8)
def _lingua_detector(target: str):
    try:
        from lingua import Language, LanguageDetectorBuilder
    except ImportError:
        return None
    try:
        langs = [getattr(Language, _LINGUA_CODES["en"]), getattr(Language, _LINGUA_CODES[target])]
        return LanguageDetectorBuilder.from_languages(*langs).build()
    except Exception:
        return None


def _heuristic_scores(text: str, target: str) -> tuple[float, float]:
    words = re.findall(r"[\w']+", text.lower())
    en = sum(1 for w in words if w in STOPWORDS["en"])
    tg = sum(1 for w in words if w in STOPWORDS.get(target, set()))
    tg += 1.5 * sum(1 for ch in text.lower() if ch in DIACRITICS.get(target, set()))
    return en, tg


def detect_language(text: str, target: str, prefer: str) -> str:
    """Return 'en' or the target code for a piece of text."""
    words = re.findall(r"[\w']+", text)
    if not words:
        return prefer
    en, tg = _heuristic_scores(text, target)
    if len(words) <= 2:
        if tg > en:
            return target
        if en > tg:
            return "en"
        return prefer
    det = _lingua_detector(target)
    if det is not None:
        try:
            vals = {cv.language.name: cv.value for cv in det.compute_language_confidence_values(text)}
            p_en = vals.get(_LINGUA_CODES["en"], 0.0)
            p_tg = vals.get(_LINGUA_CODES[target], 0.0)
            if abs(p_en - p_tg) > 0.2:
                return "en" if p_en > p_tg else target
        except Exception:
            pass
    if tg > en:
        return target
    if en > tg:
        return "en"
    return prefer


def segment_languages(text: str, target: str) -> list[dict]:
    """Split one sentence of tutor output into [{lang, text}] chunks for TTS."""
    if target == "en":  # studying English: everything is spoken by the English voice
        clean = strip_for_speech(text)
        return [{"lang": "en", "text": clean}] if re.search(r"\w", clean) else []
    parts = re.split(r"(\*\*.+?\*\*)", text, flags=re.S)
    segs: list[dict] = []
    for part in parts:
        if not part:
            continue
        is_bold = part.startswith("**") and part.endswith("**") and len(part) > 4
        clean = strip_for_speech(part[2:-2] if is_bold else part)
        if not clean or not re.search(r"\w", clean):
            if clean and segs:
                segs[-1]["text"] = (segs[-1]["text"] + clean).strip()
            continue
        lang = detect_language(clean, target, prefer=target if is_bold else "en")
        if segs and segs[-1]["lang"] == lang:
            segs[-1]["text"] = f"{segs[-1]['text']} {clean}".strip()
        else:
            segs.append({"lang": lang, "text": clean})
    return segs


def target_words(text: str) -> list[str]:
    """Extract the bold (target-language) snippets from a tutor message."""
    return [strip_for_speech(m) for m in re.findall(r"\*\*(.+?)\*\*", text or "", flags=re.S)]
