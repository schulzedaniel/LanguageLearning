"""End-to-end tests against fake Ollama/AnkiConnect servers (see tools/mock_services.py)."""
from __future__ import annotations

import io
import socket
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import mock_services  # noqa: E402
from parlera.anki import display_word  # noqa: E402
from parlera.core import clean_lemma, normalize_gender  # noqa: E402
from parlera.llm import ThinkFilter, parse_json_loose  # noqa: E402
from parlera.stt import clean_transcript  # noqa: E402
from parlera.textproc import SentenceStream, segment_languages, strip_for_speech  # noqa: E402


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _serve(app, port):
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.1).close()
            return server
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("mock server did not start")


@pytest.fixture(scope="module")
def mocks():
    o, a = _free_port(), _free_port()
    _serve(mock_services.ollama, o)
    _serve(mock_services.anki, a)
    return {"ollama": f"http://127.0.0.1:{o}", "anki": f"http://127.0.0.1:{a}"}


@pytest.fixture()
def client(tmp_path, mocks, monkeypatch):
    monkeypatch.setenv("PARLERA_DATA", str(tmp_path / "data"))
    from parlera.main import create_app
    app = create_app()
    app.state.core.settings.update({"llm": {"base_url": mocks["ollama"]}, "anki": {"url": mocks["anki"]},
                                    "tts": {"engine": "browser"}, "stt": {"backend": "off"}})
    with TestClient(app) as c:
        c.core = app.state.core
        yield c


# ---------------------------------------------------------------------------
# pure functions
# ---------------------------------------------------------------------------
def test_sentence_stream_keeps_bold_together():
    s = SentenceStream()
    text = "Great! Try: **Hej, jag heter Sam.** Now you.\n✏️ We say **jag heter**. Okay?"
    out = []
    for i in range(0, len(text), 3):
        out += s.feed(text[i:i + 3])
    out += s.flush()
    texts = [t for t, _ in out]
    assert any(t.endswith("Try: **Hej, jag heter Sam.**") for t in texts)  # bold span never split
    corrections = [t for t, c in out if c]
    assert corrections and corrections[0].startswith("✏️")


def test_segment_languages_routes_voices():
    segs = segment_languages("Hello is **hej**. Try saying **Jag heter Sam**.", "sv")
    assert [s["lang"] for s in segs] == ["en", "sv", "en", "sv"]
    fr = segment_languages("Très bien ! Comment tu t'appelles ?", "fr")
    assert fr[0]["lang"] == "fr"


def test_strip_for_speech():
    assert strip_for_speech("✏️ *Almost* — say **le livre**") == "Almost, say le livre"


def test_think_filter_and_json():
    f = ThinkFilter()
    out = "".join(f.feed(x) for x in ["<thi", "nk>secret</th", "ink>Hej", " då"]) + f.flush()
    assert out == "Hej då"
    assert parse_json_loose('Sure!\n```json\n{"a": 1}\n```') == {"a": 1}


def test_lemma_helpers():
    assert clean_lemma("en bil", "sv") == "bil"
    assert clean_lemma("att läsa", "sv") == "läsa"
    assert clean_lemma("l'école", "fr") == "école"
    assert normalize_gender("neuter", "sv") == "ett"
    assert normalize_gender("feminine", "fr") == "f"
    assert display_word({"lemma": "bil", "gender": "en", "pos": "noun", "language": "sv"}) == "en bil"
    assert display_word({"lemma": "école", "gender": "f", "pos": "noun", "language": "fr"}) == "l'école"
    assert display_word({"lemma": "maison", "gender": "f", "pos": "noun", "language": "fr"}) == "la maison"


def test_whisper_hallucination_filter():
    assert clean_transcript("Tack för att du tittade!") == ""
    assert clean_transcript("Jag heter Sam") == "Jag heter Sam"


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def test_status_dashboard_curriculum(client):
    st = client.get("/api/status").json()
    assert st["ollama"]["ok"] and st["ollama"]["model_installed"]
    assert st["anki"]["ok"]
    for lang in ("sv", "fr"):
        d = client.get(f"/api/dashboard/{lang}").json()
        assert d["unit"]["id"] == f"{lang}-a1-01"
        cur = client.get(f"/api/curriculum/{lang}").json()
        assert len(cur["curriculum"]["units"]) == 31
    assert client.get("/").status_code == 200


