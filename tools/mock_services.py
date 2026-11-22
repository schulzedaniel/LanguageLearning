"""Fake Ollama + AnkiConnect servers for development and tests (no GPU or Anki needed).

    python tools/mock_services.py            # Ollama on :11434, AnkiConnect on :8765
"""
from __future__ import annotations

import asyncio
import json
import sys
import threading

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

REPLIES = [
    "Hej och välkommen! I'm Astrid, your Swedish teacher. Let's start with the most important word: **hej** means hello. Can you say **hej**?",
    "Perfect! ✏️ Tiny tip: in Swedish we say **Jag heter Sam** — the verb comes right after **jag**.\nNow tell me your name: **Jag heter …**",
    "Mycket bra! Now let's ask the question back. **Vad heter du?** means *What's your name?* Try asking me!",
    "Jag heter Astrid. **Trevligt att träffas!** That means nice to meet you. Can you say it?",
]

ollama = FastAPI()
state = {"turn": 0}


@ollama.get("/api/tags")
async def tags():
    return {"models": [{"name": "gemma4:26b"}, {"name": "gemma4:26b-mlx"}, {"name": "qwen3:30b-a3b"}]}


@ollama.post("/api/generate")
async def generate():
    return {"done": True}


def fake_json(schema: dict):
    props = (schema or {}).get("properties", {})
    if "items" in props:
        return {"items": [
            {"lemma": "heta", "translation": "to be called", "pos": "verb", "gender": "", "forms": "heta – heter – hette – har hetat",
             "example": "Jag heter Sam.", "example_translation": "My name is Sam.", "reason": "mistake", "notes": "Irregular past."},
            {"lemma": "trevlig", "translation": "nice, pleasant", "pos": "adjective", "gender": "", "forms": "trevlig – trevligt – trevliga",
             "example": "Trevligt att träffas!", "example_translation": "Nice to meet you!", "reason": "unit", "notes": ""},
            {"lemma": "en lärare", "translation": "a teacher", "pos": "noun", "gender": "en", "forms": "en lärare – läraren – lärare – lärarna",
             "example": "Astrid är lärare.", "example_translation": "Astrid is a teacher.", "reason": "new", "notes": ""},
            {"lemma": "xyzzyq", "translation": "nonsense", "pos": "noun", "gender": "ett", "forms": "", "example": "", "example_translation": "", "reason": "new", "notes": ""},
        ]}
    if "unit_mastery" in props:
        return {
            "title": "First greetings in Swedish", "summary": "Practised hej, jag heter and vad heter du. Word order after jag needs work.",
            "feedback": "You did really well for a first lesson! Your pronunciation of hej was spot on. Watch the word order: the verb comes right after jag.",
            "strengths": ["Confident greetings", "Good pronunciation of å"], "focus_next": ["Verb-second word order", "Asking questions back"],
            "errors": [{"pattern": "Verb placement after the subject", "category": "word order", "wrong": "Jag Sam heter", "right": "Jag heter Sam", "explanation": "The verb comes directly after jag."}],
            "memories": [{"content": "Is learning Swedish because they plan to move to Stockholm.", "category": "goal"}],
            "can_do": [{"goal": "Greet people and say goodbye in informal and slightly more formal situations", "score": 0.8},
                       {"goal": "Say your name and ask for someone else's name", "score": 0.7}],
            "unit_mastery": 0.62, "ready_to_advance": False, "cefr_estimate": "A1", "recommended_unit_id": "",
            "exam_score": 0, "exam_max": 0, "exam_breakdown": "",
        }
    if "lemma" in props:
        return {"lemma": "kanelbulle", "translation": "cinnamon bun", "pos": "noun", "gender": "en",
                "forms": "en kanelbulle – kanelbullen – kanelbullar – kanelbullarna", "example": "Jag tar en kanelbulle.",
                "example_translation": "I'll have a cinnamon bun.", "notes": "4 October is kanelbullens dag!"}
    return {}


@ollama.post("/api/chat")
async def chat(req: Request):
    body = await req.json()
    if body.get("format") is not None:
        return {"message": {"role": "assistant", "content": json.dumps(fake_json(body["format"]), ensure_ascii=False)}, "done": True}
    if not body.get("stream", True):
        return {"message": {"role": "assistant", "content": "Hello! I'd like a coffee, please."}, "done": True}
    reply = REPLIES[state["turn"] % len(REPLIES)]
    state["turn"] += 1

    async def gen():
        words = reply.split(" ")
        for i, w in enumerate(words):
            tok = w + (" " if i < len(words) - 1 else "")
            yield json.dumps({"message": {"role": "assistant", "content": tok}, "done": False}) + "\n"
            await asyncio.sleep(0.02)
        yield json.dumps({"message": {"role": "assistant", "content": ""}, "done": True}) + "\n"
    return StreamingResponse(gen(), media_type="application/x-ndjson")


anki = FastAPI()
astate = {"models": [], "notes": {}, "next": 1000, "media": {}}


@anki.post("/")
async def ankiconnect(req: Request):
    b = await req.json()
    a, p = b["action"], b.get("params", {})
    res = None
    if a == "version":
        res = 6
    elif a == "modelNames":
        res = astate["models"]
    elif a == "createModel":
        astate["models"].append(p["modelName"]); res = {}
    elif a == "modelFieldNames":
        res = ["Word", "Translation", "Forms", "Gender", "POS", "Example", "ExampleTranslation", "WordAudio", "ExampleAudio", "Notes", "Language", "Reverse", "ParleraID"]
    elif a in ("createDeck",):
        res = 1
    elif a == "deckNames":
        res = ["Default", "Parlera::Swedish"]
    elif a == "storeMediaFile":
        astate["media"][p["filename"]] = len(p["data"]); res = p["filename"]
    elif a == "addNote":
        word = p["note"]["fields"]["Word"]
        if any(n["Word"] == word for n in astate["notes"].values()):
            return JSONResponse({"result": None, "error": "cannot create note because it is a duplicate"})
        nid = astate["next"]; astate["next"] += 1
        astate["notes"][nid] = p["note"]["fields"]; res = nid
    elif a == "deleteNotes":
        for n in p["notes"]:
            astate["notes"].pop(n, None)
    elif a == "findNotes":
        res = list(astate["notes"])[:1]
    elif a == "notesInfo":
        res = [{"noteId": n, "cards": [n * 10, n * 10 + 1]} for n in p["notes"] if n in astate["notes"]]
    elif a == "cardsInfo":
        res = [{"cardId": c, "interval": 25 if c % 20 == 0 else 2, "lapses": 0 if c % 20 == 0 else 3, "reps": 5} for c in p["cards"]]
    return {"result": res, "error": None}


def run(app, port):
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    o_port = int(sys.argv[1]) if len(sys.argv) > 1 else 11434
    a_port = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
    threading.Thread(target=run, args=(anki, a_port), daemon=True).start()
    run(ollama, o_port)
