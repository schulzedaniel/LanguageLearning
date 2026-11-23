"""Practice page: items for the quick games (no LLM needed) and practice statistics.

Games run in the browser; the server only supplies a pool of items and records results.
An item is a word, phrase or corrected mistake::

    {key, term, bare, meaning, gender, kind: word|phrase|fix, example, example_translation,
     vocab_id, unit_id, cloze: {before, answer, after, hint} | None, wrong (fix only)}
"""
from __future__ import annotations

import random
import re
import unicodedata
from datetime import datetime
from typing import Any

from .anki import display_word
from .db import norm, now

GAMES = ("flashcards", "match", "choice", "cloze", "scramble", "typing", "gender", "fix")
SOURCES = ("unit", "vocab", "mix", "misses", "errors")

_GENDER_ARTICLES = {
    "sv": (("en ", "en"), ("ett ", "ett")),
    "fr": (("le ", "m"), ("un ", "m"), ("la ", "f"), ("une ", "f")),
}
_STRIP_ARTICLES = {
    "sv": ("en ", "ett ", "att "),
    "fr": ("le ", "la ", "les ", "un ", "une ", "des ", "l'", "l’"),
    "en": ("a ", "an ", "the ", "to "),
}
_WORD_RE = re.compile(r"[\wÀ-ÿ'’-]+", re.UNICODE)


def _fold(s: str) -> str:
    """Lowercase without accents, for forgiving comparisons."""
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def split_article(term: str, lang: str) -> tuple[str, str, str]:
    """'en bil' -> ('en', 'bil', 'en'); 'la maison' -> ('la', 'maison', 'f'); returns (article, bare, gender)."""
    t = (term or "").strip()
    low = t.lower()
    for art, gender in _GENDER_ARTICLES.get(lang, ()):
        if low.startswith(art) and len(t) > len(art) + 1:
            return art.strip(), t[len(art):].strip(), gender
    for art in _STRIP_ARTICLES.get(lang, ()):
        if low.startswith(art) and len(t) > len(art) + 1:
            return art.strip(), t[len(art):].strip(), ""
    return "", t, ""


def cloze(sentence: str, word: str, lang: str = "") -> dict | None:
    """Blank out `word` (or an inflected form of it) in `sentence`.

    Multi-word terms must appear literally; single words may match a form that starts
    with the same stem (springa → springer, maison → maisons)."""
    sentence = (sentence or "").strip()
    word = (word or "").strip()
    if not sentence or not word or "…" in sentence or len(sentence) > 220:
        return None
    fs, fw = _fold(sentence), _fold(word)
    if " " in word:
        i = fs.find(fw)
        if i < 0:
            return None
        return {"before": sentence[:i], "answer": sentence[i:i + len(word)], "after": sentence[i + len(word):]}
    stem = fw if len(fw) < 5 else fw[:max(4, len(fw) - 2)]
    best = None
    for m in _WORD_RE.finditer(sentence):
        tok = _fold(m.group(0))
        if tok == fw:
            best = m
            break
        if best is None and len(fw) >= 3 and tok.startswith(stem) and len(tok) - len(fw) <= (4 if len(fw) >= 4 else 3):
            best = m
    if not best:
        return None
    return {"before": sentence[:best.start()], "answer": best.group(0), "after": sentence[best.end():]}


def phrase_cloze(phrase: str, lang: str, prefer: set[str] | None = None) -> dict | None:
    """Blank a meaningful word in a phrase: a known vocabulary word if possible, else the longest word."""
    if not phrase or "…" in phrase or "..." in phrase:
        return None
    words = [m.group(0) for m in _WORD_RE.finditer(phrase) if len(m.group(0)) >= 3]
    if len(words) < 2:
        return None
    prefer = prefer or set()
    known = [w for w in words if _fold(w) in prefer]
    pick = max(known, key=len) if known else max(words, key=len)
    return cloze(phrase, pick, lang)


def scramble_ok(sentence: str) -> bool:
    n = len((sentence or "").split())
    return 3 <= n <= 10 and "…" not in sentence and "..." not in sentence and "/" not in sentence


def _item(lang: str, term: str, meaning: str, kind: str, **extra) -> dict:
    art, bare, gender = split_article(term, lang)
    it = {"key": norm(term), "term": term.strip(), "bare": bare, "meaning": (meaning or "").strip(),
          "gender": gender, "kind": kind, "example": "", "example_translation": "", "vocab_id": None,
          "unit_id": None, "cloze": None}
    it.update({k: v for k, v in extra.items() if v not in (None, "")})
    return it


