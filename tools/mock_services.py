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
state = {"turn": 0, "running": {}, "unloads": []}   # running: model -> size in bytes
SIZES = {"gemma4:26b": 17e9, "muse-glimmer:30b-mlx": 21e9, "tiny:1b": 1e9}


def _touch(model: str) -> None:
    state["running"][model] = SIZES.get(model, 10e9)


@ollama.get("/api/ps")
async def ps():
    return {"models": [{"name": m, "size": s} for m, s in state["running"].items()]}


@ollama.get("/api/tags")
async def tags():
    return {"models": [{"name": "gemma4:26b"}, {"name": "gemma4:26b-mlx"}, {"name": "qwen3:30b-a3b"}]}


@ollama.post("/api/generate")
async def generate(req: Request):
    body = await req.json()
    if body.get("keep_alive") == 0:
        state["running"].pop(body.get("model"), None)
        state["unloads"].append(body.get("model"))
    elif body.get("model"):
        _touch(body["model"])
    return {"done": True}


def fake_json(schema: dict):
    props = (schema or {}).get("properties", {})
    item_props = props.get("items", {}).get("items", {}).get("properties", {})
    if "days" in item_props:  # teacher note
        return {"items": [{"content": "Speak more slowly.", "kind": "behaviour", "days": 0, "all_languages": True},
                          {"content": "This week, practise vocabulary for a job interview.", "kind": "focus", "days": 7, "all_languages": False}]}
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
    if "categories" in props:
        return {"title": "Word order & verbs", "overview": "Most mistakes come from the verb-second rule.",
                "categories": [{"name": "Verb second (V2)", "rule": "In main clauses the verb is always in position 2: **I dag dricker jag kaffe**.",
                                "why": "English keeps subject-verb order after adverbs.", "examples": [{"wrong": "I dag jag dricker kaffe", "right": "I dag dricker jag kaffe"}],
                                "tip": "Count to two: the verb is always second.", "patterns": ["Verb placement after the subject"]}],
                "plan": "Explain V2, then drill with time expressions."}
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
    _touch(body.get("model", ""))
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
# a pre-existing user deck (e.g. English cards made elsewhere); ids are creation times in ms
_PRE = [("ubiquitous", "present everywhere", "Smartphones are ubiquitous."),
        ("to mitigate", "to make less severe", "Measures to mitigate climate change."),
        ("<b>nuance</b>", "a subtle difference", "She grasped every nuance.")]
for i, (front, back, ex) in enumerate(_PRE):
    astate["notes"][1_760_000_000_000 + i] = {"deck": "English Vocab", "model": "Basic",
                                              "fields": {"Front": front, "Back": back, "Example": ex}}


def _deck_of(query: str) -> str | None:
    import re
    m = re.search(r'"?deck:([^"]+)"?', query)
    return m.group(1).strip() if m else None


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
        res = sorted({"Default", *(n["deck"] for n in astate["notes"].values())})
    elif a == "storeMediaFile":
        astate["media"][p["filename"]] = len(p["data"]); res = p["filename"]
    elif a == "addNote":
        note = p["note"]
        word = note["fields"]["Word"]
        if any(n["fields"].get("Word") == word and n["deck"] == note["deckName"] for n in astate["notes"].values()):
            return JSONResponse({"result": None, "error": "cannot create note because it is a duplicate"})
        nid = astate["next"]; astate["next"] += 1
        astate["notes"][nid] = {"deck": note["deckName"], "model": note["modelName"], "fields": note["fields"]}
        res = nid
    elif a == "deleteNotes":
        for n in p["notes"]:
            astate["notes"].pop(n, None)
    elif a == "findNotes":
        deck = _deck_of(p.get("query", ""))
        res = [nid for nid, n in astate["notes"].items() if deck is None or n["deck"] == deck or n["deck"].startswith(deck + "::")]
    elif a == "notesInfo":
        res = [{"noteId": n, "modelName": astate["notes"][n]["model"],
                "fields": {k: {"value": v, "order": i} for i, (k, v) in enumerate(astate["notes"][n]["fields"].items())},
                "cards": [n * 10, n * 10 + 1]} for n in p["notes"] if n in astate["notes"]]
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
