"""Live conversation over a WebSocket: STT -> LLM (streamed) -> sentence-level TTS.

Client -> server messages:
    {"type": "start", "resume": bool}
    {"type": "user_text", "text": "..."}
    {"type": "user_audio", "data": "<base64 wav>", "lang": "target|en|auto"}
    {"type": "interrupt"}
    {"type": "settings", "audio": bool}          # mute/unmute speech for this session

Server -> client messages:
    {"type": "ready", ...}
    {"type": "transcribing"} / {"type": "transcript", "text": "...", "message_id": n}
    {"type": "assistant_start"}
    {"type": "token", "text": "..."}
    {"type": "audio", "data": "<base64 wav>", "text": "..."}          # server TTS
    {"type": "speak", "segments": [{"lang": "sv", "text": "..."}]}    # browser TTS
    {"type": "assistant_end", "message_id": n, "content": "..."}
    {"type": "audio_end"}
    {"type": "error", "message": "..."}
"""
from __future__ import annotations

import asyncio
import base64
import logging
from datetime import datetime

from fastapi import WebSocket, WebSocketDisconnect

from .core import Parlera
from .llm import LLMError
from .textproc import SentenceStream, segment_languages

log = logging.getLogger("parlera.tutor")

RESUME_AFTER_SECONDS = 20 * 60