def unit_items(curriculum: dict, unit: dict | None, lang: str, span: int = 4) -> list[dict]:
    """Vocabulary and phrases of the current unit and the few units before it."""
    units = curriculum.get("units", [])
    idx = unit["index"] if unit else 0
    chosen = [u for u in units if idx - span < u["index"] <= idx] or units[:1]
    items: list[dict] = []
    for u in chosen:
        bare_words = {_fold(split_article(p["term"], lang)[1]) for p in u.get("vocab_pairs", [])}
        for p in u.get("vocab_pairs", []):
            if p["term"] and p["meaning"]:
                items.append(_item(lang, p["term"], p["meaning"], "word", unit_id=u["id"],
                                   current=u["index"] == idx))
        for p in u.get("phrase_pairs", []):
            if p["term"] and p["meaning"] and "…" not in p["term"]:
                it = _item(lang, p["term"], p["meaning"], "phrase", unit_id=u["id"], current=u["index"] == idx,
                           example=p["term"], example_translation=p["meaning"])
                it["bare"] = p["term"]
                c = phrase_cloze(p["term"], lang, bare_words)
                if c:
                    it["cloze"] = {**c, "hint": p["meaning"]}
                items.append(it)
    return items


def vocab_items(db, lang: str, limit: int = 300) -> list[dict]:
    rows = db.all("SELECT * FROM vocab WHERE language=? AND status IN ('learning','known','candidate') "
                  "AND translation != '' ORDER BY created_at DESC LIMIT ?", [lang, limit])
    items = []
    for v in rows:
        term = display_word(v)
        it = _item(lang, term, v["translation"], "phrase" if " " in v["lemma"].strip() else "word",
                   vocab_id=v["id"], unit_id=v.get("unit_id"), example=v.get("example") or "",
                   example_translation=v.get("example_translation") or "")
        if v.get("gender") in ("en", "ett", "m", "f"):
            it["gender"] = v["gender"]
        it["bare"] = v["lemma"]
        c = cloze(it["example"], v["lemma"], lang)
        if c:
            it["cloze"] = {**c, "hint": it["example_translation"] or v["translation"]}
        items.append(it)
    return items


def error_items(db, lang: str, limit: int = 40) -> list[dict]:
    rows = db.all("SELECT * FROM errors WHERE language=? AND example_wrong != '' AND example_right != '' "
                  "AND example_wrong != example_right ORDER BY resolved ASC, last_seen DESC LIMIT ?", [lang, limit])
    return [{"key": norm(r["example_right"]), "term": r["example_right"], "bare": r["example_right"],
             "wrong": r["example_wrong"], "meaning": r["explanation"] or r["pattern"], "pattern": r["pattern"],
             "gender": "", "kind": "fix", "example": "", "example_translation": "", "vocab_id": None,
             "unit_id": None, "cloze": None} for r in rows]


def misses(db, lang: str, limit: int = 60) -> list[dict]:
    return db.all("SELECT * FROM practice_items WHERE language=? AND wrong > 0 AND streak < 2 "
                  "ORDER BY last_wrong DESC LIMIT ?", [lang, limit])