def test_prompts_edit_preview_reset(client):
    names = [p["name"] for p in client.get("/api/prompts").json()]
    assert "tutor_base" in names and "mode_exam" in names
    r = client.put("/api/prompts/mode_free", json={"text": "{% if %}broken"})
    assert r.status_code == 400
    client.put("/api/prompts/mode_free", json={"text": "FREE TALK about {{ language_name }}"})
    assert client.get("/api/prompts/mode_free").json()["modified"]
    pv = client.post("/api/prompts-preview", json={"language": "sv", "mode": "free"}).json()
    assert "FREE TALK about Swedish" in pv["system"]
    client.post("/api/prompts/mode_free/reset")
    assert not client.get("/api/prompts/mode_free").json()["modified"]


def test_curriculum_edit_validation(client):
    bad = client.put("/api/curriculum/sv/raw", json={"text": "language: sv\nlevels: []"})
    assert bad.status_code == 400
    raw = client.get("/api/curriculum/sv/raw").text
    ok = client.post("/api/curriculum/sv/validate", json={"text": raw}).json()
    assert ok["ok"] and ok["units"] == 31


def test_full_session_flow(client):
    s = client.post("/api/sessions", json={"language": "sv", "mode": "lesson"}).json()
    sid = s["id"]
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "start"})
        events = _collect_turn(ws)
        assert any(e["type"] == "speak" for e in events), "browser TTS segments expected"
        speak = next(e for e in events if e["type"] == "speak")
        assert {"en", "sv"} & {seg["lang"] for seg in speak["segments"]}
        ws.send_json({"type": "user_text", "text": "Hej! Jag Sam heter."})
        events = _collect_turn(ws)
        end = next(e for e in events if e["type"] == "assistant_end")
        assert "✏️" in end["content"]

    view = client.get(f"/api/sessions/{sid}").json()
    assert [m["role"] for m in view["messages"]] == ["assistant", "user", "assistant"]

    # analysis
    r = client.post(f"/api/sessions/{sid}/end")
    assert r.status_code == 200, r.text
    a = r.json()["analysis"]
    assert a["title"] == "First greetings in Swedish"
    lemmas = [v["lemma"] for v in a["vocab_candidates"]]
    assert "heta" in lemmas and "lärare" in lemmas       # article stripped
    assert "xyzzyq" not in lemmas                         # rare/nonsense word filtered by frequency
    assert client.get("/api/errors?language=sv").json()[0]["pattern"] == "Verb placement after the subject"
    assert any("Stockholm" in m["content"] for m in client.get("/api/memories").json())
    prog = client.get("/api/curriculum/sv").json()["progress"]["sv-a1-01"]
    assert prog["sessions"] == 1 and abs(prog["mastery"] - 0.62) < 1e-6

    # second analysis of same session merges recurring errors (count 2)
    client.post(f"/api/sessions/{sid}/end")
    assert client.get("/api/errors?language=sv").json()[0]["count"] == 2

    # new words were pushed to Anki automatically (auto_add is on by default), then sync review stats back
    ids = [v["id"] for v in a["vocab_candidates"]]
    assert sorted(a["anki_auto"]["added"]) == sorted(ids) and not a["anki_auto"]["failed"]
    assert mock_services.astate["notes"], "notes should exist in (fake) Anki"
    sync = client.post("/api/anki/sync", json={"language": "sv"}).json()
    assert sync["updated"] == len(ids)
    weak = client.get("/api/dashboard/sv").json()["weak_vocab"]
    assert weak, "words with lapses should be reported as weak"

    # weak words and recurring errors now flow into the next session's system prompt
    pv = client.post("/api/prompts-preview", json={"language": "sv", "mode": "review"}).json()["system"]
    assert "Verb placement after the subject" in pv
    assert "First greetings in Swedish" in pv

    # export
    apkg = client.post("/api/vocab/export.apkg", json={"ids": ids})
    assert apkg.status_code == 200 and apkg.content[:2] == b"PK"
    md = client.get(f"/api/sessions/{sid}/export.md")
    assert "Transcript" in md.text

    # removing a card from Anki
    r = client.post("/api/vocab/bulk", json={"ids": ids[:1], "action": "unanki"}).json()
    assert r["removed"] == 1
    assert client.get("/api/vocab?language=sv&status=ignored").json()[0]["id"] == ids[0]