class TutorSession:
    def __init__(self, app: Parlera, ws: WebSocket, session_id: int):
        self.app = app
        self.ws = ws
        self.sid = session_id
        self.session = app.db.session(session_id)
        self.send_lock = asyncio.Lock()
        self.task: asyncio.Task | None = None
        self.audio_enabled = True
        self.system_prompt: str | None = None

    @property
    def target(self) -> str:
        return self.session["language"]

    async def send(self, data: dict) -> None:
        async with self.send_lock:
            try:
                await self.ws.send_json(data)
            except (RuntimeError, WebSocketDisconnect):
                pass

    def _system(self) -> str:
        if self.system_prompt is None:
            self.system_prompt = self.app.system_prompt(self.session)
        return self.system_prompt

    def _rates(self) -> dict[str, float]:
        if not self.app.settings.get("tts.beginner_slowdown", True):
            return {}
        unit = self.app.curricula.unit(self.target, self.session.get("unit_id"))
        level = unit["level"] if unit else "A1"
        return {self.target: {"A1": 0.82, "A2": 0.9}.get(level, 1.0)}

    def _tts_mode(self) -> str:
        if not self.audio_enabled:
            return "off"
        engine = self.app.tts.engine()
        return engine if engine in ("off", "browser") else "server"

    # ------------------------------------------------------------------
    async def run(self) -> None:
        await self.ws.accept()
        if not self.session:
            await self.send({"type": "error", "message": "Session not found."})
            await self.ws.close()
            return
        await self.send({"type": "ready", "tts": self._tts_mode(), "stt": self.app.stt.status()})
        # Warm up the model (and speech recognition) in the background.
        asyncio.create_task(self.app.llm.warm())
        if self.app.stt.backend():
            asyncio.get_running_loop().run_in_executor(None, self.app.stt.preload, self.target)
        try:
            while True:
                msg = await self.ws.receive_json()
                await self.handle(msg)
        except WebSocketDisconnect:
            pass
        finally:
            if self.task and not self.task.done():
                self.task.cancel()

    async def handle(self, msg: dict) -> None:
        t = msg.get("type")
        if t == "start":
            visible = self.app.db.messages(self.sid, include_hidden=False)
            if not visible:
                self.app.db.add_message(self.sid, "user", self.app.prompts.render(
                    "opening", **self.app.build_context(self.target, self.session["mode"],
                                                        self.session.get("unit_id"), self.session.get("scenario", ""),
                                                        self.session.get("focus", ""), self.sid)), hidden=True)
                self.start_turn()
            else:
                last = datetime.fromisoformat(visible[-1]["created_at"])
                if msg.get("resume") and (datetime.now() - last).total_seconds() > RESUME_AFTER_SECONDS:
                    self.app.db.add_message(self.sid, "user", self.app.prompts.render(
                        "resume", **self.app.build_context(self.target, self.session["mode"],
                                                           self.session.get("unit_id"))), hidden=True)
                    self.start_turn()
            if self.session["status"] == "completed":
                self.app.db.update("sessions", self.sid, {"status": "active"})
                self.session["status"] = "active"
        elif t == "user_text":
            text = (msg.get("text") or "").strip()
            if text:
                await self.cancel()
                mid = self.app.db.add_message(self.sid, "user", text, meta={"input": "text"})
                await self.send({"type": "user_saved", "message_id": mid})
                self.start_turn()
        elif t == "user_audio":
            await self.cancel()
            await self.on_audio(msg)
        elif t == "interrupt":
            await self.cancel()
        elif t == "settings":
            if "audio" in msg:
                self.audio_enabled = bool(msg["audio"])
        elif t == "ping":
            await self.send({"type": "pong"})

    async def on_audio(self, msg: dict) -> None:
        try:
            wav = base64.b64decode(msg.get("data") or "")
        except ValueError:
            await self.send({"type": "error", "message": "Invalid audio data."})
            return
        choice = msg.get("lang") or self.app.settings.get("stt.default_input_language", "target")
        lang = {"target": self.target, "en": "en", "auto": None}.get(choice, self.target)
        unit = self.app.curricula.unit(self.target, self.session.get("unit_id"))
        prompt = None
        # Bias Whisper towards the unit's words — except in pronunciation practice, where we
        # want to hear what the learner really said, not what they were supposed to say.
        if unit and lang == self.target and self.session["mode"] != "pronunciation":
            prompt = ", ".join(p["term"] for p in unit["vocab_pairs"][:25])
        await self.send({"type": "transcribing"})
        try:
            res = await asyncio.get_running_loop().run_in_executor(
                None, self.app.stt.transcribe, wav, lang, prompt)
        except Exception as e:
            log.exception("transcription failed")
            await self.send({"type": "error", "message": f"Speech recognition failed: {e}"})
            await self.send({"type": "transcript", "text": "", "empty": True})
            return
        text = res.get("text", "").strip()
        if not text:
            await self.send({"type": "transcript", "text": "", "empty": True})
            return
        meta = {"input": "voice", "stt_lang": res.get("language"), "words": res.get("words") or []}
        pron = None
        if self.app.settings.get("stt.pronunciation_hints", True) and lang != "en":
            from .pronunciation import analyse
            last = next((m["content"] for m in reversed(self.app.db.messages(self.sid, include_hidden=False))
                         if m["role"] == "assistant"), "")
            pron = analyse(meta["words"], text, last, float(self.app.settings.get("stt.confidence_threshold", 0.55)))
            if pron["note"]:
                meta["pron_note"] = pron["note"]
            meta["pron"] = {"low": pron["low"], "rep": pron["rep"]}
        mid = self.app.db.add_message(self.sid, "user", text, meta=meta)
        await self.send({"type": "transcript", "text": text, "message_id": mid,
                         "pron": meta.get("pron")})
        self.start_turn()

    def start_turn(self) -> None:
        self.task = asyncio.create_task(self.turn())

    async def cancel(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):
                pass
        self.task = None

    # ------------------------------------------------------------------
    async def turn(self) -> None:
        messages = self.app.chat_messages(self.session, self._system())
        tts_mode = self._tts_mode()
        speak_corrections = self.app.settings.get("tts.speak_corrections", True)
        queue: asyncio.Queue = asyncio.Queue()
        tts_task = asyncio.create_task(self.tts_worker(queue, tts_mode)) if tts_mode != "off" else None
        stream = SentenceStream()
        full = ""
        saved = False

        def enqueue(items):
            for text, is_correction in items:
                if tts_task and (speak_corrections or not is_correction):
                    queue.put_nowait(text)

        await self.send({"type": "assistant_start"})
        try:
            async for tok in self.app.llm.chat_stream(messages):
                full += tok
                await self.send({"type": "token", "text": tok})
                enqueue(stream.feed(tok))
            enqueue(stream.flush())
            full = full.strip()
            mid = self.app.db.add_message(self.sid, "assistant", full or "…")
            saved = True
            await self.send({"type": "assistant_end", "message_id": mid, "content": full})
            if tts_task:
                queue.put_nowait(None)
                await tts_task
            await self.send({"type": "audio_end"})
        except asyncio.CancelledError:
            if tts_task:
                tts_task.cancel()
            if full.strip() and not saved:
                self.app.db.add_message(self.sid, "assistant", full.strip() + " …", meta={"interrupted": True})
            raise
        except LLMError as e:
            if tts_task:
                tts_task.cancel()
            await self.send({"type": "error", "message": str(e)})
            await self.send({"type": "assistant_end", "message_id": None, "content": full, "failed": True})
        except Exception as e:  # pragma: no cover - defensive
            log.exception("turn failed")
            if tts_task:
                tts_task.cancel()
            await self.send({"type": "error", "message": f"Something went wrong: {e}"})
            await self.send({"type": "assistant_end", "message_id": None, "content": full, "failed": True})

    async def tts_worker(self, queue: asyncio.Queue, mode: str) -> None:
        loop = asyncio.get_running_loop()
        rates = self._rates()
        while True:
            sentence = await queue.get()
            if sentence is None:
                return
            segments = segment_languages(sentence, self.target)
            if not segments:
                continue
            if mode == "browser":
                await self.send({"type": "speak", "segments": segments, "rates": rates})
                continue
            try:
                wav = await loop.run_in_executor(None, self.app.tts.synth_segments, segments, rates)
            except Exception as e:
                log.warning("TTS failed: %s", e)
                await self.send({"type": "speak", "segments": segments, "rates": rates, "fallback": str(e)})
                continue
            if wav:
                await self.send({"type": "audio", "data": base64.b64encode(wav).decode(), "text": sentence})
