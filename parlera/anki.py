"""Anki integration: AnkiConnect (live push + review-data sync) and .apkg export via genanki."""
from __future__ import annotations

import base64
import hashlib
import html
from pathlib import Path
from typing import Any

import httpx

MODEL_NAME = "Parlera Vocab"
FIELDS = ["Word", "Translation", "Forms", "Gender", "POS", "Example", "ExampleTranslation",
          "WordAudio", "ExampleAudio", "Notes", "Language", "Reverse", "ParleraID"]

CSS = """
.card { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 22px;
        text-align: center; color: #1d1d1f; background: #fbfaf7; line-height: 1.45; }
.nightMode.card, .night_mode .card { color: #f2f2f2; background: #1e1e20; }
.lang { font-size: 12px; letter-spacing: .12em; text-transform: uppercase; opacity: .55; margin-bottom: 18px; }
.word { font-size: 40px; font-weight: 650; margin: 8px 0; }
.g-en, .g-m { color: #2f6fdf; } .g-ett { color: #1f9d55; } .g-f { color: #d1435b; }
.nightMode .g-en, .nightMode .g-m { color: #7aa7ff; } .nightMode .g-ett { color: #5fd08f; } .nightMode .g-f { color: #ff7d93; }
.translation { font-size: 28px; font-weight: 500; }
.forms { font-size: 18px; opacity: .8; margin-top: 10px; }
.pos { font-size: 14px; font-style: italic; opacity: .6; margin-top: 4px; }
.example { font-size: 20px; margin-top: 22px; padding: 12px 16px; border-radius: 12px; background: rgba(127,127,127,.09); display: inline-block; }
.example-tr { font-size: 16px; opacity: .65; margin-top: 6px; }
.notes { font-size: 15px; opacity: .7; margin-top: 16px; }
hr#answer { border: 0; border-top: 1px solid rgba(127,127,127,.25); margin: 22px 0; }
"""

BACK_DETAILS = """
{{#Forms}}<div class="forms">{{Forms}}</div>{{/Forms}}
{{#POS}}<div class="pos">{{POS}}</div>{{/POS}}
{{#Example}}<div class="example">{{Example}} {{ExampleAudio}}</div>
<div class="example-tr">{{ExampleTranslation}}</div>{{/Example}}
{{#Notes}}<div class="notes">{{Notes}}</div>{{/Notes}}
"""

TEMPLATES = [
    {
        "Name": "Recognition",
        "Front": '<div class="lang">{{Language}}</div><div class="word g-{{Gender}}">{{Word}}</div>{{WordAudio}}',
        "Back": '{{FrontSide}}<hr id="answer"><div class="translation">{{Translation}}</div>' + BACK_DETAILS,
    },
    {
        "Name": "Production",
        "Front": '{{#Reverse}}<div class="lang">→ {{Language}}</div><div class="translation">{{Translation}}</div>'
                 '{{#POS}}<div class="pos">{{POS}}</div>{{/POS}}{{/Reverse}}',
        "Back": '{{FrontSide}}<hr id="answer"><div class="word g-{{Gender}}">{{Word}}</div>{{WordAudio}}' + BACK_DETAILS,
    },
]

LANG_NAMES = {"fr": "French", "sv": "Swedish", "en": "English"}


class AnkiError(RuntimeError):
    pass


def strip_html(value: str) -> str:
    """Anki field HTML → plain text (drops [sound:…] tags, <br>, entities)."""
    import re
    v = re.sub(r"\[sound:[^\]]*\]", " ", value or "")
    v = re.sub(r"<br\s*/?>|</div>|</p>", " ", v, flags=re.I)
    v = re.sub(r"<[^>]+>", "", v)
    v = html.unescape(v).replace("\xa0", " ")
    return re.sub(r"\s+", " ", v).strip()


