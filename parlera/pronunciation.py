"""Pronunciation hints from speech recognition.

The language model only ever sees text, so it cannot hear an accent. Two signals in the
transcript still carry real pronunciation information:

1. Whisper's per-word probability: words it was unsure about are often mispronounced
   (or mumbled / noisy).
2. Repetition mismatches: when the learner repeats a phrase the tutor modelled in **bold**,
   differences between the target and what Whisper heard ("tjugo" -> "chugo") point at
   specific problem words.

Both become a short note appended to the learner's message for the tutor, and are shown in
the UI. This is a heuristic, not phoneme-level scoring.
"""
from __future__ import annotations

import difflib
import re

from .textproc import target_words

WORD_RE = re.compile(r"[\w'’-]+", re.UNICODE)


def _norm_words(text: str) -> list[str]:
    return [w.lower().strip("'’-") for w in WORD_RE.findall(text or "") if w.strip("'’-")]


def low_confidence(words: list[dict], threshold: float = 0.55) -> list[dict]:
    out = []
    for w in words or []:
        token = (w.get("word") or "").strip(" .,!?;:\"'«»")
        if len(token) >= 2 and re.search(r"\w", token) and float(w.get("p", 1.0)) < threshold:
            out.append({"word": token, "p": float(w["p"])})
    return out


def repetition_mismatches(heard: str, tutor_text: str) -> dict | None:
    """If the learner seems to be repeating a bold phrase from the tutor, return the differences."""
    heard_w = _norm_words(heard)
    if not heard_w:
        return None
    best, best_ratio = None, 0.0
    for phrase in target_words(tutor_text):
        exp_w = _norm_words(phrase.replace("…", " "))
        if len(exp_w) < 1:
            continue
        ratio = difflib.SequenceMatcher(None, exp_w, heard_w).ratio()
        if ratio > best_ratio:
            best, best_ratio = (phrase, exp_w), ratio
    if not best or best_ratio < 0.5:
        return None          # not an attempt to repeat a modelled phrase
    phrase, exp_w = best
    diffs = []
    sm = difflib.SequenceMatcher(None, exp_w, heard_w)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        diffs.append({"expected": " ".join(exp_w[i1:i2]), "heard": " ".join(heard_w[j1:j2])})
    if not diffs:
        return None
    return {"phrase": phrase, "diffs": diffs[:5]}


def build_note(low: list[dict], rep: dict | None) -> str:
    parts = []
    if rep:
        d = "; ".join(
            (f'"{x["expected"]}" sounded like "{x["heard"]}"' if x["expected"] and x["heard"]
             else f'"{x["expected"]}" was missing' if x["expected"] else f'extra "{x["heard"]}"')
            for x in rep["diffs"])
        parts.append(f'they were repeating "{rep["phrase"]}": {d}')
    if low:
        parts.append("the recognizer was unsure about " + ", ".join(f'"{w["word"]}" ({round(w["p"] * 100)}%)' for w in low[:6]))
    if not parts:
        return ""
    return ("[Pronunciation hint from the speech recognizer, not said by the learner: "
            + "; ".join(parts) + ". This may indicate pronunciation problems (or just noise). "
            "If it concerns target-language words, give one short, concrete pronunciation tip.]")


def analyse(words: list[dict], heard: str, last_tutor_text: str, threshold: float) -> dict:
    low = low_confidence(words, threshold)
    rep = repetition_mismatches(heard, last_tutor_text or "")
    return {"low": low, "rep": rep, "note": build_note(low, rep)}