def test_auto_add_queues_when_anki_closed_and_custom_deck(client):
    from parlera.anki import deck_name
    st = client.core.settings.update({"anki": {"decks": {"sv": "Svenska::Ord"}, "deck_per_unit": True}})
    assert deck_name(st, "sv", {"level": "A1", "title": "Hej!"}) == "Svenska::Ord::A1 Hej!"
    client.core.settings.update({"anki": {"url": "http://127.0.0.1:9"}})       # Anki "closed"
    s = client.post("/api/sessions", json={"language": "sv", "mode": "lesson"}).json()
    client.core.db.add_message(s["id"], "assistant", "Hej! **Hej** means hello.")
    client.core.db.add_message(s["id"], "user", "Hej")
    a = client.post(f"/api/sessions/{s['id']}/end").json()["analysis"]
    assert a["anki_auto"] == {"queued": len(a["vocab_candidates"])}
    assert client.post("/api/anki/push-pending", json={}).json()["offline"]


def test_resume_and_interrupt(client):
    s = client.post("/api/sessions", json={"language": "fr", "mode": "conversation"}).json()
    with client.websocket_connect(f"/ws/sessions/{s['id']}") as ws:
        ws.receive_json()
        ws.send_json({"type": "start"})
        ws.receive_json()  # assistant_start
        ws.send_json({"type": "interrupt"})
        time.sleep(0.3)
    msgs = client.get(f"/api/sessions/{s['id']}").json()["messages"]
    assert len(msgs) <= 1
    if msgs:
        assert msgs[0]["meta"].get("interrupted")


def test_vocab_manual_and_autofill(client):
    fill = client.post("/api/vocab/autofill", json={"language": "sv", "word": "kanelbulle"}).json()
    assert fill["gender"] == "en"
    row = client.post("/api/vocab", json={"language": "sv", **fill}).json()
    assert row["display"] == "en kanelbulle"
    dup = client.post("/api/vocab", json={"language": "sv", "lemma": "en kanelbulle"})
    assert dup.status_code == 400
    csv = client.get("/api/vocab/export.csv?language=sv").text
    assert "en kanelbulle" in csv


def test_memories_and_learner(client):
    m = client.post("/api/memories", json={"content": "Loves hiking", "category": "personal"}).json()
    client.patch(f"/api/memories/{m['id']}", json={"active": 0})
    pv = client.post("/api/prompts-preview", json={"language": "sv", "mode": "lesson"}).json()["system"]
    assert "Loves hiking" not in pv
    client.patch(f"/api/memories/{m['id']}", json={"active": 1})
    client.put("/api/learner/sv", json={"notes": "Prefers British English explanations."})
    pv = client.post("/api/prompts-preview", json={"language": "sv", "mode": "lesson"}).json()["system"]
    assert "Loves hiking" in pv and "British English" in pv
    client.put("/api/learner/sv", json={"current_unit_id": "sv-a1-05", "complete_previous": True})
    prog = client.get("/api/curriculum/sv").json()["progress"]
    assert prog["sv-a1-01"]["status"] == "completed"
    assert client.get("/api/dashboard/sv").json()["unit"]["id"] == "sv-a1-05"


def test_backup_restore(client):
    client.post("/api/memories", json={"content": "Before backup"})
    zbytes = client.get("/api/backup").content
    names = zipfile.ZipFile(io.BytesIO(zbytes)).namelist()
    assert "parlera.db" in names and "prompts/tutor_base.md" in names and "curricula/sv.yaml" in names
    client.post("/api/memories", json={"content": "After backup"})
    r = client.post("/api/restore", files={"file": ("b.zip", zbytes, "application/zip")})
    assert r.status_code == 200
    contents = [m["content"] for m in client.get("/api/memories").json()]
    assert "Before backup" in contents and "After backup" not in contents


def _collect_turn(ws, limit=400):
    events = []
    for _ in range(limit):
        e = ws.receive_json()
        events.append(e)
        if e["type"] in ("audio_end", "error"):
            break
    return events


def _tone_wav(seconds=1.0, rate=16000, freq=220.0):
    import numpy as np
    from parlera.audio import float32_to_wav
    t = np.arange(int(seconds * rate)) / rate
    return float32_to_wav((0.2 * np.sin(2 * np.pi * freq * t)).astype("float32"), rate)


