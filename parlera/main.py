"""FastAPI app: REST API + WebSocket + static GUI."""
from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import logging
import shutil
import tempfile
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from . import __version__, practice
from .anki import AnkiError, display_word
from .config import DEFAULTS_DIR, LANGUAGES, STATIC_DIR
from .core import Parlera
from .curriculum import CurriculumError
from .db import norm, now
from .llm import LLMError
from .prompts import MODES, PROMPT_INFO
from .textproc import segment_languages
from .tts import PIPER_BASE, PIPER_CATALOG, TTSError
from .tutor import TutorSession

log = logging.getLogger("parlera")


DEMO = os.environ.get("PARLERA_DEMO") or ""


def static_build_id() -> str:
    """Short hash of the web UI's files (changes whenever any of them changes)."""
    import hashlib
    h = hashlib.sha1(__version__.encode())
    for f in sorted(STATIC_DIR.rglob("*")):
        if f.is_file() and f.suffix in (".js", ".css", ".html", ".svg"):
            h.update(f.relative_to(STATIC_DIR).as_posix().encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:10]


def create_app(root: Path | None = None) -> FastAPI:
    core = Parlera(root)
    app = FastAPI(title="Parlera", version=__version__)
    app.state.core = core

    app.state.server = None          # set by __main__ when run as a program
    app.state.last_seen = None       # last heartbeat from a browser tab
    app.state.bye_at = None          # when a tab reported it was closed

    def request_quit(reason: str) -> bool:
        server = app.state.server
        if server is None:
            return False
        log.info("Stopping Parlera (%s)", reason)
        server.should_exit = True
        return True

    async def watchdog() -> None:
        """Quit when the last tab was closed (bye + no heartbeat for 45 s), or after a long silence.

        A silence alone isn't enough for a quick quit: Safari pauses timers in hidden tabs, so a
        tab in the background may not send heartbeats for a long time while still being open.
        """
        import time
        while True:
            await asyncio.sleep(5)
            if not core.settings.get("app.auto_quit", True) or app.state.last_seen is None:
                continue
            t = time.monotonic()
            bye = app.state.bye_at
            if bye is not None and app.state.last_seen <= bye and t - bye > 45:
                request_quit("last tab closed")
                return
            if t - app.state.last_seen > 60 * float(core.settings.get("app.idle_quit_minutes", 30)):
                request_quit("no tab seen for a long time")
                return

    @app.on_event("startup")
    async def _startup() -> None:
        try:
            core.daily_backup()
            core.tts.cleanup_cache()
        except Exception:  # pragma: no cover
            log.exception("startup housekeeping failed")
        app.state.watchdog = asyncio.create_task(watchdog())

    app.state.demos = []   # demo server processes started from this instance

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        for d in app.state.demos:          # stop demos started from here
            if d["process"].poll() is None:
                d["process"].terminate()
        if DEMO:                           # a demo never unloads shared models, backs up or quits Ollama
            return
        # Free the RAM used by the model when Parlera quits.
        for model in {core.settings.get("llm.model"), core.settings.get("llm.analysis_model")} - {"", None}:
            await core.llm.unload(model)
        try:
            core.db.backup_to(core.paths.backups / "parlera-last-quit.db")  # extra safety copy
        except Exception:  # pragma: no cover
            pass
        if core.settings.get("app.quit_ollama") == "always":
            import subprocess
            import sys
            if sys.platform == "darwin":
                subprocess.run(["osascript", "-e", 'quit app "Ollama"'], capture_output=True)
            subprocess.run(["pkill", "-x", "ollama"], capture_output=True)

    @app.exception_handler(ValueError)
    async def _value_error(_: Request, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(LLMError)
    async def _llm_error(_: Request, exc: LLMError):
        return JSONResponse({"detail": str(exc)}, status_code=502)

    @app.exception_handler(AnkiError)
    async def _anki_error(_: Request, exc: AnkiError):
        return JSONResponse({"detail": str(exc)}, status_code=502)

    @app.exception_handler(CurriculumError)
    async def _cur_error(_: Request, exc: CurriculumError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(TTSError)
    async def _tts_error(_: Request, exc: TTSError):
        return JSONResponse({"detail": str(exc)}, status_code=500)

    def lang_ok(language: str) -> str:
        if language not in LANGUAGES:
            raise HTTPException(404, f"Unknown language '{language}'")
        return language

    # ------------------------------------------------------------------
    # status & settings
    # ------------------------------------------------------------------
    @app.get("/api/status")
    async def status():
        settings = core.settings.all()
        ollama: dict[str, Any] = {"ok": False, "models": [], "model": settings["llm"]["model"]}
        try:
            ollama["models"] = await core.llm.list_models()
            ollama["ok"] = True
            ollama["model_installed"] = any(
                m == settings["llm"]["model"] or m == settings["llm"]["model"] + ":latest" for m in ollama["models"])
        except Exception as e:
            ollama["error"] = str(e)
        anki_version = await core.anki().version()
        return {
            "version": __version__,
            "data_dir": str(core.paths.root),
            "ollama": ollama,
            "stt": core.stt.status(),
            "tts": core.tts.status(),
            "anki": {"ok": anki_version is not None, "version": anki_version},
            "demo": DEMO,
            "languages": LANGUAGES,
            "modes": MODES,
        }

    @app.get("/api/settings/export")
    async def settings_export():
        return Response(json.dumps(core.settings.all(), indent=2, ensure_ascii=False), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="parlera-settings-{date.today().isoformat()}.json"'})

    @app.post("/api/settings/import")
    async def settings_import(file: UploadFile = File(...)):
        try:
            data = json.loads((await file.read()).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(400, "Not a valid settings file.")
        if not isinstance(data, dict) or not ({"llm", "tts", "ui"} & set(data)):
            raise HTTPException(400, "This doesn't look like a Parlera settings file.")
        return core.settings.update(data)

    @app.post("/api/demo/start")
    async def demo_start(body: dict = Body(default={})):
        if DEMO:
            raise HTTPException(400, "You're already in demo mode.")
        from .demo import spawn_demo
        app.state.demos = [d for d in app.state.demos if d["process"].poll() is None]
        d = await asyncio.to_thread(spawn_demo, core.paths.root, body.get("mode", "copy"), body.get("open_window", True))
        app.state.demos.append(d)
        return {"url": d["url"], "port": d["port"]}

    @app.get("/api/system")
    async def system_info():
        from .system import cache_info, find_app_browser, hf_hub_dir, needed_hf_models, hf_cached
        needed = needed_hf_models(core.settings.all())
        return {
            "offline": getattr(app.state, "offline", None),
            "models": [{"repo": r, "downloaded": hf_cached(r)} for r in needed],
            "hf_cache": str(hf_hub_dir()),
            "app_browser": find_app_browser(),
            "cache": cache_info(core.paths, core.paths.browser_profile),
        }

    @app.post("/api/cache/clear")
    async def cache_clear(body: dict = Body(...)):
        from .system import clear_cache
        targets = [t for t in body.get("targets", []) if t in ("tts", "media", "old_backups", "browser")]
        return clear_cache(core.paths, core.paths.browser_profile, targets)

    @app.post("/api/heartbeat")
    async def heartbeat():
        import time
        app.state.last_seen = time.monotonic()
        app.state.bye_at = None
        return {"ok": True, "build": app.state.build}

    @app.post("/api/bye")
    async def bye():
        """A tab was closed: quit in ~45 s unless another tab (or a reload) sends a heartbeat."""
        import time
        if app.state.last_seen is not None:
            app.state.bye_at = time.monotonic()
        return {"ok": True}

    @app.post("/api/shutdown")
    async def shutdown():
        ok = request_quit("Quit button")
        return {"ok": ok, "detail": None if ok else "Parlera wasn't started by run.sh; stop it in its terminal."}

    @app.get("/api/settings")
    async def get_settings():
        return core.settings.all()

    @app.put("/api/settings")
    async def put_settings(patch: dict = Body(...)):
        return core.settings.update(patch)

    @app.get("/api/models")
    async def models():
        return {"models": await core.llm.list_models()}

    # ------------------------------------------------------------------
    # dashboard / learner / curriculum
    # ------------------------------------------------------------------
    @app.get("/api/dashboard/{language}")
    async def dashboard(language: str):
        lang_ok(language)
        learner = core.learner(language)
        unit = core.current_unit(language)
        prog = core.db.ensure_unit(language, unit["id"])
        recent = core.db.all("SELECT * FROM sessions WHERE language=? ORDER BY updated_at DESC LIMIT 6", [language])
        for s in recent:
            s.pop("analysis", None)
            s["duration"] = core.session_duration(s["id"])
        weak = core.weak_vocab(language, 10)
        for v in weak:
            v["display"] = display_word(v)
        return {
            "learner": learner,
            "unit": unit,
            "unit_progress": prog,
            "next_unit": core.curricula.next_unit(language, unit["id"]),
            "immersion": core.immersion(language, unit),
            "stats": core.stats(language),
            "recent_sessions": recent,
            "errors": core.recurring_errors(language, 6),
            "weak_vocab": weak,
            "exam": core.exam_for_level(language, unit["level"]),
            "workshop": core.workshop_status(language),
        }

    @app.put("/api/learner/{language}")
    async def put_learner(language: str, body: dict = Body(...)):
        lang_ok(language)
        core.learner(language)
        if "current_unit_id" in body:
            core.set_current_unit(language, body["current_unit_id"], bool(body.get("complete_previous")))
        if "notes" in body:
            core.db.update("learner", language, {"notes": body["notes"]}, key="language")
        return core.learner(language)

    @app.post("/api/learner/{language}/advance")
    async def advance(language: str):
        lang_ok(language)
        nxt = core.advance(language)
        return {"next": nxt}

    @app.get("/api/curriculum/{language}")
    async def curriculum(language: str):
        lang_ok(language)
        data = core.curricula.get(language)
        learner = core.learner(language)
        return {"curriculum": data, "progress": core.db.unit_progress_map(language),
                "current_unit_id": learner["current_unit_id"]}

    @app.get("/api/curriculum/{language}/raw", response_class=PlainTextResponse)
    async def curriculum_raw(language: str):
        lang_ok(language)
        return core.curricula.raw(language)

    @app.put("/api/curriculum/{language}/raw")
    async def curriculum_save(language: str, body: dict = Body(...)):
        lang_ok(language)
        data = core.curricula.save_raw(language, body.get("text", ""))
        core.learner(language)  # re-validate current unit
        return {"ok": True, "units": len(data["units"])}

    @app.post("/api/curriculum/{language}/validate")
    async def curriculum_validate(language: str, body: dict = Body(...)):
        import yaml
        from .curriculum import normalize, validate
        try:
            data = normalize(validate(yaml.safe_load(body.get("text", ""))))
        except yaml.YAMLError as e:
            return {"ok": False, "error": f"YAML syntax error: {e}"}
        except CurriculumError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "units": len(data["units"]), "levels": [lv["code"] for lv in data["levels"]]}

    @app.post("/api/curriculum/{language}/reset")
    async def curriculum_reset(language: str):
        lang_ok(language)
        src = DEFAULTS_DIR / "curricula" / f"{language}.yaml"
        core.curricula.save_raw(language, src.read_text(encoding="utf-8"))
        return {"ok": True}

    @app.post("/api/curriculum/{language}/units/{unit_id}")
    async def unit_action(language: str, unit_id: str, body: dict = Body(...)):
        lang_ok(language)
        action = body.get("action")
        if action == "set_current":
            core.set_current_unit(language, unit_id, bool(body.get("complete_previous")))
        elif action in ("completed", "active"):
            core.set_unit_status(language, unit_id, action)
        elif action == "reset":
            core.db.execute("DELETE FROM unit_progress WHERE language=? AND unit_id=?", [language, unit_id])
        else:
            raise HTTPException(400, "Unknown action")
        return {"ok": True, "progress": core.db.unit_progress_map(language)}

    # ------------------------------------------------------------------
    # prompts
    # ------------------------------------------------------------------
    @app.get("/api/prompts")
    async def prompts_list():
        return [core.prompts.info(n) for n in core.prompts.names()]

    @app.get("/api/prompts/{name}")
    async def prompt_get(name: str):
        try:
            return {**core.prompts.info(name), "text": core.prompts.read(name),
                    "default": core.prompts.default(name)}
        except FileNotFoundError:
            raise HTTPException(404, "Prompt not found")

    @app.put("/api/prompts/{name}")
    async def prompt_put(name: str, body: dict = Body(...)):
        core.prompts.write(name, body.get("text", ""))
        return core.prompts.info(name)

    @app.post("/api/prompts/{name}/reset")
    async def prompt_reset(name: str):
        try:
            core.prompts.reset(name)
        except FileNotFoundError:
            raise HTTPException(404, "No default for this prompt")
        return {**core.prompts.info(name), "text": core.prompts.read(name)}

    @app.post("/api/prompts-preview")
    async def prompt_preview(body: dict = Body(...)):
        language = lang_ok(body.get("language", "sv"))
        ctx = core.build_context(language, body.get("mode", "lesson"), body.get("unit_id"),
                                 body.get("scenario", ""), body.get("focus", ""))
        system = core.render_system_prompt(ctx)
        return {"system": system, "opening": core.prompts.render("opening", **ctx),
                "chars": len(system), "approx_tokens": len(system) // 4}

    # ------------------------------------------------------------------
    # sessions
    # ------------------------------------------------------------------
    @app.post("/api/sessions")
    async def session_create(body: dict = Body(...)):
        # Fresh Anki review data → better choice of words to reinforce in this session.
        if core.settings.get("anki.auto_sync", True) and body.get("language") in LANGUAGES:
            try:
                await asyncio.wait_for(core.sync_anki(body["language"]), timeout=4)
            except Exception:
                pass
        s = core.create_session(body.get("language"), body.get("mode", "lesson"), body.get("unit_id"),
                                body.get("scenario", ""), body.get("focus", ""))
        return s

    @app.post("/api/teacher-note/parse")
    async def teacher_note_parse(body: dict = Body(...)):
        return {"items": await core.parse_teacher_note(lang_ok(body.get("language", "")), body.get("text", ""))}

    @app.post("/api/directives")
    async def directives_save(body: dict = Body(...)):
        return core.save_directives(lang_ok(body.get("language", "")), body.get("items", []), body.get("text", ""))

    @app.get("/api/directives")
    async def directives_list(language: str):
        rows = core.db.all("SELECT * FROM directives WHERE language IS NULL OR language=? ORDER BY created_at DESC",
                           [lang_ok(language)])
        ts = now()
        for r in rows:
            r["expired"] = bool(r["expires_at"] and r["expires_at"] <= ts)
        return rows

    @app.patch("/api/directives/{did}")
    async def directive_patch(did: int, body: dict = Body(...)):
        patch = {k: v for k, v in body.items() if k in ("content", "active", "expires_at")}
        core.db.update("directives", did, patch)
        return core.db.one("SELECT * FROM directives WHERE id=?", [did])

    @app.delete("/api/directives/{did}")
    async def directive_delete(did: int):
        core.db.execute("DELETE FROM directives WHERE id=?", [did])
        return {"ok": True}

    # ------------------------------------------------------------------
    # Practice: quick games (no LLM) + grammar lectures
    # ------------------------------------------------------------------
    @app.get("/api/practice/{language}")
    async def practice_overview(language: str):
        lang_ok(language)
        unit = core.current_unit(language)
        return {"stats": practice.stats(core.db, language),
                "topics": practice.grammar_topics(core.curricula.get(language), unit),
                "lectures": core.lectures(language),
                "unit": {"id": unit["id"], "title": unit["title"], "level": unit["level"]} if unit else None,
                "counts": practice.build_pool(core, language, "mix", 4)["counts"],
                "round_length": int(core.settings.get("practice.round_length", 10) or 10)}

    @app.get("/api/practice/{language}/items")
    async def practice_items(language: str, source: str = "mix", count: int = 40):
        lang_ok(language)
        return practice.build_pool(core, language, source, max(4, min(count, 120)))

    @app.post("/api/practice/{language}/results")
    async def practice_results(language: str, body: dict = Body(...)):
        lang_ok(language)
        results = [r for r in (body.get("results") or []) if isinstance(r, dict)][:200]
        return practice.record_results(core.db, language, str(body.get("game") or ""), str(body.get("source") or ""),
                                       results, int(body.get("seconds") or 0))

    @app.get("/api/lectures")
    async def lectures_list(language: str = "sv"):
        return core.lectures(lang_ok(language))

    @app.post("/api/lectures")
    async def lectures_create(body: dict = Body(...)):
        return await core.create_lecture(lang_ok(body.get("language", "sv")), body.get("topic", ""),
                                         body.get("unit_id") or None)

    @app.get("/api/lectures/{lid}")
    async def lecture_get(lid: int):
        lec = core.lecture(lid)
        if not lec:
            raise HTTPException(404, "Lecture not found")
        return lec

    @app.post("/api/lectures/{lid}/ask")
    async def lecture_ask(lid: int, body: dict = Body(...)):
        return await core.ask_lecture(lid, body.get("question", ""))

    @app.delete("/api/lectures/{lid}")
    async def lecture_delete(lid: int):
        core.db.execute("DELETE FROM lectures WHERE id=?", [lid])
        return {"ok": True}

    @app.get("/api/workshops/status/{language}")
    async def workshop_status(language: str):
        return core.workshop_status(lang_ok(language))

    @app.post("/api/workshops")
    async def workshop_create(body: dict = Body(...)):
        return await core.create_workshop(lang_ok(body.get("language", "")))

    @app.get("/api/sessions")
    async def sessions_list(language: str | None = None, limit: int = 200):
        sql = "SELECT * FROM sessions"
        params: list[Any] = []
        if language:
            sql += " WHERE language=?"
            params.append(language)
        rows = core.db.all(sql + " ORDER BY created_at DESC LIMIT ?", [*params, limit])
        for r in rows:
            r.pop("analysis", None)
            r["duration"] = core.session_duration(r["id"])
            r["turns"] = core.db.scalar(
                "SELECT COUNT(*) FROM messages WHERE session_id=? AND hidden=0 AND role='user'", [r["id"]])
            unit = core.curricula.unit(r["language"], r["unit_id"]) if r.get("unit_id") else None
            r["unit_title"] = unit["title"] if unit else ""
            r["unit_level"] = unit["level"] if unit else ""
        return rows

    @app.get("/api/sessions/{sid}")
    async def session_get(sid: int):
        s = core.session_view(sid)
        if not s:
            raise HTTPException(404, "Session not found")
        return s

    @app.patch("/api/sessions/{sid}")
    async def session_patch(sid: int, body: dict = Body(...)):
        allowed = {k: v for k, v in body.items() if k in ("title", "status")}
        core.db.update("sessions", sid, allowed)
        return core.db.session(sid)

    @app.delete("/api/sessions/{sid}")
    async def session_delete(sid: int):
        core.db.execute("DELETE FROM vocab WHERE session_id=? AND status='candidate'", [sid])
        core.db.execute("DELETE FROM sessions WHERE id=?", [sid])
        return {"ok": True}

    @app.post("/api/sessions/{sid}/end")
    async def session_end(sid: int):
        result = await core.analyze_session(sid)
        return {"analysis": result, "session": core.session_view(sid)}

    @app.delete("/api/messages/{mid}")
    async def message_delete(mid: int):
        core.db.execute("DELETE FROM messages WHERE id=?", [mid])
        return {"ok": True}

    @app.get("/api/sessions/{sid}/export.md")
    async def session_export(sid: int):
        s = core.session_view(sid)
        if not s:
            raise HTTPException(404)
        a = s.get("analysis") or {}
        lines = [f"# {s['title']}", "", f"*{s['created_at'][:16].replace('T', ' ')} · {s['mode_info'].get('title', s['mode'])}"
                 f" · {round(s['duration'] / 60)} min*", ""]
        if a.get("feedback"):
            lines += ["## Feedback", "", a["feedback"], ""]
        if a.get("errors"):
            lines += ["## Mistakes", ""] + [f"- ~~{e.get('wrong')}~~ → **{e.get('right')}** — {e.get('explanation')}"
                                            for e in a["errors"]] + [""]
        lines += ["## Transcript", ""]
        for m in s["messages"]:
            who = "**You**" if m["role"] == "user" else "**Tutor**"
            lines += [f"{who}: {m['content']}", ""]
        name = f"parlera-session-{sid}.md"
        return Response("\n".join(lines), media_type="text/markdown",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.websocket("/ws/sessions/{sid}")
    async def session_ws(ws: WebSocket, sid: int):
        await TutorSession(core, ws, sid).run()

    # ------------------------------------------------------------------
    # vocabulary & Anki
    # ------------------------------------------------------------------
    @app.get("/api/vocab")
    async def vocab_list(language: str | None = None, status: str | None = None, q: str | None = None):
        sql, params = "SELECT * FROM vocab WHERE 1=1", []
        if language:
            sql += " AND language=?"
            params.append(language)
        if status:
            sql += " AND status=?"
            params.append(status)
        if q:
            sql += " AND (lemma LIKE ? OR translation LIKE ? OR example LIKE ?)"
            params += [f"%{q}%"] * 3
        rows = core.db.all(sql + " ORDER BY created_at DESC, id DESC", params)
        for r in rows:
            r["display"] = display_word(r)
        return rows

    @app.post("/api/vocab")
    async def vocab_add(body: dict = Body(...)):
        row = core.add_manual_vocab(lang_ok(body.get("language", "")), body)
        row["display"] = display_word(row)
        return row

    @app.post("/api/vocab/autofill")
    async def vocab_autofill(body: dict = Body(...)):
        return await core.autofill_vocab(lang_ok(body.get("language", "")), body.get("word", ""),
                                         body.get("context", ""))

    @app.patch("/api/vocab/{vid}")
    async def vocab_patch(vid: int, body: dict = Body(...)):
        fields = ("lemma", "forms", "gender", "pos", "translation", "example", "example_translation", "notes",
                  "status", "unit_id")
        patch = {k: v for k, v in body.items() if k in fields}
        if "lemma" in patch:
            patch["lemma_norm"] = norm(patch["lemma"])
        patch["updated_at"] = now()
        core.db.update("vocab", vid, patch)
        row = core.db.one("SELECT * FROM vocab WHERE id=?", [vid])
        if row:
            row["display"] = display_word(row)
        return row

    @app.delete("/api/vocab/{vid}")
    async def vocab_delete(vid: int):
        core.db.execute("DELETE FROM vocab WHERE id=?", [vid])
        return {"ok": True}

    @app.post("/api/vocab/bulk")
    async def vocab_bulk(body: dict = Body(...)):
        ids = [int(i) for i in body.get("ids", [])]
        action = body.get("action")
        result: dict[str, Any] = {"ok": True}
        if action in ("accept", "anki"):
            for i in ids:
                core.db.execute("UPDATE vocab SET status='learning', updated_at=? WHERE id=? AND status IN "
                                "('candidate','ignored')", [now(), i])
            if action == "anki":
                result.update(await core.push_to_anki(ids))
        elif action == "ignore":
            for i in ids:
                core.db.execute("UPDATE vocab SET status='ignored', updated_at=? WHERE id=?", [now(), i])
        elif action == "known":
            for i in ids:
                core.db.execute("UPDATE vocab SET status='known', updated_at=? WHERE id=?", [now(), i])
        elif action == "unanki":
            result["removed"] = await core.remove_from_anki(ids)
        elif action == "delete":
            for i in ids:
                core.db.execute("DELETE FROM vocab WHERE id=?", [i])
        else:
            raise HTTPException(400, "Unknown action")
        return result

    @app.post("/api/anki/sync")
    async def anki_sync(body: dict = Body(default={})):
        return await core.sync_anki(body.get("language"))

    @app.post("/api/anki/push-pending")
    async def anki_push_pending(body: dict = Body(default={})):
        if await core.anki().version() is None:
            return {"added": [], "failed": [], "offline": True}
        return await core.push_pending(body.get("language"))

    @app.get("/api/anki/decks")
    async def anki_decks():
        if await core.anki().version() is None:
            return {"ok": False, "decks": []}
        return {"ok": True, "decks": await core.anki().deck_names()}

    @app.get("/api/anki/deck-preview")
    async def anki_deck_preview(deck: str):
        notes = await core.anki().deck_notes(deck)
        fields: list[str] = []
        for n in notes:
            for f in n["order"]:
                if f not in fields:
                    fields.append(f)
        return {"count": len(notes), "fields": fields, "models": sorted({n["modelName"] for n in notes}),
                "sample": [n["fields"] for n in notes[:6]]}

    @app.post("/api/anki/import")
    async def anki_import(body: dict = Body(...)):
        if not body.get("deck") or not body.get("word_field"):
            raise HTTPException(400, "Choose a deck and the field that contains the word.")
        return await core.import_anki_deck(lang_ok(body.get("language", "")), body["deck"], body["word_field"],
                                           body.get("meaning_field", ""), body.get("example_field", ""))

    @app.get("/api/anki/test")
    async def anki_test():
        v = await core.anki().version()
        if v is None:
            raise HTTPException(502, "AnkiConnect not reachable. Open Anki and install the AnkiConnect add-on (code 2055492159).")
        decks = await core.anki().invoke("deckNames")
        return {"version": v, "decks": decks}

    @app.post("/api/vocab/export.apkg")
    async def vocab_apkg(body: dict = Body(...)):
        ids = [int(i) for i in body.get("ids", [])]
        if not ids and body.get("language"):
            ids = [r["id"] for r in core.db.all(
                "SELECT id FROM vocab WHERE language=? AND status IN ('learning','known')", [body["language"]])]
        tmp = Path(tempfile.mkdtemp())
        out = await asyncio.to_thread(core.export_apkg, ids, tmp / "parlera.apkg")
        return FileResponse(out, filename=f"parlera-{date.today().isoformat()}.apkg",
                            media_type="application/octet-stream",
                            background=BackgroundTask(shutil.rmtree, tmp, ignore_errors=True))

    @app.get("/api/vocab/export.csv")
    async def vocab_csv(language: str | None = None):
        rows = await vocab_list(language=language)
        buf = io.StringIO()
        w = csv.writer(buf)
        cols = ["display", "translation", "pos", "gender", "forms", "example", "example_translation", "notes",
                "status", "unit_id", "anki_interval", "created_at"]
        w.writerow(cols)
        for r in rows:
            w.writerow([r.get(c, "") for c in cols])
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="parlera-vocab.csv"'})

    # ------------------------------------------------------------------
    # memories & errors
    # ------------------------------------------------------------------
    @app.get("/api/memories")
    async def memories(language: str | None = None):
        if language:
            return core.db.all("SELECT * FROM memories WHERE language IS NULL OR language=? "
                               "ORDER BY pinned DESC, updated_at DESC", [language])
        return core.db.all("SELECT * FROM memories ORDER BY pinned DESC, updated_at DESC")

    @app.post("/api/memories")
    async def memory_add(body: dict = Body(...)):
        content = (body.get("content") or "").strip()
        if not content:
            raise HTTPException(400, "Memory is empty")
        ts = now()
        mid = core.db.insert("memories", {"language": body.get("language") or None,
                                          "category": body.get("category") or "personal", "content": content,
                                          "pinned": int(bool(body.get("pinned"))), "active": 1,
                                          "created_at": ts, "updated_at": ts})
        return core.db.one("SELECT * FROM memories WHERE id=?", [mid])

    @app.patch("/api/memories/{mid}")
    async def memory_patch(mid: int, body: dict = Body(...)):
        patch = {k: v for k, v in body.items() if k in ("content", "category", "pinned", "active", "language")}
        if "language" in patch and not patch["language"]:
            patch["language"] = None
        patch["updated_at"] = now()
        core.db.update("memories", mid, patch)
        return core.db.one("SELECT * FROM memories WHERE id=?", [mid])

    @app.delete("/api/memories/{mid}")
    async def memory_delete(mid: int):
        core.db.execute("DELETE FROM memories WHERE id=?", [mid])
        return {"ok": True}

    @app.get("/api/errors")
    async def errors(language: str):
        return core.db.all("SELECT * FROM errors WHERE language=? ORDER BY resolved, count DESC, last_seen DESC",
                           [language])

    @app.patch("/api/errors/{eid}")
    async def error_patch(eid: int, body: dict = Body(...)):
        patch = {k: v for k, v in body.items() if k in ("resolved", "pattern", "explanation", "example_wrong",
                                                       "example_right")}
        core.db.update("errors", eid, patch)
        return core.db.one("SELECT * FROM errors WHERE id=?", [eid])

    @app.delete("/api/errors/{eid}")
    async def error_delete(eid: int):
        core.db.execute("DELETE FROM errors WHERE id=?", [eid])
        return {"ok": True}

    # ------------------------------------------------------------------
    # speech
    # ------------------------------------------------------------------
    @app.post("/api/stt")
    async def stt(file: UploadFile = File(...), language: str = Form("")):
        data = await file.read()
        return await asyncio.to_thread(core.stt.transcribe, data, language or None, None)

    @app.post("/api/speak")
    async def speak(body: dict = Body(...)):
        language = lang_ok(body.get("language", "sv"))
        text = body.get("text", "")
        segs = segment_languages(text, language) if body.get("mixed", True) else [{"lang": body.get("lang", language),
                                                                                    "text": text}]
        rate = float(body.get("rate", 1.0))
        rates = {"en": rate, language: rate * (0.75 if body.get("slow") else 1.0)}
        wav = await asyncio.to_thread(core.tts.synth_segments, segs, rates, language)
        return Response(wav, media_type="audio/wav")

    @app.post("/api/segments")
    async def segments(body: dict = Body(...)):
        language = lang_ok(body.get("language", "sv"))
        from .textproc import SentenceStream
        s = SentenceStream()
        out = []
        for sentence, _ in s.feed(body.get("text", "") + " ") + s.flush():
            out += segment_languages(sentence, language)
        return {"segments": out, "engine": core.tts.engine()}

    @app.get("/api/tts/voices")
    async def tts_voices(engine: str = "macos", refresh: bool = False):
        if engine == "macos" and refresh:
            core.tts.macos_voices(refresh=True)
        return {lang: core.tts.voices(engine, lang) for lang in ("fr", "sv", "en")}

    @app.get("/api/tts/engines")
    async def tts_engines():
        return {"available": core.tts.available_engines(), "default": core.tts.engine(),
                "per_language": {lang: core.tts.engine_for(lang) for lang in ("fr", "sv", "en")}}

    @app.get("/api/tts/piper/catalog")
    async def piper_catalog():
        installed = {v["name"] for v in core.tts.piper_voices()}
        import importlib.util
        return {"installed_package": importlib.util.find_spec("piper") is not None,
                "voices": [{**v, "installed": v["name"] in installed} for v in PIPER_CATALOG]}

    @app.post("/api/tts/piper/download")
    async def piper_download(body: dict = Body(...)):
        entry = next((v for v in PIPER_CATALOG if v["name"] == body.get("name")), None)
        if not entry:
            raise HTTPException(404, "Unknown voice")
        async with httpx.AsyncClient(timeout=600, follow_redirects=True) as client:
            for suffix in (".onnx", ".onnx.json"):
                url = f"{PIPER_BASE}/{entry['path']}/{entry['name']}{suffix}"
                dest = core.paths.voices / f"{entry['name']}{suffix}"
                tmp = dest.with_suffix(dest.suffix + ".part")
                async with client.stream("GET", url) as r:
                    if r.status_code != 200:
                        raise HTTPException(502, f"Download failed ({r.status_code}) for {url}")
                    with open(tmp, "wb") as f:
                        async for chunk in r.aiter_bytes():
                            f.write(chunk)
                tmp.replace(dest)
        return {"ok": True}

    @app.post("/api/tts/test")
    async def tts_test(body: dict = Body(...)):
        lang = body.get("lang", "sv")
        name = core.teacher(lang_ok(lang))["name"]
        samples = {"sv": f"Hej! Jag heter {name}. Välkommen till din svensklektion.",
                   "fr": f"Bonjour ! Je m'appelle {name}. Bienvenue à ton cours de français.",
                   "en": f"Hi, I'm {name}. Let's get your English to the next level."}
        speaker = body.get("speaker") or lang
        wav = await asyncio.to_thread(core.tts.synth, body.get("text") or samples.get(lang, "Hello"), lang, 1.0, speaker)
        return Response(wav, media_type="audio/wav")

    @app.post("/api/translate")
    async def translate(body: dict = Body(...)):
        language = lang_ok(body.get("language", "sv"))
        direction = body.get("direction", "to_native")
        ctx = {"language": language, "language_name": LANGUAGES[language]["name"],
               "native_language": core.settings.get("learner.native_language") or "English",
               "direction": direction, "text": body.get("text", "")}
        level = core.current_unit(language)["level"]
        ctx["level"] = level
        out = await core.llm.chat(
            [{"role": "system", "content": core.prompts.render("translate", **ctx)},
             {"role": "user", "content": body.get("text", "")}], options={"temperature": 0.2})
        return {"text": out.strip()}

    # ------------------------------------------------------------------
    # backup / restore
    # ------------------------------------------------------------------
    @app.get("/api/backup")
    async def backup():
        tmp = Path(tempfile.mkdtemp())
        db_copy = tmp / "parlera.db"
        core.db.backup_to(db_copy)
        out = tmp / "backup.zip"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(db_copy, "parlera.db")
            z.write(core.paths.settings, "settings.json") if core.paths.settings.exists() else None
            for sub in ("prompts", "curricula"):
                for f in getattr(core.paths, sub).glob("*"):
                    if f.is_file():
                        z.write(f, f"{sub}/{f.name}")
            z.writestr("manifest.json", json.dumps({"app": "parlera", "version": __version__, "created": now()}))
        return FileResponse(out, filename=f"parlera-backup-{date.today().isoformat()}.zip",
                            media_type="application/zip",
                            background=BackgroundTask(shutil.rmtree, tmp, ignore_errors=True))

    @app.post("/api/restore")
    async def restore(file: UploadFile = File(...)):
        data = await file.read()
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise HTTPException(400, "Not a zip file")
        names = z.namelist()
        if "parlera.db" not in names or "manifest.json" not in names:
            raise HTTPException(400, "This doesn't look like a Parlera backup.")
        # keep a safety copy of the current state
        core.db.backup_to(core.paths.backups / f"before-restore-{now().replace(':', '-')}.db")
        with tempfile.TemporaryDirectory() as td:
            z.extractall(td)
            td_path = Path(td)
            core.db.close()
            shutil.copy2(td_path / "parlera.db", core.paths.db)
            for suffix in ("-wal", "-shm"):
                Path(str(core.paths.db) + suffix).unlink(missing_ok=True)
            if (td_path / "settings.json").exists():
                shutil.copy2(td_path / "settings.json", core.paths.settings)
            for sub in ("prompts", "curricula"):
                src = td_path / sub
                if src.exists():
                    for f in src.iterdir():
                        if f.is_file() and f.suffix in (".md", ".yaml", ".yml"):
                            shutil.copy2(f, getattr(core.paths, sub) / f.name)
        from .db import DB
        core.db = DB(core.paths.db)
        core.settings.reload()
        core.curricula._cache.clear()
        return {"ok": True}

    # ------------------------------------------------------------------
    # static GUI
    # ------------------------------------------------------------------
    # Versioned asset URLs: every code change gets a new /static/v-<build>/ prefix, so a browser can
    # never mix cached files from an older version with new ones (that left Safari with a blank page).
    build = static_build_id()
    app.state.build = build

    @app.get("/static/v-{build_id}/{path:path}")
    async def versioned_static(build_id: str, path: str):
        target = (STATIC_DIR / path).resolve()
        if STATIC_DIR.resolve() not in target.parents or not target.is_file():
            raise HTTPException(404)
        cache = "public, max-age=31536000, immutable" if build_id == build else "no-cache"
        return FileResponse(target, headers={"Cache-Control": cache})

    @app.middleware("http")
    async def no_stale_static(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/") and not request.url.path.startswith("/static/v-"):
            response.headers["Cache-Control"] = "no-cache"   # always revalidate unversioned files
        return response

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    async def index():
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        html = (html.replace('/static/js/', f'/static/v-{build}/js/')
                    .replace('/static/css/', f'/static/v-{build}/css/')
                    .replace("__BUILD__", build))
        return Response(html, media_type="text/html", headers={"Cache-Control": "no-cache, no-store"})

    return app