def build_pool(core, lang: str, source: str = "mix", count: int = 40, seed: int | None = None) -> dict:
    """A shuffled pool of practice items (more than one round, so games have distractors)."""
    source = source if source in SOURCES else "mix"
    rng = random.Random(seed)
    cur = core.curricula.get(lang)
    unit = core.current_unit(lang)
    units = unit_items(cur, unit, lang)
    vocab = vocab_items(core.db, lang)
    if source == "errors":
        pool = error_items(core.db, lang)
    elif source == "misses":
        by_key = {it["key"]: it for it in units + vocab}
        pool = []
        for m in misses(core.db, lang):
            pool.append(by_key.get(m["term_norm"]) or _item(lang, m["term"], m["meaning"], "word",
                                                            vocab_id=m["vocab_id"]))
    elif source == "unit":
        current = [i for i in units if i.get("current")]
        rest = [i for i in units if not i.get("current")]
        rng.shuffle(current)
        rng.shuffle(rest)
        pool = current + rest
    elif source == "vocab":
        pool = vocab
    else:  # mix: recent vocabulary + current unit + a few older unit items
        recent = vocab[:80]
        rng.shuffle(recent)
        current = [i for i in units if i.get("current")]
        rest = [i for i in units if not i.get("current")]
        rng.shuffle(current)
        rng.shuffle(rest)
        pool = recent[:count // 2] + current + rest
    seen: set[str] = set()
    out = []
    for it in pool:
        if it["key"] in seen or not it["meaning"]:
            continue
        seen.add(it["key"])
        out.append(it)
    if source not in ("unit",):
        rng.shuffle(out)
    # distractor pool for multiple choice / matching (other items of the language)
    extra = [{"term": i["term"], "meaning": i["meaning"], "gender": i["gender"], "kind": i["kind"]}
             for i in (units + vocab) if i["key"] not in seen][:120]
    return {"language": lang, "source": source, "items": out[:max(count, 4)], "distractors": extra,
            "unit": {"id": unit["id"], "title": unit["title"], "level": unit["level"]} if unit else None,
            "counts": {"unit": len(units), "vocab": len(vocab), "misses": len(misses(core.db, lang)),
                       "errors": len(error_items(core.db, lang))}}


def record_results(db, lang: str, game: str, source: str, results: list[dict], seconds: int = 0) -> dict:
    """Store a finished round: the log entry and per-item statistics (for "Your misses")."""
    ts = now()
    score = sum(1 for r in results if r.get("correct"))
    db.insert("practice_log", {"language": lang, "game": game if game in GAMES else "other",
                               "source": source or "", "score": score, "total": len(results),
                               "seconds": max(0, min(int(seconds or 0), 4 * 3600)), "created_at": ts})
    for r in results:
        term = str(r.get("term") or "").strip()
        if not term:
            continue
        key = norm(term)
        ok = bool(r.get("correct"))
        row = db.one("SELECT * FROM practice_items WHERE language=? AND term_norm=?", [lang, key])
        if row:
            db.execute("UPDATE practice_items SET seen=seen+1, wrong=wrong+?, streak=?, last_seen=?, "
                       "last_wrong=COALESCE(?, last_wrong), meaning=COALESCE(NULLIF(?, ''), meaning) "
                       "WHERE language=? AND term_norm=?",
                       [0 if ok else 1, row["streak"] + 1 if ok else 0, ts, None if ok else ts,
                        str(r.get("meaning") or ""), lang, key])
        else:
            db.insert("practice_items", {"language": lang, "term_norm": key, "term": term[:300],
                                         "meaning": str(r.get("meaning") or "")[:300],
                                         "vocab_id": r.get("vocab_id"), "seen": 1, "wrong": 0 if ok else 1,
                                         "streak": 1 if ok else 0, "last_seen": ts,
                                         "last_wrong": None if ok else ts})
    return {"score": score, "total": len(results), "stats": stats(db, lang)}


def stats(db, lang: str) -> dict:
    today = datetime.now().date().isoformat()
    week = db.one("SELECT COUNT(*) AS rounds, COALESCE(SUM(score),0) AS score, COALESCE(SUM(total),0) AS total, "
                  "COALESCE(SUM(seconds),0) AS seconds FROM practice_log WHERE language=? "
                  "AND created_at >= date('now', 'localtime', '-6 days')", [lang]) or {}
    return {
        "today": db.scalar("SELECT COUNT(*) FROM practice_log WHERE language=? AND substr(created_at,1,10)=?",
                           [lang, today]) or 0,
        "week_rounds": week.get("rounds", 0), "week_score": week.get("score", 0),
        "week_total": week.get("total", 0), "week_minutes": round((week.get("seconds") or 0) / 60),
        "misses": db.scalar("SELECT COUNT(*) FROM practice_items WHERE language=? AND wrong > 0 AND streak < 2",
                            [lang]) or 0,
        "last": db.all("SELECT game, source, score, total, created_at FROM practice_log WHERE language=? "
                       "ORDER BY created_at DESC LIMIT 5", [lang]),
    }


def grammar_topics(curriculum: dict, unit: dict | None) -> list[dict]:
    """Grammar points from the curriculum, grouped by level, up to one level above the current one."""
    from .curriculum import LEVEL_ORDER
    cur_level = unit["level"] if unit else "A1"
    max_rank = LEVEL_ORDER.index(cur_level) + 1 if cur_level in LEVEL_ORDER else 99
    out: dict[str, list[dict[str, Any]]] = {}
    for u in curriculum.get("units", []):
        if u["level"] in LEVEL_ORDER and LEVEL_ORDER.index(u["level"]) > max_rank:
            continue
        for g in u.get("grammar", []):
            out.setdefault(u["level"], []).append({"topic": str(g), "unit_id": u["id"], "unit_title": u["title"],
                                                   "current": bool(unit and u["id"] == unit["id"]),
                                                   "done": bool(unit and u["index"] < unit["index"])})
    return [{"level": lv, "topics": ts} for lv, ts in out.items()]