def test_voice_pipeline_with_fake_engines(client):
    """Mic audio -> STT -> LLM -> per-sentence server TTS, with the speech engines stubbed."""
    import base64
    core = client.core
    heard = {}

    def fake_transcribe(wav, lang, prompt):
        heard.update(lang=lang, prompt=prompt, size=len(wav))
        return {"text": "Hej! Jag heter Sam.", "language": lang}

    core.stt.backend = lambda: "fake"
    core.stt.preload = lambda *a: None
    core.stt.transcribe = fake_transcribe
    core.tts.engine = lambda: "macos"
    synth_calls = []

    def fake_synth(text, lang, rate=1.0):
        synth_calls.append((lang, text, rate))
        return _tone_wav(0.2, 22050)
    core.tts.synth = fake_synth

    s = client.post("/api/sessions", json={"language": "sv", "mode": "lesson"}).json()
    with client.websocket_connect(f"/ws/sessions/{s['id']}") as ws:
        ready = ws.receive_json()
        assert ready["tts"] == "server"
        ws.send_json({"type": "user_audio", "data": base64.b64encode(_tone_wav()).decode(), "lang": "target"})
        events = _collect_turn(ws)
    types = [e["type"] for e in events]
    assert types[0] == "transcribing" and events[1]["text"] == "Hej! Jag heter Sam."
    assert "audio" in types
    assert heard["lang"] == "sv" and "hej" in heard["prompt"]          # unit vocab biases Whisper
    langs = {c[0] for c in synth_calls}
    assert langs == {"sv", "en"}                                        # mixed-language reply, two voices
    assert all(rate < 1.0 for lang, _, rate in synth_calls if lang == "sv")  # slower Swedish at A1
    # concatenated WAV is valid
    wav = base64.b64decode(next(e for e in events if e["type"] == "audio")["data"])
    assert wav[:4] == b"RIFF"


def test_pronunciation_hints_reach_the_tutor(client):
    import base64
    core = client.core
    core.stt.backend = lambda: "fake"
    core.stt.preload = lambda *a: None
    seen = {}
    core.stt.transcribe = lambda wav, lang, prompt: (seen.update(prompt=prompt) or
                                                     {"text": "Ja heter Sam", "language": "sv",
                                                      "words": [{"word": "Ja", "p": 0.31}, {"word": "heter", "p": 0.95},
                                                                {"word": "Sam", "p": 0.97}]})
    s = client.post("/api/sessions", json={"language": "sv", "mode": "pronunciation"}).json()
    core.db.add_message(s["id"], "assistant", "Repeat after me: **Jag heter Sam.**")
    with client.websocket_connect(f"/ws/sessions/{s['id']}") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_audio", "data": base64.b64encode(_tone_wav()).decode(), "lang": "target"})
        events = _collect_turn(ws)
    tr = next(e for e in events if e["type"] == "transcript")
    assert tr["pron"]["rep"]["diffs"][0] == {"expected": "jag", "heard": "ja"}
    assert tr["pron"]["low"][0]["word"] == "Ja"
    assert seen["prompt"] is None                       # no vocabulary bias in pronunciation mode
    session = core.db.session(s["id"])
    msgs = core.chat_messages(session, "SYSTEM")
    assert "Pronunciation hint" in msgs[-2]["content"]  # the user turn sent to the LLM carries the hint
    shown = client.get(f"/api/sessions/{s['id']}").json()["messages"]
    assert "Pronunciation hint" not in shown[1]["content"]   # but the transcript itself stays clean


def test_speak_endpoint_and_concat(client):
    client.core.tts.engine = lambda: "macos"
    client.core.tts.synth = lambda text, lang, rate=1.0: _tone_wav(0.3, 22050 if lang == "sv" else 16000)
    r = client.post("/api/speak", json={"text": "Hello is **hej**.", "language": "sv"})
    assert r.status_code == 200 and r.content[:4] == b"RIFF"
    import io as _io
    import wave
    with wave.open(_io.BytesIO(r.content)) as wf:
        assert wf.getframerate() == 16000          # resampled to the first segment's rate
        assert wf.getnframes() > 0.6 * 16000       # both segments + gap
