"""Application core: wires together storage, curriculum, prompts, LLM, speech and Anki,
and implements the learning logic (context building, analysis, progression, vocab)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .anki import AnkiConnect, AnkiError, deck_name, display_word, note_fields, note_tags
from .config import DEFAULT_SETTINGS, LANGUAGES, Paths, Settings
from .curriculum import LEVEL_ORDER, Curricula
from .db import DB, norm, now
from .llm import OllamaClient
from .practice import split_article
from .prompts import MODES, PromptStore
from .stt import STTManager
from .tts import TTSManager

log = logging.getLogger("parlera")

# ---------------------------------------------------------------------------
# JSON schemas for structured output (Ollama `format`)
# ---------------------------------------------------------------------------
ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "feedback": {"type": "string"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "focus_next": {"type": "array", "items": {"type": "string"}},
        "errors": {"type": "array", "items": {"type": "object", "properties": {
            "pattern": {"type": "string"}, "category": {"type": "string"},
            "wrong": {"type": "string"}, "right": {"type": "string"},
            "explanation": {"type": "string"}},
            "required": ["pattern", "category", "wrong", "right", "explanation"]}},
        "memories": {"type": "array", "items": {"type": "object", "properties": {
            "content": {"type": "string"}, "category": {"type": "string"}},
            "required": ["content", "category"]}},
        "can_do": {"type": "array", "items": {"type": "object", "properties": {
            "goal": {"type": "string"}, "score": {"type": "number"}}, "required": ["goal", "score"]}},
        "unit_mastery": {"type": "number"},
        "ready_to_advance": {"type": "boolean"},
        "cefr_estimate": {"type": "string"},
        "recommended_unit_id": {"type": "string"},
        "exam_score": {"type": "number"},
        "exam_max": {"type": "number"},
        "exam_breakdown": {"type": "string"},
        "mastered_patterns": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "summary", "feedback", "strengths", "focus_next", "errors", "memories",
                 "can_do", "unit_mastery", "ready_to_advance", "cefr_estimate",
                 "recommended_unit_id", "exam_score", "exam_max", "exam_breakdown", "mastered_patterns"],
}

VOCAB_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
        "lemma": {"type": "string"}, "translation": {"type": "string"}, "pos": {"type": "string"},
        "gender": {"type": "string"}, "forms": {"type": "string"}, "example": {"type": "string"},
        "example_translation": {"type": "string"}, "reason": {"type": "string"}, "notes": {"type": "string"}},
        "required": ["lemma", "translation", "pos", "gender", "forms", "example",
                     "example_translation", "reason", "notes"]}}},
    "required": ["items"],
}

WORKSHOP_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "overview": {"type": "string"},
        "categories": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "rule": {"type": "string"}, "why": {"type": "string"},
            "examples": {"type": "array", "items": {"type": "object", "properties": {
                "wrong": {"type": "string"}, "right": {"type": "string"}}, "required": ["wrong", "right"]}},
            "tip": {"type": "string"}, "patterns": {"type": "array", "items": {"type": "string"}}},
            "required": ["name", "rule", "why", "examples", "tip", "patterns"]}},
        "plan": {"type": "string"},
    },
    "required": ["title", "overview", "categories", "plan"],
}

NOTE_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
        "content": {"type": "string"}, "kind": {"type": "string"}, "days": {"type": "integer"},
        "all_languages": {"type": "boolean"}}, "required": ["content", "kind", "days", "all_languages"]}}},
    "required": ["items"],
}

AUTOFILL_SCHEMA = {
    "type": "object",
    "properties": {k: {"type": "string"} for k in
                   ("lemma", "translation", "pos", "gender", "forms", "example", "example_translation", "notes")},
    "required": ["lemma", "translation", "pos", "gender", "forms", "example", "example_translation", "notes"],
}

_STR = {"type": "string"}
LECTURE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": _STR, "summary": _STR, "mechanism": _STR,
        "steps": {"type": "array", "items": {"type": "object", "properties": {
            "heading": _STR, "explanation": _STR,
            "examples": {"type": "array", "items": {"type": "object", "properties": {
                "target": _STR, "native": _STR, "note": _STR}, "required": ["target", "native", "note"]}}},
            "required": ["heading", "explanation", "examples"]}},
        "table": {"type": "object", "properties": {
            "caption": _STR, "columns": {"type": "array", "items": _STR},
            "rows": {"type": "array", "items": {"type": "array", "items": _STR}}},
            "required": ["caption", "columns", "rows"]},
        "contrast": _STR,
        "mistakes": {"type": "array", "items": {"type": "object", "properties": {
            "wrong": _STR, "right": _STR, "why": _STR}, "required": ["wrong", "right", "why"]}},
        "tips": {"type": "array", "items": _STR},
        "quiz": {"type": "array", "items": {"type": "object", "properties": {
            "question": _STR, "options": {"type": "array", "items": _STR}, "answer": _STR, "explanation": _STR},
            "required": ["question", "options", "answer", "explanation"]}},
        "speaking_task": _STR,
    },
    "required": ["title", "summary", "mechanism", "steps", "table", "contrast", "mistakes", "tips", "quiz",
                 "speaking_task"],
}

REASON_PRIORITY = {"mistake": 0, "asked": 1, "unit": 2, "new": 3}
BREAK_NAMES = {"sv": "fika", "fr": "pause café", "en": "tea time"}
UNIT_MODES = {"lesson", "conversation", "roleplay", "review", "writing", "pronunciation"}


def _clamp01(x: Any) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 0.0


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


class Parlera:
    def __init__(self, root: Path | None = None):
        self.paths = Paths(root)
        self.context_version = 0   # bumped when instructions/memories/notes/prompts/settings change (tutor.py rebuilds)
        self.upgraded_defaults = self.paths.ensure()
        if self.upgraded_defaults:
            log.info("Updated unedited default files: %s", ", ".join(self.upgraded_defaults))
        self.settings = Settings(self.paths.settings)
        self.db = DB(self.paths.db)
        self.curricula = Curricula(self.paths.curricula)
        self.prompts = PromptStore(self.paths.prompts)
        self.llm = OllamaClient(self.settings.all)
        self.stt = STTManager(self.settings.all)
        self.tts = TTSManager(self.settings.all, self.paths.voices, self.paths.tts_cache)

    # ------------------------------------------------------------------
    # housekeeping
    # ------------------------------------------------------------------
    def daily_backup(self, keep: int = 14) -> Path | None:
        dest = self.paths.backups / f"parlera-{date.today().isoformat()}.db"
        if not dest.exists():
            self.db.backup_to(dest)
        if self.paths.settings.exists():  # settings snapshots, too
            shutil.copy2(self.paths.settings, self.paths.backups / "settings-latest.json")
            daily = self.paths.backups / f"settings-{date.today().isoformat()}.json"
            if not daily.exists():
                shutil.copy2(self.paths.settings, daily)
            for old in sorted(self.paths.backups.glob("settings-20*.json"))[:-keep]:
                old.unlink(missing_ok=True)
        backups = sorted(self.paths.backups.glob("parlera-*.db"))
        for old in backups[:-keep]:
            old.unlink(missing_ok=True)
        return dest

    async def release_analysis_model(self) -> None:
        """After analysis with a separate (big) model: free it and preload the conversation model again."""
        analysis = self.settings.get("llm.analysis_model") or ""
        if analysis and analysis != self.settings.get("llm.model") and self.settings.get("llm.exclusive_models", True):
            await self.llm.unload(analysis)
            asyncio.create_task(self.llm.warm())

    def teacher(self, language: str) -> dict:
        """The teacher's name and gender for a language (Settings → Your teachers)."""
        default = DEFAULT_SETTINGS["teachers"].get(language, {"name": "Alex", "gender": "female"})
        t = (self.settings.get("teachers") or {}).get(language) or {}
        name = str(t.get("name") or "").strip() or default["name"]
        gender = t.get("gender") if t.get("gender") in ("female", "male") else default["gender"]
        return {"name": name[:40], "gender": gender}

    def anki(self) -> AnkiConnect:
        return AnkiConnect(self.settings.get("anki.url"))

    # ------------------------------------------------------------------
    # learner state & curriculum progress
    # ------------------------------------------------------------------
    def learner(self, language: str) -> dict:
        first = self.curricula.first_unit(language)
        row = self.db.ensure_learner(language, first["id"])
        if not self.curricula.unit(language, row["current_unit_id"]):
            # curriculum edited and the unit vanished -> fall back to first unit
            self.db.update("learner", language, {"current_unit_id": first["id"]}, key="language")
            row = self.db.learner(language)
        return row

    def current_unit(self, language: str) -> dict:
        return self.curricula.unit(language, self.learner(language)["current_unit_id"])

    def set_current_unit(self, language: str, unit_id: str, complete_previous: bool = False) -> dict:
        unit = self.curricula.unit(language, unit_id)
        if not unit:
            raise ValueError(f"Unknown unit '{unit_id}'")
        self.learner(language)
        self.db.update("learner", language, {"current_unit_id": unit_id}, key="language")
        self.db.ensure_unit(language, unit_id)
        if complete_previous:
            for u in self.curricula.get(language)["units"][: unit["index"]]:
                self.db.ensure_unit(language, u["id"])
                self.db.execute("UPDATE unit_progress SET status='completed' WHERE language=? AND unit_id=?",
                                [language, u["id"]])
        return unit

    def set_unit_status(self, language: str, unit_id: str, status: str) -> None:
        self.db.ensure_unit(language, unit_id)
        self.db.execute("UPDATE unit_progress SET status=? WHERE language=? AND unit_id=?",
                        [status, language, unit_id])

    def advance(self, language: str) -> dict | None:
        cur = self.current_unit(language)
        self.set_unit_status(language, cur["id"], "completed")
        nxt = self.curricula.next_unit(language, cur["id"])
        if nxt:
            self.set_current_unit(language, nxt["id"])
        return nxt

    def is_monolingual(self, language: str) -> bool:
        """True when the studied language is also the explanation language (e.g. English)."""
        native = (self.settings.get("learner.native_language") or "English").strip().lower()
        return LANGUAGES.get(language, {}).get("name", "").lower() == native

    def immersion(self, language: str, unit: dict | None) -> int:
        setting = self.settings.get("conversation.immersion", "auto")
        if self.is_monolingual(language):
            return 100
        if str(setting).isdigit():
            return max(0, min(100, int(setting)))
        if not unit:
            return 50
        base = {"A1": 50, "A2": 70, "B1": 85, "B2": 95, "C1": 98, "C2": 100}.get(unit["level"], 60)
        level_units = [u for u in self.curricula.get(language)["units"] if u["level"] == unit["level"]]
        pos = next((i for i, u in enumerate(level_units) if u["id"] == unit["id"]), 0)
        span = {"A1": 20, "A2": 15, "B1": 10, "B2": 5}.get(unit["level"], 0)
        frac = pos / max(1, len(level_units) - 1)
        return int(min(100, base + span * frac))

    # ------------------------------------------------------------------
    # prompt context
    # ------------------------------------------------------------------
    def memories_for(self, language: str, limit: int = 40) -> list[dict]:
        return self.db.all(
            "SELECT * FROM memories WHERE active=1 AND (language IS NULL OR language=?) "
            "ORDER BY pinned DESC, updated_at DESC LIMIT ?", [language, limit])

    def weak_vocab(self, language: str, limit: int = 12) -> list[dict]:
        return self.db.all(
            "SELECT * FROM vocab WHERE language=? AND status='learning' AND "
            "((anki_lapses IS NOT NULL AND anki_lapses >= 2) OR (anki_reps > 0 AND anki_interval < 4)) "
            "ORDER BY anki_lapses DESC, anki_interval ASC LIMIT ?", [language, limit]) or self.db.all(
            "SELECT * FROM vocab WHERE language=? AND status='learning' ORDER BY updated_at DESC LIMIT ?",
            [language, min(limit, 8)])

    def reinforce_vocab(self, language: str, seed: int | None = None, exclude: set[int] | None = None) -> list[dict]:
        """Pick recently learned words for the tutor to weave in subtly.

        Each word gets a weight from how long ago it was added and how it's doing in Anki.
        A few words are sampled per session (the seed keeps the choice stable for one
        session) so different words come up in different sessions.

        Age: added today 0.4 (Anki shows it anyway), 1–21 days 1.0, 22–45 days 0.6,
        46–90 days 0.3, older ignored.
        Anki: not in Anki / not synced 0.7, never reviewed 0.5, interval ≤ 7 d 1.0,
        8–20 d 0.6, ≥ 21 d (mature) 0.15. Struggling words (lapses ≥ 2) are left to
        `weak_vocab`, which the tutor practises more directly.
        """
        if not self.settings.get("vocab.reinforce", True):
            return []
        import random
        limit = int(self.settings.get("vocab.reinforce_count", 6))
        rows = self.db.all("SELECT * FROM vocab WHERE language=? AND status IN ('learning','known')", [language])
        today = datetime.now()
        pool: list[tuple[float, dict]] = []
        for v in rows:
            if exclude and v["id"] in exclude:
                continue
            if (v.get("anki_lapses") or 0) >= 2:
                continue
            try:
                age = (today - _parse_ts(v["created_at"])).days
            except (TypeError, ValueError):
                continue
            if age > 90:
                continue
            w_age = 0.4 if age < 1 else 1.0 if age <= 21 else 0.6 if age <= 45 else 0.3
            interval, reps = v.get("anki_interval"), v.get("anki_reps")
            if v.get("anki_note_id") is None or interval is None:
                w_anki = 0.7
            elif not reps:
                w_anki = 0.5
            elif interval <= 7:
                w_anki = 1.0
            elif interval <= 20:
                w_anki = 0.6
            else:
                w_anki = 0.15
            pool.append((w_age * w_anki, v))
        rng = random.Random(seed)
        picked: list[dict] = []
        while pool and len(picked) < limit:
            total = sum(w for w, _ in pool)
            r, acc = rng.random() * total, 0.0
            for i, (w, v) in enumerate(pool):
                acc += w
                if acc >= r:
                    picked.append(v)
                    pool.pop(i)
                    break
        return picked

    # ------------------------------------------------------------------
    # mistake workshop
    # ------------------------------------------------------------------
    def workshop_for_session(self, session_id: int | None) -> dict | None:
        if not session_id:
            return None
        row = self.db.one("SELECT * FROM workshops WHERE session_id=?", [session_id])
        return json.loads(row["digest"]) if row else None

    def workshop_status(self, language: str) -> dict:
        last = self.db.one("SELECT * FROM workshops WHERE language=? ORDER BY created_at DESC LIMIT 1", [language])
        since = last["created_at"] if last else "0000"
        events = self.db.scalar("SELECT COUNT(*) FROM error_events WHERE language=? AND created_at > ?", [language, since])
        patterns = self.db.scalar("SELECT COUNT(DISTINCT error_id) FROM error_events WHERE language=? AND created_at > ?",
                                  [language, since])
        interval = int(self.settings.get("workshop.interval_days", 7))
        days = (datetime.now() - _parse_ts(last["created_at"])).days if last else None
        enough = events >= int(self.settings.get("workshop.min_mistakes", 3))
        return {"last": last["created_at"] if last else None, "days_since": days, "new_mistakes": events,
                "new_patterns": patterns, "due": enough and (days is None or days >= interval),
                "available": events > 0 or bool(self.recurring_errors(language, 1))}

    async def create_workshop(self, language: str) -> dict:
        """Summarise and categorise recent mistakes with the LLM, then open a workshop session."""
        last = self.db.one("SELECT created_at FROM workshops WHERE language=? ORDER BY created_at DESC LIMIT 1", [language])
        start = last["created_at"] if last else (datetime.now() - timedelta(days=30)).isoformat(timespec="seconds")
        rows = self.db.all(
            "SELECT e.pattern, e.category, e.explanation, e.count, e.resolved, ev.wrong, ev.right, ev.created_at "
            "FROM error_events ev JOIN errors e ON e.id = ev.error_id "
            "WHERE ev.language=? AND ev.created_at > ? ORDER BY ev.created_at", [language, start])
        if not rows:  # nothing new: train the unresolved recurring mistakes instead
            rows = [{"pattern": e["pattern"], "category": e["category"], "explanation": e["explanation"],
                     "count": e["count"], "resolved": 0, "wrong": e["example_wrong"], "right": e["example_right"],
                     "created_at": e["last_seen"]} for e in self.recurring_errors(language, 15)]
        if not rows:
            raise ValueError("No mistakes collected yet — have a few sessions (and press End & review) first.")
        grouped: dict[str, dict] = {}
        for r in rows:
            g = grouped.setdefault(r["pattern"], {"pattern": r["pattern"], "category": r["category"],
                                                  "explanation": r["explanation"], "total": r["count"], "examples": []})
            if r["wrong"] and len(g["examples"]) < 4:
                g["examples"].append({"wrong": r["wrong"], "right": r["right"]})
        ctx = self.build_context(language, "workshop")
        ctx["mistakes"] = sorted(grouped.values(), key=lambda g: -len(g["examples"]) - g["total"])
        ctx["period_start"] = start[:10]
        model = self.settings.get("llm.analysis_model") or None
        messages = [{"role": "system", "content": self.prompts.render("analysis_workshop", **ctx)},
                    {"role": "user", "content": "Create the workshop JSON now."}]
        think = bool(self.settings.get("workshop.thinking", True))
        try:
            digest = await self.llm.chat_json(messages, schema=WORKSHOP_SCHEMA, model=model, think=think or None)
        except Exception:
            if not think:
                raise
            digest = await self.llm.chat_json(messages, schema=WORKSHOP_SCHEMA, model=model, think=False)
        digest = {
            "title": str(digest.get("title") or "Mistake workshop"),
            "overview": str(digest.get("overview") or ""),
            "plan": str(digest.get("plan") or ""),
            "categories": [c for c in (digest.get("categories") or []) if isinstance(c, dict) and c.get("name")][:6],
            "mistake_count": len(rows),
        }
        await self.release_analysis_model()
        session = self.create_session(language, "workshop")
        title = f"Mistake workshop · {digest['title']}"[:120]
        self.db.update("sessions", session["id"], {"title": title})
        self.db.insert("workshops", {"language": language, "created_at": now(), "period_start": start,
                                     "period_end": now(), "digest": json.dumps(digest, ensure_ascii=False),
                                     "session_id": session["id"]})
        return self.db.session(session["id"])

    # ------------------------------------------------------------------
    # "Message your teacher": instructions outside sessions
    # ------------------------------------------------------------------
    def active_directives(self, language: str) -> list[dict]:
        return self.db.all(
            "SELECT * FROM directives WHERE active=1 AND (language IS NULL OR language=?) "
            "AND (expires_at IS NULL OR expires_at > ?) ORDER BY created_at", [language, now()])

    async def parse_teacher_note(self, language: str, text: str) -> list[dict]:
        """Turn a free-text note into concrete instructions with a suggested duration (the learner confirms)."""
        text = (text or "").strip()
        if not text:
            raise ValueError("The note is empty.")
        ctx = self.build_context(language, "free")
        ctx["note"] = text
        data = await self.llm.chat_json(
            [{"role": "system", "content": self.prompts.render("teacher_note", **ctx)},
             {"role": "user", "content": text}], schema=NOTE_SCHEMA)
        out = []
        for it in (data.get("items") or [])[:8]:
            if not isinstance(it, dict) or not str(it.get("content", "")).strip():
                continue
            days = it.get("days")
            try:
                days = int(days) if days not in (None, "", 0) else None
            except (TypeError, ValueError):
                days = None
            kind = it.get("kind") if it.get("kind") in ("behaviour", "focus", "vocabulary", "other") else "other"
            out.append({"content": str(it["content"]).strip(), "kind": kind,
                        "days": days if days is None else max(1, min(365, days)),
                        "all_languages": bool(it.get("all_languages"))})
        if not out:
            out = [{"content": text, "kind": "other", "days": 7, "all_languages": False}]
        return out

    def save_directives(self, language: str, items: list[dict], source_text: str = "") -> list[dict]:
        ts = datetime.now()
        for it in items:
            days = it.get("days")
            self.db.insert("directives", {
                "language": None if it.get("all_languages") else language, "kind": it.get("kind") or "other",
                "content": str(it.get("content", "")).strip()[:500], "source_text": source_text[:1000],
                "expires_at": (ts + timedelta(days=int(days))).isoformat(timespec="seconds") if days else None,
                "active": 1, "created_at": ts.isoformat(timespec="seconds")})
        return self.active_directives(language)

    # ------------------------------------------------------------------
    # Practice → Grammar lectures (reasoning model, stored for re-reading)
    # ------------------------------------------------------------------
    async def create_lecture(self, language: str, topic: str, unit_id: str | None = None) -> dict:
        topic = (topic or "").strip()[:200]
        if not topic:
            raise ValueError("Choose or type a grammar topic.")
        ctx = self.build_context(language, "free", unit_id)
        unit = self.curricula.unit(language, unit_id) if unit_id else None
        ctx.update(topic=topic, unit_title=unit["title"] if unit else "",
                   unit_vocab="; ".join(p["term"] for p in (unit or {}).get("vocab_pairs", [])[:20]))
        model = self.settings.get("llm.analysis_model") or None
        messages = [{"role": "system", "content": self.prompts.render("lecture_grammar", **ctx)},
                    {"role": "user", "content": f"Write the lecture on: {topic}"}]
        think = bool(self.settings.get("practice.lecture_thinking", True))
        try:
            data = await self.llm.chat_json(messages, schema=LECTURE_SCHEMA, model=model, think=think or None,
                                            temperature=0.3)
        except Exception:
            if not think:
                raise
            data = await self.llm.chat_json(messages, schema=LECTURE_SCHEMA, model=model, think=False,
                                            temperature=0.3)
        await self.release_analysis_model()
        content = clean_lecture(data, topic)
        ts = now()
        lid = self.db.insert("lectures", {"language": language, "topic": topic, "unit_id": unit_id or None,
                                          "level": ctx["level"], "content": json.dumps(content, ensure_ascii=False),
                                          "model": model or self.settings.get("llm.model") or "",
                                          "created_at": ts, "updated_at": ts})
        return self.lecture(lid)

    def lecture(self, lid: int) -> dict | None:
        row = self.db.one("SELECT * FROM lectures WHERE id=?", [lid])
        if not row:
            return None
        row["content"] = json.loads(row["content"])
        return row

    def lectures(self, language: str) -> list[dict]:
        rows = self.db.all("SELECT id, language, topic, unit_id, level, content, created_at FROM lectures "
                           "WHERE language=? ORDER BY created_at DESC", [language])
        for r in rows:
            c = json.loads(r.pop("content"))
            r["title"], r["summary"] = c.get("title", r["topic"]), c.get("summary", "")
        return rows

    async def ask_lecture(self, lid: int, question: str) -> dict:
        lec = self.lecture(lid)
        if not lec:
            raise ValueError("Lecture not found.")
        question = (question or "").strip()[:500]
        if not question:
            raise ValueError("Type a question.")
        ctx = self.build_context(lec["language"], "free", lec.get("unit_id"))
        ctx["lecture"] = lec["content"]
        msgs = [{"role": "system", "content": self.prompts.render("lecture_followup", **ctx)}]
        for qa in lec["content"].get("followups", [])[-4:]:
            msgs += [{"role": "user", "content": qa["q"]}, {"role": "assistant", "content": qa["a"]}]
        msgs.append({"role": "user", "content": question})
        answer = (await self.llm.chat(msgs, options={"temperature": 0.3})).strip()
        lec["content"].setdefault("followups", []).append({"q": question, "a": answer, "at": now()})
        self.db.update("lectures", lid, {"content": json.dumps(lec["content"], ensure_ascii=False),
                                         "updated_at": now()})
        return {"q": question, "a": answer}

    def recurring_errors(self, language: str, limit: int = 8) -> list[dict]:
        return self.db.all("SELECT * FROM errors WHERE language=? AND resolved=0 "
                           "ORDER BY count DESC, last_seen DESC LIMIT ?", [language, limit])

    def recent_summaries(self, language: str, exclude: int | None = None, limit: int = 3) -> list[dict]:
        return self.db.all("SELECT id, title, summary, mode, unit_id, created_at FROM sessions "
                           "WHERE language=? AND status='completed' AND summary != '' AND id != ? "
                           "ORDER BY created_at DESC LIMIT ?", [language, exclude or -1, limit])

    def exam_for_level(self, language: str, level: str) -> dict:
        lv = self.curricula.level(language, level) or {}
        return lv.get("exam") or {}

    def build_context(self, language: str, mode: str, unit_id: str | None = None, scenario: str = "",
                      focus: str = "", session_id: int | None = None) -> dict:
        settings = self.settings.all()
        cur = self.curricula.get(language)
        learner = self.learner(language)
        unit = self.curricula.unit(language, unit_id) or self.current_unit(language)
        progress = self.db.ensure_unit(language, unit["id"]) if unit else {}
        level = unit["level"] if unit else "A1"
        lang_info = LANGUAGES.get(language, {"name": language})
        immersion = self.immersion(language, unit)
        level_units = [u for u in cur["units"] if u["level"] == level]
        weak = self.weak_vocab(language)
        teacher = self.teacher(language)
        return {
            "teacher_name": teacher["name"],
            "teacher_gender": teacher["gender"],
            "language": language,
            "language_name": cur.get("name") or lang_info["name"],
            "native_language": settings["learner"].get("native_language") or "English",
            "monolingual": self.is_monolingual(language),
            "correct_native": bool(settings.get("conversation", {}).get("correct_native", True))
            and not self.is_monolingual(language),
            "learner_name": settings["learner"].get("name") or "",
            "learner_goal": (settings["learner"].get("goals") or {}).get(language, ""),
            "learner_notes": learner.get("notes") or "",
            "level": level,
            "unit": unit or {},
            "unit_number": (unit["index"] + 1) if unit else 0,
            "units_total": len(cur["units"]),
            "unit_progress": {"sessions": progress.get("sessions", 0), "mastery": progress.get("mastery", 0.0),
                              "status": progress.get("status", "active")},
            "level_units": [{"id": u["id"], "title": u["title"]} for u in level_units],
            "all_units": [{"id": u["id"], "title": u["title"], "level": u["level"]} for u in cur["units"]],
            "mode": mode,
            "mode_title": MODES.get(mode, {}).get("title", mode),
            "scenario": scenario or "",
            "focus": focus or "",
            "immersion": immersion,
            "memories": [m["content"] for m in self.memories_for(language)],
            "recent_summaries": self.recent_summaries(language, exclude=session_id),
            "weak_vocab": [display_word(v) + (f" ({v['translation']})" if v.get("translation") else "")
                           for v in weak],
            "reinforce_vocab": [display_word(v) + (f" ({v['translation']})" if v.get("translation") else "")
                                for v in self.reinforce_vocab(language, seed=session_id,
                                                              exclude={w["id"] for w in weak})],
            "recurring_errors": self.recurring_errors(language),
            "exam": self.exam_for_level(language, level),
            "workshop": self.workshop_for_session(session_id) if mode == "workshop" else None,
            "directives": [d["content"] for d in self.active_directives(language)],
            "break_name": BREAK_NAMES.get(language, "coffee break"),
            "exams": cur.get("exams", []),
            "today": date.today().isoformat(),
        }

    def system_prompt(self, session: dict) -> str:
        ctx = self.build_context(session["language"], session["mode"], session.get("unit_id"),
                                 session.get("scenario") or "", session.get("focus") or "", session["id"])
        return self.render_system_prompt(ctx)

    def render_system_prompt(self, ctx: dict) -> str:
        parts = [self.prompts.render("tutor_base", **ctx)]
        persona = f"persona_{ctx['language']}"
        if persona in self.prompts.names():
            parts.append(self.prompts.render(persona, **ctx))
        parts.append(self.prompts.render("context", **ctx))
        mode_prompt = f"mode_{ctx['mode']}"
        if mode_prompt in self.prompts.names():
            parts.append(self.prompts.render(mode_prompt, **ctx))
        return "\n\n".join(p for p in parts if p.strip())

    def chat_messages(self, session: dict, system: str) -> list[dict]:
        limit = int(self.settings.get("llm.context_messages", 40))
        rows = self.db.messages(session["id"])
        msgs = []
        for r in rows:
            content = r["content"]
            note = (r.get("meta") or {}).get("pron_note")
            if r["role"] == "user" and note:
                content = f"{content}\n\n{note}"
            msgs.append({"role": r["role"], "content": content})
        if len(msgs) > limit:
            msgs = msgs[-limit:]
            while msgs and msgs[0]["role"] != "user":
                msgs.pop(0)
        return [{"role": "system", "content": system}, *msgs]

    # ------------------------------------------------------------------
    # sessions
    # ------------------------------------------------------------------
    def create_session(self, language: str, mode: str, unit_id: str | None = None, scenario: str = "",
                       focus: str = "") -> dict:
        if language not in LANGUAGES:
            raise ValueError(f"Unsupported language '{language}'")
        if mode not in MODES:
            raise ValueError(f"Unknown mode '{mode}'")
        unit = self.curricula.unit(language, unit_id) if unit_id else self.current_unit(language)
        ts = now()
        unit_title = unit["title"] if unit else ""
        title = f"{MODES[mode]['title']}" + (f" · {unit_title}" if MODES[mode]["unit"] and unit_title else "")
        sid = self.db.insert("sessions", {
            "language": language, "mode": mode, "unit_id": unit["id"] if unit else None,
            "scenario": scenario or "", "focus": focus or "", "title": title, "status": "active",
            "created_at": ts, "updated_at": ts, "model": self.settings.get("llm.model")})
        return self.db.session(sid)

    def unit_status(self, language: str, unit_id: str | None = None) -> dict:
        """Where a unit stands, in plain numbers: position in its level and the course, and the two
        conditions for completing it (enough reviewed sessions, enough mastery)."""
        cur = self.curricula.get(language)
        unit = (self.curricula.unit(language, unit_id) if unit_id else None) or self.current_unit(language)
        prog = self.db.ensure_unit(language, unit["id"])
        pmap = self.db.unit_progress_map(language)
        level_units = [u for u in cur["units"] if u["level"] == unit["level"]]
        threshold = float(self.settings.get("curriculum.advance_threshold", 0.75))
        min_sessions = int(unit.get("min_sessions", 1))
        open_sessions = [s for s in self.db.all(
            "SELECT * FROM sessions WHERE language=? AND unit_id=? AND status='active' AND mode IN (%s)"
            % ",".join("?" * len(UNIT_MODES)), [language, unit["id"], *sorted(UNIT_MODES)]) if not self.is_archived(s)]
        return {
            "unit_id": unit["id"], "title": unit["title"], "level": unit["level"],
            "number_in_level": level_units.index(unit) + 1 if unit in level_units else 0,
            "level_total": len(level_units),
            "level_done": sum(1 for u in level_units if pmap.get(u["id"], {}).get("status") == "completed"),
            "number_in_course": unit["index"] + 1, "course_total": len(cur["units"]),
            "status": prog.get("status", "active"),
            "sessions_reviewed": prog.get("sessions", 0), "min_sessions": min_sessions,
            "sessions_ok": prog.get("sessions", 0) >= min_sessions,
            "mastery": prog.get("mastery", 0.0), "threshold": threshold,
            "mastery_ok": prog.get("mastery", 0.0) >= threshold,
            "open_sessions": len(open_sessions),
        }

    def is_archived(self, s: dict) -> bool:
        """Manual choice wins; otherwise sessions without activity for history.archive_after_days are archived."""
        if s.get("archived") is not None:
            return bool(s["archived"])
        days = int(self.settings.get("history.archive_after_days", 7) or 0)
        if days <= 0:
            return False
        last = _parse_ts(s.get("updated_at") or s["created_at"])
        return last < datetime.now() - timedelta(days=days)

    def open_session(self, language: str, mode: str, unit_id: str | None = None) -> dict | None:
        """The most recent unfinished session of this kind (same mode and unit) that has real messages,
        so "Continue lesson" can resume it instead of starting a duplicate."""
        if mode not in MODES or mode == "workshop":
            return None
        unit = self.curricula.unit(language, unit_id) if unit_id else self.current_unit(language)
        uid = unit["id"] if unit and MODES[mode]["unit"] else None
        rows = self.db.all(
            "SELECT s.*, (SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id AND m.hidden=0 AND m.role='user') "
            "AS turns FROM sessions s WHERE s.language=? AND s.mode=? AND s.status='active' "
            "AND COALESCE(s.scenario,'')='' AND COALESCE(s.focus,'')='' "
            + ("AND s.unit_id=? " if uid else "") + "ORDER BY s.updated_at DESC LIMIT 5",
            [language, mode, *([uid] if uid else [])])
        for r in rows:
            if r["turns"] > 0:
                r.pop("analysis", None)
                return r
        return None

    def session_duration(self, sid: int) -> int:
        """Active seconds, estimated from message timestamps (gaps capped at 2 minutes)."""
        rows = self.db.all("SELECT created_at FROM messages WHERE session_id=? ORDER BY id", [sid])
        if not rows:
            return 0
        times = [_parse_ts(r["created_at"]) for r in rows]
        total = 30
        for a, b in zip(times, times[1:]):
            total += min(120, max(0, (b - a).total_seconds()))
        return int(total)

    def session_view(self, sid: int) -> dict | None:
        s = self.db.session(sid)
        if not s:
            return None
        s["messages"] = self.db.messages(sid, include_hidden=False)
        s["unit"] = self.curricula.unit(s["language"], s["unit_id"]) if s.get("unit_id") else None
        s["duration"] = self.session_duration(sid)
        s["mode_info"] = MODES.get(s["mode"], {})
        s["workshop"] = self.workshop_for_session(sid) if s["mode"] == "workshop" else None
        s["vocab"] = self.db.all("SELECT * FROM vocab WHERE session_id=? ORDER BY id", [sid])
        for v in s["vocab"]:
            v["display"] = display_word(v)
        # for highlighting in the transcript word picker: everything already in the vocabulary list
        s["saved_lemmas"] = self.db.all("SELECT lemma, status FROM vocab WHERE language=? AND status != 'ignored'",
                                        [s["language"]])
        return s

    async def pick_words(self, sid: int, words: list[dict]) -> dict:
        """Flashcards for words the learner picked in the transcript: one model call fills in the fields,
        the words are stored as candidates of this session (shown in the review table to check and send)."""
        s = self.db.session(sid)
        if not s:
            raise ValueError("Session not found")
        lang = s["language"]
        clean = []
        seen = set()
        for w in words[:30]:
            text = re.sub(r"\s+", " ", str((w or {}).get("text", "")).replace("**", "")).strip(" .,!?;:\"'«»“”()")
            if text and len(text) <= 80 and norm(text) not in seen:
                seen.add(norm(text))
                clean.append({"text": text, "context": str(w.get("context") or "").replace("**", "")[:300]})
        if not clean:
            raise ValueError("Pick at least one word.")
        ctx = self.build_context(lang, s["mode"], s.get("unit_id"), session_id=sid)
        ctx["words"] = clean
        try:
            data = await self.llm.chat_json(
                [{"role": "system", "content": self.prompts.render("vocab_pick", **ctx)},
                 {"role": "user", "content": "Return the JSON now."}], schema=VOCAB_SCHEMA)
            items = data.get("items", []) if isinstance(data, dict) else []
        except Exception:
            log.exception("vocab pick failed; falling back to one call per word")
            items = []
        added, existing = [], []
        ts = now()
        for i, w in enumerate(clean):
            it = items[i] if i < len(items) and isinstance(items[i], dict) else None
            if it is None:
                try:
                    it = await self.autofill_vocab(lang, w["text"], w["context"])
                except Exception:
                    it = {"lemma": w["text"]}
            lemma = clean_lemma(str(it.get("lemma") or w["text"]), lang)
            ln = norm(lemma)
            if not ln:
                continue
            row = self.db.one("SELECT * FROM vocab WHERE language=? AND lemma_norm=?", [lang, ln])
            if row and row["status"] != "ignored":
                row["display"] = display_word(row)
                existing.append(row)
                continue
            fields = {
                "forms": str(it.get("forms", ""))[:200], "gender": normalize_gender(str(it.get("gender", "")), lang),
                "pos": str(it.get("pos", "")).lower()[:30], "translation": str(it.get("translation", ""))[:200],
                "example": str(it.get("example", "") or w["context"])[:300],
                "example_translation": str(it.get("example_translation", ""))[:300],
                "notes": str(it.get("notes", ""))[:300], "session_id": sid, "status": "candidate",
                "reason": "picked", "updated_at": ts,
            }
            if row:   # a word you once skipped: bring it back
                self.db.update("vocab", row["id"], fields)
                vid = row["id"]
            else:
                vid = self.db.insert("vocab", {"language": lang, "lemma": lemma, "lemma_norm": ln,
                                               "unit_id": s.get("unit_id") or "", "source": "manual", "freq": 0,
                                               "created_at": ts, **fields})
            r = self.db.one("SELECT * FROM vocab WHERE id=?", [vid])
            r["display"] = display_word(r)
            added.append(r)
        return {"added": added, "existing": existing}

    def transcript(self, sid: int, max_chars: int = 24000) -> str:
        s = self.db.session(sid)
        lines = []
        for m in self.db.messages(sid, include_hidden=False):
            who = "Learner" if m["role"] == "user" else "Tutor"
            lines.append(f"{who}: {m['content'].strip()}")
        text = "\n".join(lines)
        if len(text) > max_chars:
            half = max_chars // 2
            text = text[:half] + "\n[…middle of the session omitted…]\n" + text[-half:]
        return text if s else ""

    # ------------------------------------------------------------------
    # post-session analysis
    # ------------------------------------------------------------------
    async def analyze_session(self, sid: int) -> dict:
        s = self.db.session(sid)
        if not s:
            raise ValueError("Session not found")
        user_turns = self.db.scalar("SELECT COUNT(*) FROM messages WHERE session_id=? AND role='user' AND hidden=0",
                                    [sid])
        if not user_turns:
            raise ValueError("Nothing to analyze yet — say something in the session first.")
        ctx = self.build_context(s["language"], s["mode"], s.get("unit_id"), s.get("scenario") or "",
                                 s.get("focus") or "", sid)
        ctx["transcript"] = self.transcript(sid)
        ctx["known_error_patterns"] = [e["pattern"] for e in self.db.all(
            "SELECT pattern FROM errors WHERE language=? ORDER BY count DESC LIMIT 40", [s["language"]])]
        ctx["existing_memories"] = ctx["memories"]
        model = self.settings.get("llm.analysis_model") or None

        analysis = await self.llm.chat_json(
            [{"role": "system", "content": self.prompts.render("analysis_session", **ctx)},
             {"role": "user", "content": "Analyze the session transcript above and return the JSON."}],
            schema=ANALYSIS_SCHEMA, model=model)
        analysis = self._clean_analysis(analysis, ctx)

        try:
            vocab_items = await self.extract_vocab(sid, ctx, model)
        except Exception as e:  # vocab extraction failing shouldn't lose the analysis
            log.exception("vocab extraction failed")
            analysis["vocab_error"] = str(e)
            vocab_items = []

        result = self._apply_analysis(s, analysis)
        result["vocab_candidates"] = vocab_items
        await self.release_analysis_model()
        # Optionally send the new words straight to Anki (if it's open).
        result["anki_auto"] = None
        if vocab_items and self.settings.get("anki.auto_add", True):
            ids = [v["id"] for v in vocab_items]
            if await self.anki().version() is not None:
                for i in ids:
                    self.db.execute("UPDATE vocab SET status='learning', updated_at=? WHERE id=?", [now(), i])
                result["anki_auto"] = await self.push_to_anki(ids)
            else:
                result["anki_auto"] = {"queued": len(ids)}
            stored = {k: v for k, v in result.items() if k != "vocab_candidates"}
            self.db.update("sessions", sid, {"analysis": json.dumps(stored, ensure_ascii=False)})
        return result

    def _clean_analysis(self, a: dict, ctx: dict) -> dict:
        a = dict(a or {})
        for k in ("title", "summary", "feedback", "cefr_estimate", "recommended_unit_id", "exam_breakdown"):
            a[k] = str(a.get(k) or "").strip()
        for k in ("strengths", "focus_next"):
            a[k] = [str(x) for x in (a.get(k) or []) if str(x).strip()][:6]
        a["errors"] = [e for e in (a.get("errors") or []) if isinstance(e, dict) and e.get("pattern")][:12]
        a["mastered_patterns"] = [str(p) for p in (a.get("mastered_patterns") or []) if str(p).strip()][:20]
        a["memories"] = [m for m in (a.get("memories") or []) if isinstance(m, dict) and m.get("content")][:8]
        a["can_do"] = [{"goal": str(c.get("goal", "")), "score": _clamp01(c.get("score"))}
                       for c in (a.get("can_do") or []) if isinstance(c, dict)]
        a["unit_mastery"] = _clamp01(a.get("unit_mastery"))
        a["ready_to_advance"] = bool(a.get("ready_to_advance"))
        valid_units = {u["id"] for u in ctx["all_units"]}
        if a["recommended_unit_id"] not in valid_units:
            a["recommended_unit_id"] = ""
        try:
            a["exam_score"] = float(a.get("exam_score") or 0)
            a["exam_max"] = float(a.get("exam_max") or 0)
        except (TypeError, ValueError):
            a["exam_score"], a["exam_max"] = 0.0, 0.0
        return a

    def _apply_analysis(self, s: dict, a: dict) -> dict:
        lang, sid, ts = s["language"], s["id"], now()
        # errors (merge with recurring patterns)
        for e in a["errors"]:
            pn = norm(e["pattern"])
            existing = self.db.one("SELECT * FROM errors WHERE language=? AND pattern_norm=?", [lang, pn])
            error_id = existing["id"] if existing else None
            if existing:
                self.db.update("errors", existing["id"], {
                    "count": existing["count"] + 1, "last_seen": ts, "last_session": sid, "resolved": 0,
                    "example_wrong": e.get("wrong") or existing["example_wrong"],
                    "example_right": e.get("right") or existing["example_right"],
                    "explanation": e.get("explanation") or existing["explanation"]})
            else:
                self.db.insert("errors", {
                    "language": lang, "category": e.get("category") or "grammar", "pattern": e["pattern"],
                    "pattern_norm": pn, "example_wrong": e.get("wrong", ""), "example_right": e.get("right", ""),
                    "explanation": e.get("explanation", ""), "count": 1, "first_seen": ts, "last_seen": ts,
                    "last_session": sid})
                error_id = self.db.scalar("SELECT id FROM errors WHERE language=? AND pattern_norm=?", [lang, pn])
            if s["mode"] != "workshop":
                self.db.insert("error_events", {"error_id": error_id, "language": lang, "session_id": sid,
                                                "wrong": e.get("wrong", ""), "right": e.get("right", ""), "created_at": ts})
        # mistakes the learner has now mastered (workshop sessions)
        for p in a.get("mastered_patterns", []):
            self.db.execute("UPDATE errors SET resolved=1 WHERE language=? AND pattern_norm=?", [lang, norm(p)])

        # memories (skip near-duplicates)
        existing_mem = {norm(m["content"]) for m in self.db.all("SELECT content FROM memories")}
        new_memory_ids = []
        for m in a["memories"]:
            if norm(m["content"]) in existing_mem:
                continue
            cat = m.get("category") if m.get("category") in ("personal", "preference", "goal", "other") else "other"
            new_memory_ids.append(self.db.insert("memories", {
                "language": None if cat in ("personal",) else lang, "category": cat,
                "content": m["content"].strip(), "source_session_id": sid, "pinned": 0, "active": 1,
                "created_at": ts, "updated_at": ts}))
        a["memory_ids"] = new_memory_ids

        # unit progress
        advance_suggestion = None
        if s["mode"] in UNIT_MODES and s.get("unit_id"):
            prog = self.db.ensure_unit(lang, s["unit_id"])
            sessions = prog["sessions"] + 1
            mastery = a["unit_mastery"] if prog["sessions"] == 0 else 0.5 * prog["mastery"] + 0.5 * a["unit_mastery"]
            self.db.execute("UPDATE unit_progress SET sessions=?, mastery=?, last_session_at=? "
                            "WHERE language=? AND unit_id=?", [sessions, round(mastery, 3), ts, lang, s["unit_id"]])
            unit = self.curricula.unit(lang, s["unit_id"])
            threshold = float(self.settings.get("curriculum.advance_threshold", 0.75))
            is_current = self.learner(lang)["current_unit_id"] == s["unit_id"]
            if unit and is_current and mastery >= threshold and sessions >= int(unit.get("min_sessions", 1)) \
                    and (a["ready_to_advance"] or mastery >= threshold + 0.1):
                nxt = self.curricula.next_unit(lang, s["unit_id"])
                if self.settings.get("curriculum.auto_advance"):
                    self.advance(lang)
                    advance_suggestion = {"done": True, "next": nxt}
                else:
                    advance_suggestion = {"done": False, "next": nxt}
            a["unit_mastery_total"] = round(mastery, 3)
            a["unit_sessions"] = sessions
        a["advance"] = advance_suggestion

        # exam score
        if s["mode"] == "exam" and a["exam_max"] > 0:
            unit = self.curricula.unit(lang, s.get("unit_id")) or self.current_unit(lang)
            self.db.insert("exam_scores", {"language": lang, "level": unit["level"], "session_id": sid,
                                           "score": a["exam_score"], "max_score": a["exam_max"],
                                           "breakdown": a["exam_breakdown"], "created_at": ts})

        self.db.update("sessions", sid, {
            "status": "completed", "ended_at": ts, "summary": a["summary"],
            "title": a["title"] or s["title"], "analysis": json.dumps(a, ensure_ascii=False)})
        return a

    # ------------------------------------------------------------------
    # vocabulary
    # ------------------------------------------------------------------
    async def extract_vocab(self, sid: int, ctx: dict, model: str | None = None) -> list[dict]:
        s = self.db.session(sid)
        lang = s["language"]
        known = self.db.all("SELECT lemma FROM vocab WHERE language=? ORDER BY updated_at DESC LIMIT 400", [lang])
        ctx = dict(ctx)
        ctx["known_lemmas"] = [k["lemma"] for k in known]
        ctx["max_items"] = int(self.settings.get("vocab.max_cards_per_session", 15)) + 5
        data = await self.llm.chat_json(
            [{"role": "system", "content": self.prompts.render("analysis_vocab", **ctx)},
             {"role": "user", "content": "Return the vocabulary JSON now."}],
            schema=VOCAB_SCHEMA, model=model)
        items = data.get("items", []) if isinstance(data, dict) else []
        return self.store_candidates(lang, sid, s.get("unit_id") or "", items)

    def store_candidates(self, lang: str, sid: int | None, unit_id: str, items: list[dict]) -> list[dict]:
        try:
            from wordfreq import zipf_frequency
        except ImportError:  # pragma: no cover
            zipf_frequency = None
        min_zipf = float(self.settings.get("vocab.min_zipf", 2.0))
        max_cards = int(self.settings.get("vocab.max_cards_per_session", 15))
        existing = {r["lemma_norm"] for r in self.db.all("SELECT lemma_norm FROM vocab WHERE language=?", [lang])}
        picked: dict[str, dict] = {}
        for it in items:
            if not isinstance(it, dict):
                continue
            lemma = clean_lemma(str(it.get("lemma", "")), lang)
            ln = norm(lemma)
            if not ln or ln in existing or ln in picked or len(ln) > 60:
                continue
            reason = str(it.get("reason", "new")).lower().strip()
            reason = reason if reason in REASON_PRIORITY else "new"
            freq = 0.0
            if zipf_frequency:
                freq = max(zipf_frequency(w, lang) for w in ln.split()) if " " in ln else zipf_frequency(ln, lang)
            if freq < min_zipf and reason in ("new",) and " " not in ln:
                continue
            if lang == "en" and reason == "new" and freq > 5.2:  # too basic for an advanced learner
                continue
            gender = normalize_gender(str(it.get("gender", "")), lang)
            picked[ln] = {
                "language": lang, "lemma": lemma, "lemma_norm": ln, "forms": str(it.get("forms", ""))[:200],
                "gender": gender, "pos": str(it.get("pos", "")).lower()[:30],
                "translation": str(it.get("translation", ""))[:200],
                "example": str(it.get("example", ""))[:300],
                "example_translation": str(it.get("example_translation", ""))[:300],
                "notes": str(it.get("notes", ""))[:300], "unit_id": unit_id, "session_id": sid,
                "status": "candidate", "source": "extracted", "reason": reason, "freq": round(freq, 2),
            }
        ranked = sorted(picked.values(), key=lambda v: (REASON_PRIORITY[v["reason"]], -v["freq"]))[:max_cards]
        ts = now()
        out = []
        for v in ranked:
            v["created_at"] = v["updated_at"] = ts
            vid = self.db.insert("vocab", v)
            row = self.db.one("SELECT * FROM vocab WHERE id=?", [vid])
            row["display"] = display_word(row)
            out.append(row)
        return out

    def add_manual_vocab(self, lang: str, fields: dict) -> dict:
        lemma = clean_lemma(fields.get("lemma", ""), lang)
        ln = norm(lemma)
        if not ln:
            raise ValueError("The word is empty.")
        if self.db.one("SELECT id FROM vocab WHERE language=? AND lemma_norm=?", [lang, ln]):
            raise ValueError(f"'{lemma}' is already in your vocabulary.")
        ts = now()
        vid = self.db.insert("vocab", {
            "language": lang, "lemma": lemma, "lemma_norm": ln, "forms": fields.get("forms", ""),
            "gender": normalize_gender(fields.get("gender", ""), lang)
            or split_article(fields.get("lemma", ""), lang)[2],   # "en bil" / "la maison" → gender from the article
            "pos": fields.get("pos", ""),
            "translation": fields.get("translation", ""), "example": fields.get("example", ""),
            "example_translation": fields.get("example_translation", ""), "notes": fields.get("notes", ""),
            "unit_id": fields.get("unit_id") or self.learner(lang)["current_unit_id"],
            "session_id": fields.get("session_id"), "status": fields.get("status") or "learning",
            "source": "manual", "reason": "manual", "freq": 0, "created_at": ts, "updated_at": ts})
        return self.db.one("SELECT * FROM vocab WHERE id=?", [vid])

    async def autofill_vocab(self, lang: str, word: str, context: str = "") -> dict:
        ctx = {"language": lang, "language_name": LANGUAGES[lang]["name"], "word": word, "context": context,
               "native_language": self.settings.get("learner.native_language") or "English"}
        data = await self.llm.chat_json(
            [{"role": "system", "content": self.prompts.render("vocab_autofill", **ctx)},
             {"role": "user", "content": word}], schema=AUTOFILL_SCHEMA)
        data = {k: str(v) for k, v in (data or {}).items()}
        data["gender"] = normalize_gender(data.get("gender", ""), lang)
        data["lemma"] = clean_lemma(data.get("lemma") or word, lang)
        return data

    def _card_audio(self, v: dict) -> dict[str, bytes]:
        media: dict[str, bytes] = {}
        if not self.settings.get("anki.include_audio", True) or not self.tts.server_side((v["language"],)):
            return media
        try:
            media[f"parlera_{v['language']}_{v['id']}_w.wav"] = self.tts.synth(display_word(v), v["language"], 0.9)
            if v.get("example"):
                media[f"parlera_{v['language']}_{v['id']}_e.wav"] = self.tts.synth(v["example"], v["language"], 0.95)
        except Exception as e:
            log.warning("card audio failed: %s", e)
        return media

    async def push_to_anki(self, ids: list[int]) -> dict:
        settings = self.settings.all()
        client = self.anki()
        await client.ensure_model()
        added, failed = [], []
        for vid in ids:
            v = self.db.one("SELECT * FROM vocab WHERE id=?", [vid])
            if not v:
                continue
            try:
                media = await asyncio.to_thread(self._card_audio, v)
                for name, data in media.items():
                    await client.store_media(name, data)
                wa = f"parlera_{v['language']}_{v['id']}_w.wav"
                ea = f"parlera_{v['language']}_{v['id']}_e.wav"
                fields = note_fields(v, settings["anki"].get("add_reverse", True),
                                     wa if wa in media else "", ea if ea in media else "")
                unit = self.curricula.unit(v["language"], v.get("unit_id"))
                note_id = await client.add_note(deck_name(settings, v["language"], unit), fields, note_tags(v))
                self.db.update("vocab", vid, {"anki_note_id": note_id, "status": "learning",
                                              "anki_synced_at": now(), "updated_at": now()})
                added.append(vid)
            except AnkiError as e:
                failed.append({"id": vid, "lemma": v["lemma"], "error": str(e)})
        return {"added": added, "failed": failed}

    async def push_pending(self, language: str | None = None) -> dict:
        """Send words that were saved while Anki was closed (or auto-suggested) to Anki."""
        if self.settings.get("anki.auto_add", True):
            cond = "(status='learning' OR (status='candidate' AND source='extracted'))"
        else:
            cond = "status='learning'"
        sql = "SELECT id FROM vocab WHERE anki_note_id IS NULL AND " + cond
        params: list = []
        if language:
            sql += " AND language=?"
            params.append(language)
        ids = [r["id"] for r in self.db.all(sql, params)]
        if not ids:
            return {"added": [], "failed": []}
        for i in ids:
            self.db.execute("UPDATE vocab SET status='learning', updated_at=? WHERE id=? AND status='candidate'",
                            [now(), i])
        return await self.push_to_anki(ids)

    async def import_anki_deck(self, language: str, deck: str, word_field: str, meaning_field: str,
                               example_field: str = "") -> dict:
        """Link an existing Anki deck's notes into Parlera's vocabulary (nothing is changed in Anki).

        The note's creation time (encoded in its id) becomes `created_at`, so reinforcement
        and "recently learned" use the real dates. Review stats are synced right after.
        """
        client = self.anki()
        notes = await client.deck_notes(deck)
        existing = {r["lemma_norm"]: r for r in self.db.all(
            "SELECT id, lemma_norm, anki_note_id FROM vocab WHERE language=?", [language])}
        added = linked = skipped = 0
        for n in notes:
            f = n["fields"]
            lemma = clean_lemma(f.get(word_field, ""), language)
            ln = norm(lemma)
            if not ln or len(ln) > 120:
                skipped += 1
                continue
            if ln in existing:
                row = existing[ln]
                if not row["anki_note_id"]:
                    self.db.update("vocab", row["id"], {"anki_note_id": n["noteId"]})
                    linked += 1
                else:
                    skipped += 1
                continue
            try:
                created = datetime.fromtimestamp(n["noteId"] / 1000).isoformat(timespec="seconds")
            except (OverflowError, OSError, ValueError):
                created = now()
            vid = self.db.insert("vocab", {
                "language": language, "lemma": lemma, "lemma_norm": ln,
                "translation": f.get(meaning_field, "")[:300] if meaning_field else "",
                "example": f.get(example_field, "")[:300] if example_field else "",
                "unit_id": "", "status": "learning", "source": "anki", "reason": "imported",
                "anki_note_id": n["noteId"], "created_at": created, "updated_at": now()})
            existing[ln] = {"id": vid, "lemma_norm": ln, "anki_note_id": n["noteId"]}
            added += 1
        synced = await self.sync_anki(language)
        return {"notes": len(notes), "added": added, "linked": linked, "skipped": skipped, "synced": synced}

    async def remove_from_anki(self, ids: list[int]) -> int:
        rows = [self.db.one("SELECT id, anki_note_id FROM vocab WHERE id=?", [i]) for i in ids]
        note_ids = [r["anki_note_id"] for r in rows if r and r["anki_note_id"]]
        await self.anki().delete_notes(note_ids)
        for r in rows:
            if r:
                self.db.update("vocab", r["id"], {"anki_note_id": None, "status": "ignored", "updated_at": now()})
        return len(note_ids)

    async def sync_anki(self, language: str | None = None) -> dict:
        client = self.anki()
        rows = self.db.all("SELECT id, anki_note_id FROM vocab WHERE anki_note_id IS NOT NULL" +
                           (" AND language=?" if language else ""), [language] if language else [])
        stats = await client.review_stats([r["anki_note_id"] for r in rows])
        ts, updated, known = now(), 0, 0
        for r in rows:
            st = stats.get(r["anki_note_id"])
            if not st:
                continue
            status = "known" if st["interval"] >= 21 else "learning"
            known += status == "known"
            self.db.update("vocab", r["id"], {"anki_interval": st["interval"], "anki_lapses": st["lapses"],
                                              "anki_reps": st["reps"], "anki_synced_at": ts, "status": status})
            updated += 1
        return {"updated": updated, "known": known, "linked": len(rows)}

    def export_apkg(self, ids: list[int], out_path: Path) -> Path:
        from .anki import build_apkg
        rows = [self.db.one("SELECT * FROM vocab WHERE id=?", [i]) for i in ids]
        rows = [r for r in rows if r]
        if not rows:
            raise ValueError("No words selected.")
        media: dict[str, bytes] = {}
        for v in rows:
            media.update(self._card_audio(v))
        units = {u["id"]: u for lang in {r["language"] for r in rows} for u in self.curricula.get(lang)["units"]}
        return build_apkg(rows, self.settings.all(), media, out_path, units)

    # ------------------------------------------------------------------
    # dashboard stats
    # ------------------------------------------------------------------
    def stats(self, language: str) -> dict:
        sessions = self.db.all("SELECT id, created_at, status FROM sessions WHERE language=? ORDER BY created_at",
                               [language])
        games = self.db.all("SELECT created_at, seconds FROM practice_log WHERE language=?", [language])
        days = sorted({_parse_ts(s["created_at"]).date() for s in sessions}
                      | {_parse_ts(g["created_at"]).date() for g in games})   # quick games count for the streak
        streak, d = 0, date.today()
        dayset = set(days)
        if d not in dayset:
            d -= timedelta(days=1)
        while d in dayset:
            streak += 1
            d -= timedelta(days=1)
        week_ago = datetime.now() - timedelta(days=7)
        total_sec, week_sec = 0, 0
        for s in sessions:
            dur = self.session_duration(s["id"])
            total_sec += dur
            if _parse_ts(s["created_at"]) >= week_ago:
                week_sec += dur
        for g in games:
            total_sec += g["seconds"]
            if _parse_ts(g["created_at"]) >= week_ago:
                week_sec += g["seconds"]
        counts = {r["status"]: r["n"] for r in self.db.all(
            "SELECT status, COUNT(*) n FROM vocab WHERE language=? GROUP BY status", [language])}
        cur = self.curricula.get(language)
        prog = self.db.unit_progress_map(language)
        levels = []
        for lv in cur["levels"]:
            ids = [u["id"] for u in lv["units"]]
            done = sum(1 for i in ids if prog.get(i, {}).get("status") == "completed")
            scores = self.db.all("SELECT score, max_score FROM exam_scores WHERE language=? AND level=? "
                                 "ORDER BY created_at DESC LIMIT 3", [language, lv["code"]])
            readiness = (sum(s["score"] / s["max_score"] for s in scores if s["max_score"]) / len(scores)) \
                if scores else None
            levels.append({"code": lv["code"], "title": lv.get("title", ""), "total": len(ids), "completed": done,
                           "exam": (lv.get("exam") or {}).get("name", ""), "exam_readiness": readiness})
        return {
            "streak": streak, "total_minutes": round(total_sec / 60), "week_minutes": round(week_sec / 60),
            "sessions": len(sessions), "completed_sessions": sum(1 for s in sessions if s["status"] == "completed"),
            "vocab": {"learning": counts.get("learning", 0), "known": counts.get("known", 0),
                      "candidate": counts.get("candidate", 0)},
            "levels": levels,
            "practice_days": [d.isoformat() for d in days[-60:]],
        }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