def display_word(v: dict) -> str:
    """Word with article: 'en bil', 'ett hus', 'la maison', "l'école"."""
    lemma = (v.get("lemma") or "").strip()
    g = (v.get("gender") or "").strip().lower()
    pos = (v.get("pos") or "").lower()
    if not lemma or (pos and "noun" not in pos):
        return lemma
    lang = v.get("language")
    if lang == "sv" and g in ("en", "ett") and not lemma.lower().startswith(("en ", "ett ")):
        return f"{g} {lemma}"
    if lang == "fr" and g in ("m", "f") and not lemma.lower().startswith(("le ", "la ", "l'", "les ")):
        if lemma[0].lower() in "aeiouyhéèêàâîôû":
            return f"l'{lemma}"
        return ("le " if g == "m" else "la ") + lemma
    return lemma


def deck_name(settings: dict, language: str, unit: dict | None) -> str:
    """The deck chosen in Settings for this language (existing or new), optionally with a unit sub-deck."""
    decks = settings["anki"].get("decks") or {}
    name = (decks.get(language) or "").strip()
    if not name:
        root = settings["anki"].get("deck_root") or "Parlera"
        name = f"{root}::{LANG_NAMES.get(language, language)}"
    if settings["anki"].get("deck_per_unit") and unit:
        name += "::" + f"{unit['level']} {unit['title']}".replace("::", " ")
    return name


def note_fields(v: dict, add_reverse: bool, word_audio: str = "", example_audio: str = "") -> dict:
    e = html.escape
    return {
        "Word": e(display_word(v)),
        "Translation": e(v.get("translation") or ""),
        "Forms": e(v.get("forms") or ""),
        "Gender": e((v.get("gender") or "").lower()),
        "POS": e(v.get("pos") or ""),
        "Example": e(v.get("example") or ""),
        "ExampleTranslation": e(v.get("example_translation") or ""),
        "WordAudio": f"[sound:{word_audio}]" if word_audio else "",
        "ExampleAudio": f"[sound:{example_audio}]" if example_audio else "",
        "Notes": e(v.get("notes") or ""),
        "Language": LANG_NAMES.get(v.get("language"), v.get("language") or ""),
        "Reverse": "y" if add_reverse else "",
        "ParleraID": str(v.get("id") or ""),
    }


def note_tags(v: dict) -> list[str]:
    tags = ["parlera", f"parlera::{v.get('language')}"]
    if v.get("unit_id"):
        tags.append(f"parlera::{v['unit_id']}")
    return tags


class AnkiConnect:
    def __init__(self, url: str):
        self.url = url

    async def invoke(self, action: str, **params: Any) -> Any:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(self.url, json={"action": action, "version": 6, "params": params})
        except httpx.HTTPError as e:
            raise AnkiError("Cannot reach AnkiConnect. Is Anki open with the AnkiConnect add-on installed?") from e
        data = r.json()
        if data.get("error"):
            raise AnkiError(str(data["error"]))
        return data.get("result")

    async def version(self) -> int | None:
        try:
            async with httpx.AsyncClient(timeout=2.5) as client:
                r = await client.post(self.url, json={"action": "version", "version": 6})
            return r.json().get("result")
        except (httpx.HTTPError, ValueError):
            return None

    async def ensure_model(self) -> None:
        names = await self.invoke("modelNames")
        if MODEL_NAME in names:
            existing = await self.invoke("modelFieldNames", modelName=MODEL_NAME)
            for f in FIELDS:
                if f not in existing:
                    await self.invoke("modelFieldAdd", modelName=MODEL_NAME, fieldName=f, index=len(existing))
                    existing.append(f)
            return
        await self.invoke("createModel", modelName=MODEL_NAME, inOrderFields=FIELDS, css=CSS,
                          isCloze=False, cardTemplates=TEMPLATES)

    async def store_media(self, filename: str, data: bytes) -> str:
        return await self.invoke("storeMediaFile", filename=filename, data=base64.b64encode(data).decode())

    async def add_note(self, deck: str, fields: dict, tags: list[str]) -> int:
        await self.invoke("createDeck", deck=deck)
        try:
            return await self.invoke("addNote", note={
                "deckName": deck, "modelName": MODEL_NAME, "fields": fields, "tags": tags,
                "options": {"allowDuplicate": False, "duplicateScope": "deck"}})
        except AnkiError as e:
            if "duplicate" in str(e).lower():
                ids = await self.invoke("findNotes", query=f'"deck:{deck}" "Word:{fields["Word"]}"')
                if ids:
                    return ids[0]
            raise

    async def deck_notes(self, deck: str, limit: int | None = None) -> list[dict]:
        """Notes in a deck (incl. sub-decks): [{noteId, modelName, fields: {name: plain text}, order: [names]}]."""
        ids = await self.invoke("findNotes", query=f'"deck:{deck}"')
        if limit:
            ids = ids[:limit]
        out = []
        for i in range(0, len(ids), 200):
            for n in await self.invoke("notesInfo", notes=ids[i:i + 200]):
                if not n or not n.get("noteId"):
                    continue
                fields = n.get("fields") or {}
                order = sorted(fields, key=lambda k: fields[k].get("order", 0))
                out.append({"noteId": n["noteId"], "modelName": n.get("modelName", ""),
                            "fields": {k: strip_html(fields[k].get("value", "")) for k in order}, "order": order})
        return out

    async def delete_notes(self, note_ids: list[int]) -> None:
        if note_ids:
            await self.invoke("deleteNotes", notes=note_ids)

    async def deck_names(self) -> list[str]:
        return sorted(await self.invoke("deckNames"))

    async def review_stats(self, note_ids: list[int]) -> dict[int, dict]:
        """note_id -> {interval, lapses, reps} (max interval / sum lapses over the note's cards)."""
        if not note_ids:
            return {}
        notes = await self.invoke("notesInfo", notes=note_ids)
        card_to_note: dict[int, int] = {}
        for n in notes:
            if n and n.get("noteId"):
                for c in n.get("cards", []):
                    card_to_note[c] = n["noteId"]
        if not card_to_note:
            return {}
        cards = await self.invoke("cardsInfo", cards=list(card_to_note))
        out: dict[int, dict] = {}
        for c in cards:
            nid = card_to_note.get(c.get("cardId"))
            if nid is None:
                continue
            s = out.setdefault(nid, {"interval": 0, "lapses": 0, "reps": 0})
            s["interval"] = max(s["interval"], int(c.get("interval") or 0))
            s["lapses"] += int(c.get("lapses") or 0)
            s["reps"] += int(c.get("reps") or 0)
        return out


def build_apkg(vocab: list[dict], settings: dict, media: dict[str, bytes], out_path: Path,
               units: dict[str, dict] | None = None) -> Path:
    import genanki

    model = genanki.Model(
        1607392319, MODEL_NAME,
        fields=[{"name": f} for f in FIELDS],
        templates=[{"name": t["Name"], "qfmt": t["Front"], "afmt": t["Back"]} for t in TEMPLATES],
        css=CSS,
    )
    decks: dict[str, genanki.Deck] = {}
    add_reverse = settings["anki"].get("add_reverse", True)
    for v in vocab:
        unit = (units or {}).get(v.get("unit_id") or "")
        name = deck_name(settings, v["language"], unit)
        if name not in decks:
            decks[name] = genanki.Deck(int(hashlib.md5(name.encode()).hexdigest()[:8], 16), name)
        wa = f"parlera_{v['language']}_{v['id']}_w.wav"
        ea = f"parlera_{v['language']}_{v['id']}_e.wav"
        fields = note_fields(v, add_reverse, wa if wa in media else "", ea if ea in media else "")
        decks[name].add_note(genanki.Note(model=model, fields=[fields[f] for f in FIELDS],
                                          tags=[t.replace("::", "_") for t in note_tags(v)],
                                          guid=genanki.guid_for("parlera", v["language"], v["lemma_norm"])))
    tmp_dir = out_path.parent / "apkg_media"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for name, data in media.items():
        p = tmp_dir / name
        p.write_bytes(data)
        files.append(str(p))
    pkg = genanki.Package(list(decks.values()))
    pkg.media_files = files
    pkg.write_to_file(str(out_path))
    return out_path