ARTICLES = {
    "en": ("a ", "an ", "the ", "to "),
    "sv": ("en ", "ett "),
    "fr": ("le ", "la ", "les ", "un ", "une ", "des ", "l'", "l’"),
}


def clean_lecture(d: Any, topic: str) -> dict:
    """Normalise the model's lecture JSON so the UI can rely on its shape."""
    d = d if isinstance(d, dict) else {}
    txt = lambda v: str(v or "").strip()  # noqa: E731
    lst = lambda v: v if isinstance(v, list) else []  # noqa: E731
    steps = []
    for st in lst(d.get("steps"))[:6]:
        if isinstance(st, dict) and (txt(st.get("heading")) or txt(st.get("explanation"))):
            steps.append({"heading": txt(st.get("heading")), "explanation": txt(st.get("explanation")),
                          "examples": [{"target": txt(e.get("target")), "native": txt(e.get("native")),
                                        "note": txt(e.get("note"))}
                                       for e in lst(st.get("examples"))[:5] if isinstance(e, dict) and txt(e.get("target"))]})
    table = d.get("table") if isinstance(d.get("table"), dict) else {}
    cols = [txt(c) for c in lst(table.get("columns"))][:8]
    rows = [[txt(c) for c in r][:len(cols) or 8] for r in lst(table.get("rows")) if isinstance(r, list)][:14]
    quiz = []
    for q in lst(d.get("quiz"))[:10]:
        if not isinstance(q, dict):
            continue
        opts = [txt(o) for o in lst(q.get("options")) if txt(o)][:5]
        ans = txt(q.get("answer"))
        if not txt(q.get("question")) or len(opts) < 2:
            continue
        match = next((o for o in opts if o == ans), None) or next((o for o in opts if o.lower() == ans.lower()), None)
        if match is None and ans:
            opts.append(ans)
            match = ans
        if match is None:
            continue
        quiz.append({"question": txt(q.get("question")), "options": opts, "answer": match,
                     "explanation": txt(q.get("explanation"))})
    return {
        "title": txt(d.get("title")) or topic, "summary": txt(d.get("summary")), "mechanism": txt(d.get("mechanism")),
        "steps": steps, "table": {"caption": txt(table.get("caption")), "columns": cols, "rows": rows if cols else []},
        "contrast": txt(d.get("contrast")),
        "mistakes": [{"wrong": txt(m.get("wrong")), "right": txt(m.get("right")), "why": txt(m.get("why"))}
                     for m in lst(d.get("mistakes"))[:6] if isinstance(m, dict) and txt(m.get("right"))],
        "tips": [txt(t) for t in lst(d.get("tips")) if txt(t)][:5],
        "quiz": quiz, "speaking_task": txt(d.get("speaking_task")), "followups": [],
    }


def clean_lemma(lemma: str, lang: str) -> str:
    s = re.sub(r"\s+", " ", (lemma or "").strip().strip(".,!?;:\"'«»“”"))
    low = s.lower()
    for art in ARTICLES.get(lang, ()):
        if low.startswith(art) and len(s) > len(art) + 1:
            s = s[len(art):]
            break
    if lang == "sv" and s.lower().startswith("att ") and len(s) > 5:  # infinitive marker
        s = s[4:]
    return s.strip()


def normalize_gender(g: str, lang: str) -> str:
    g = (g or "").strip().lower()
    if lang == "sv":
        if g in ("en", "common", "utrum", "c", "n-en", "u"):
            return "en"
        if g in ("ett", "neuter", "neutrum", "n"):
            return "ett"
        return ""
    if lang == "fr":
        if g in ("m", "masc", "masculine", "le", "masculin", "un"):
            return "m"
        if g in ("f", "fem", "feminine", "la", "féminin", "feminin", "une"):
            return "f"
        return ""
    return ""


def level_rank(code: str) -> int:
    return LEVEL_ORDER.index(code) if code in LEVEL_ORDER else 0


def copy_tree_files(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        if f.is_file():
            shutil.copy2(f, dst / f.name)
