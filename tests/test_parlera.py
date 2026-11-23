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

    def fake_synth(text, lang, rate=1.0, speaker=None):
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
    client.core.tts.synth = lambda text, lang, rate=1.0, speaker=None: _tone_wav(0.3, 22050 if lang == "sv" else 16000)
    r = client.post("/api/speak", json={"text": "Hello is **hej**.", "language": "sv"})
    assert r.status_code == 200 and r.content[:4] == b"RIFF"
    import io as _io
    import wave
    with wave.open(_io.BytesIO(r.content)) as wf:
        assert wf.getframerate() == 16000          # resampled to the first segment's rate
        assert wf.getnframes() > 0.6 * 16000       # both segments + gap


# ---------------------------------------------------------------------------
# English course, reinforcement, Anki import, default upgrades
# ---------------------------------------------------------------------------
def test_english_course_is_monolingual(client):
    d = client.get("/api/dashboard/en").json()
    assert d["unit"]["id"] == "en-c1-01"              # start_unit from en.yaml
    assert d["immersion"] == 100
    cur = client.get("/api/curriculum/en").json()["curriculum"]
    assert [lv["code"] for lv in cur["levels"]] == ["B2", "C1", "C2"]
    pv = client.post("/api/prompts-preview", json={"language": "en", "mode": "lesson"}).json()["system"]
    assert "Oliver" in pv and "IELTS" in pv
    assert "Mixing languages" not in pv and "✏️ Upgrade" in pv
    exam = client.post("/api/prompts-preview", json={"language": "en", "mode": "exam"}).json()["system"]
    assert "TOEFL iBT" in exam and "Duolingo English Test" in exam
    # all English goes to one voice
    assert segment_languages("Great answer! Try **mitigate the risk** next time.", "en") == [
        {"lang": "en", "text": "Great answer! Try mitigate the risk next time."}]
    assert clean_lemma("to mitigate", "en") == "mitigate"
    assert normalize_gender("m", "en") == ""
    # the Swedish course still mixes languages
    sv = client.post("/api/prompts-preview", json={"language": "sv", "mode": "lesson"}).json()["system"]
    assert "Mixing languages" in sv and "Oliver" not in sv


def test_reinforcement_prefers_recent_young_cards(client):
    from datetime import datetime, timedelta
    core = client.core
    ts = lambda days: (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    rows = [  # (lemma, age_days, anki_interval, reps, lapses)
        ("recent_young", 5, 3, 4, 0), ("recent_unsynced", 8, None, None, None), ("mature", 10, 60, 9, 0),
        ("ancient", 200, 2, 3, 0), ("struggling", 4, 1, 6, 4), ("brand_new_today", 0, None, None, None)]
    for lemma, age, interval, reps, lapses in rows:
        core.db.insert("vocab", {"language": "fr", "lemma": lemma, "lemma_norm": lemma, "status": "learning",
                                 "anki_note_id": 1 if interval is not None else None, "anki_interval": interval,
                                 "anki_reps": reps, "anki_lapses": lapses, "created_at": ts(age), "updated_at": ts(age)})
    counts = {}
    for seed in range(300):
        for v in core.reinforce_vocab("fr", seed=seed):
            counts[v["lemma"]] = counts.get(v["lemma"], 0) + 1
    assert "ancient" not in counts and "struggling" not in counts     # too old / left to weak_vocab
    core.settings.update({"vocab": {"reinforce_count": 1}})
    single = {}
    for seed in range(600):
        lemma = core.reinforce_vocab("fr", seed=seed)[0]["lemma"]
        single[lemma] = single.get(lemma, 0) + 1
    assert single["recent_young"] > single["mature"] * 3              # young cards far more often
    assert single["recent_young"] > single["brand_new_today"]
    # the same session always gets the same selection (stable prompt for Ollama's cache)
    assert core.reinforce_vocab("fr", seed=42) == core.reinforce_vocab("fr", seed=42)
    ctx = core.build_context("fr", "conversation", session_id=7)
    assert ctx["reinforce_vocab"]
    pv = core.render_system_prompt(ctx)
    assert "Recently learned words" in pv


def test_import_existing_anki_deck(client):
    preview = client.get("/api/anki/deck-preview", params={"deck": "English Vocab"}).json()
    assert preview["count"] == 3 and preview["fields"] == ["Front", "Back", "Example"]
    assert preview["sample"][2]["Front"] == "nuance"                  # HTML stripped
    r = client.post("/api/anki/import", json={"language": "en", "deck": "English Vocab", "word_field": "Front",
                                              "meaning_field": "Back", "example_field": "Example"}).json()
    assert r["added"] == 3 and r["synced"]["linked"] >= 3
    words = {v["lemma"]: v for v in client.get("/api/vocab?language=en").json()}
    assert set(words) == {"ubiquitous", "mitigate", "nuance"}         # "to " stripped
    assert words["mitigate"]["translation"] == "to make less severe"
    assert words["ubiquitous"]["created_at"].startswith("2025-")      # real creation date from the note id
    again = client.post("/api/anki/import", json={"language": "en", "deck": "English Vocab", "word_field": "Front",
                                                  "meaning_field": "Back"}).json()
    assert again["added"] == 0 and again["skipped"] == 3


def test_unedited_default_prompts_are_upgraded(tmp_path):
    import hashlib
    import json as _json
    from parlera.config import DEFAULTS_DIR, Paths, file_hash
    paths = Paths(tmp_path / "d")
    paths.ensure()
    old_default = "An OLD built-in version of the opening prompt."
    (paths.prompts / "opening.md").write_text(old_default)            # pretend: an old, unedited default
    (paths.prompts / "resume.md").write_text("My own edited resume prompt.")
    known = _json.loads((DEFAULTS_DIR / "known_hashes.json").read_text())
    known["prompts/opening.md"].append(file_hash(old_default.encode()))
    import parlera.config as cfg
    orig = cfg._known_default_hashes
    cfg._known_default_hashes = lambda: {k: set(v) for k, v in known.items()}
    try:
        upgraded = paths.ensure()
    finally:
        cfg._known_default_hashes = orig
    assert upgraded == ["prompts/opening.md"]
    assert (paths.prompts / "opening.md").read_text() == (DEFAULTS_DIR / "prompts/opening.md").read_text()
    assert (paths.prompts / "resume.md").read_text() == "My own edited resume prompt."   # user edits kept
    assert (paths.curricula / "en.yaml").exists()                      # new files are installed


def test_known_hashes_cover_git_history():
    """Every committed version of a default file must be listed, or users' copies won't upgrade."""
    import json as _json
    import subprocess
    from parlera.config import DEFAULTS_DIR, file_hash
    try:
        commits = subprocess.run(["git", "log", "--format=%H", "--", "parlera/defaults/prompts", "parlera/defaults/curricula"],
                                 cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    known = _json.loads((DEFAULTS_DIR / "known_hashes.json").read_text())
    for c in commits:
        files = subprocess.run(["git", "ls-tree", "-r", "--name-only", c, "--", "parlera/defaults/prompts",
                                "parlera/defaults/curricula"], cwd=ROOT, capture_output=True, text=True).stdout.split()
        for f in files:
            data = subprocess.run(["git", "show", f"{c}:{f}"], cwd=ROOT, capture_output=True).stdout
            rel = f[len("parlera/defaults/"):]
            current = DEFAULTS_DIR / rel
            if current.exists() and file_hash(current.read_bytes()) == file_hash(data):
                continue  # this is the current default
            assert file_hash(data) in known.get(rel, []), f"{rel}@{c[:7]} missing — run tools/update_default_hashes.py"


# ---------------------------------------------------------------------------
# quitting, voices per language, mistake workshop, DB migration
# ---------------------------------------------------------------------------
def test_heartbeat_bye_and_shutdown(client):
    class FakeServer:
        should_exit = False
    hb = client.post("/api/heartbeat").json()
    assert hb["ok"] and hb["build"] == client.app.state.build
    assert client.app.state.last_seen is not None and client.app.state.bye_at is None
    client.post("/api/bye")                                   # tab closed → quit soon…
    assert client.app.state.bye_at is not None
    client.post("/api/heartbeat")                             # …unless a reload/another tab beats
    assert client.app.state.bye_at is None
    assert client.post("/api/shutdown").json()["ok"] is False   # not started via run.sh
    client.app.state.server = FakeServer()
    assert client.post("/api/shutdown").json()["ok"] is True
    assert client.app.state.server.should_exit is True


def test_versioned_assets_prevent_stale_cache(client):
    """index.html must load the UI from a build-specific URL, so browsers can't mix old cached files."""
    build = client.app.state.build
    html = client.get("/").text
    assert f'/static/v-{build}/js/app.js' in html and f'/static/v-{build}/css/app.css' in html
    assert "__BUILD__" not in html and "no-store" in client.get("/").headers["cache-control"]
    js = client.get(f"/static/v-{build}/js/app.js")
    assert js.status_code == 200 and "immutable" in js.headers["cache-control"]
    assert "javascript" in js.headers["content-type"]
    # relative module imports resolve inside the versioned folder
    assert client.get(f"/static/v-{build}/js/views/dashboard.js").status_code == 200
    # an old build id still works but is never cached for long
    old = client.get("/static/v-0000000000/js/app.js")
    assert old.status_code == 200 and old.headers["cache-control"] == "no-cache"
    assert client.get("/static/js/app.js").headers["cache-control"] == "no-cache"
    assert client.get(f"/static/v-{build}/../main.py").status_code == 404
    assert client.get(f"/static/v-{build}/%2e%2e/main.py").status_code == 404


def test_per_language_voice_engines(client):
    tts = client.core.tts
    tts.available_engines = lambda: {"macos": True, "piper": False, "kokoro": True, "browser": True}
    client.core.settings.update({"tts": {"engine": "macos", "engines": {"en": "kokoro", "fr": "", "sv": ""}}})
    assert tts.engine_for("en") == "kokoro" and tts.engine_for("sv") == "macos"
    assert tts.server_side(("sv", "en"))
    client.core.settings.update({"tts": {"engines": {"fr": "browser"}}})
    assert not tts.server_side(("fr", "en"))
    assert [v["name"] for v in tts.voices("kokoro", "fr")] == ["ff_siwis"]
    assert tts.voices("kokoro", "sv") == []                # Kokoro has no Swedish voice
    # an override for an engine that isn't installed falls back to the default
    tts.available_engines = lambda: {"macos": True, "piper": False, "kokoro": False, "browser": True}
    assert tts.engine_for("en") == "macos"


def test_mistake_workshop_flow(client):
    core = client.core
    s = client.post("/api/sessions", json={"language": "sv", "mode": "lesson"}).json()
    core.db.add_message(s["id"], "assistant", "Hej! **Vad heter du?**")
    core.db.add_message(s["id"], "user", "Jag Sam heter")
    client.post(f"/api/sessions/{s['id']}/end")             # mock analysis records a mistake + event
    events = core.db.all("SELECT * FROM error_events WHERE language='sv'")
    assert events and events[0]["wrong"] == "Jag Sam heter"
    st = client.get("/api/workshops/status/sv").json()
    assert st["available"] and st["new_mistakes"] >= 1
    seen = {}
    orig = core.llm.chat_json

    async def spy(messages, **kw):
        seen.setdefault("think", kw.get("think"))
        seen.setdefault("prompt", messages[0]["content"])
        return await orig(messages, **kw)
    core.llm.chat_json = spy
    w = client.post("/api/workshops", json={"language": "sv"}).json()
    core.llm.chat_json = orig
    assert seen["think"] is True                            # thinking allowed for the summary
    assert "Jag Sam heter" in seen["prompt"]
    view = client.get(f"/api/sessions/{w['id']}").json()
    assert view["mode"] == "workshop" and view["workshop"]["categories"][0]["name"] == "Verb second (V2)"
    pv = core.render_system_prompt(core.build_context("sv", "workshop", session_id=w["id"]))
    assert "mistake workshop" in pv and "Count to two" in pv
    assert client.get("/api/workshops/status/sv").json()["new_mistakes"] == 0   # counter resets
    # workshop analysis can mark patterns as mastered
    core.db.add_message(w["id"], "user", "I dag dricker jag kaffe")
    orig2 = core.llm.chat_json

    async def mastered(messages, schema=None, **kw):
        data = await orig2(messages, schema=schema, **kw)
        if schema and "mastered_patterns" in schema.get("properties", {}):
            data["mastered_patterns"] = ["Verb placement after the subject"]
        return data
    core.llm.chat_json = mastered
    client.post(f"/api/sessions/{w['id']}/end")
    core.llm.chat_json = orig2
    err = client.get("/api/errors?language=sv").json()[0]
    assert err["resolved"] == 1


def test_db_migration_from_v1(tmp_path):
    import sqlite3
    from parlera.db import DB, SCHEMA_V1
    p = tmp_path / "old.db"
    con = sqlite3.connect(p)
    con.executescript(SCHEMA_V1)
    con.execute("PRAGMA user_version=1")
    con.execute("INSERT INTO errors (language, pattern, pattern_norm, example_wrong, example_right, first_seen, last_seen) "
                "VALUES ('fr', 'Gender', 'gender', 'le maison', 'la maison', '2026-01-01T10:00:00', '2026-01-02T10:00:00')")
    con.commit()
    con.close()
    db = DB(p)
    assert db.scalar("PRAGMA user_version") == 3   # V2 (workshops) and V3 (practice) applied
    ev = db.all("SELECT * FROM error_events")
    assert len(ev) == 1 and ev[0]["wrong"] == "le maison"   # backfilled from existing mistakes
    assert db.all("SELECT * FROM errors")[0]["pattern"] == "Gender"


def test_teacher_note_becomes_instructions(client):
    items = client.post("/api/teacher-note/parse", json={"language": "en", "text": "Please speak slower. Job interview Friday!"}).json()["items"]
    assert [i["days"] for i in items] == [None, 7]          # 0 from the model = permanent
    saved = client.post("/api/directives", json={"language": "en", "text": "note", "items": items}).json()
    assert len(saved) == 2
    pv = client.post("/api/prompts-preview", json={"language": "en", "mode": "lesson"}).json()["system"]
    assert "Speak more slowly." in pv and "job interview" in pv
    # "all languages" instruction also reaches the Swedish teacher, the English-only one doesn't
    sv = client.post("/api/prompts-preview", json={"language": "sv", "mode": "lesson"}).json()["system"]
    assert "Speak more slowly." in sv and "job interview" not in sv
    # expired instructions drop out
    rows = client.get("/api/directives?language=en").json()
    temp = next(r for r in rows if r["expires_at"])
    client.patch(f"/api/directives/{temp['id']}", json={"expires_at": "2000-01-01T00:00:00"})
    pv = client.post("/api/prompts-preview", json={"language": "en", "mode": "lesson"}).json()["system"]
    assert "job interview" not in pv
    assert any(r["expired"] for r in client.get("/api/directives?language=en").json())


def test_chat_break_mode(client):
    for lang, name in (("sv", "fika"), ("fr", "pause café"), ("en", "tea time")):
        pv = client.post("/api/prompts-preview", json={"language": lang, "mode": "break"}).json()["system"]
        assert f"relaxed {name}" in pv
    s = client.post("/api/sessions", json={"language": "sv", "mode": "break"}).json()
    assert s["mode"] == "break"


# ---------------------------------------------------------------------------
# settings safety, model swapping, offline mode, cache, window
# ---------------------------------------------------------------------------
def test_settings_survive_damage_and_roundtrip(client, tmp_path):
    from parlera.config import Settings
    core = client.core
    core.settings.update({"llm": {"model": "my-model:7b"}})
    core.settings.update({"tts": {"speed": 1.1}})               # creates settings.json.bak with my-model
    core.paths.settings.write_text("{ broken json")              # e.g. disk full / crash mid-write
    s = Settings(core.paths.settings).all()
    assert s["llm"]["model"] == "my-model:7b"                     # restored, not reset to defaults
    exported = client.get("/api/settings/export")
    assert exported.json()["llm"]["model"] == "my-model:7b"
    core.settings.update({"llm": {"model": "other"}})
    r = client.post("/api/settings/import", files={"file": ("s.json", exported.content, "application/json")})
    assert r.status_code == 200 and core.settings.get("llm.model") == "my-model:7b"
    bad = client.post("/api/settings/import", files={"file": ("s.json", b'{"foo": 1}', "application/json")})
    assert bad.status_code == 400
    core.daily_backup()
    assert (core.paths.backups / "settings-latest.json").exists()


def test_only_one_big_model_in_memory(client):
    import asyncio
    core = client.core
    mock_services.state["running"].clear()
    mock_services.state["unloads"].clear()
    core.settings.update({"llm": {"model": "gemma4:26b", "analysis_model": "muse-glimmer:30b-mlx"}})
    mock_services.state["running"].update({"gemma4:26b": 17e9, "tiny:1b": 1e9})
    asyncio.run(core.llm.chat([{"role": "user", "content": "hi"}], model="muse-glimmer:30b-mlx"))
    assert "gemma4:26b" in mock_services.state["unloads"]          # big conversation model unloaded first
    assert "tiny:1b" in mock_services.state["running"]             # small models stay
    # after a session analysis the analysis model is freed again
    s = client.post("/api/sessions", json={"language": "sv", "mode": "lesson"}).json()
    core.db.add_message(s["id"], "assistant", "Hej!")
    core.db.add_message(s["id"], "user", "Hej")
    mock_services.state["unloads"].clear()
    client.post(f"/api/sessions/{s['id']}/end")
    assert "muse-glimmer:30b-mlx" in mock_services.state["unloads"]
    # switching it off keeps both
    core.settings.update({"llm": {"exclusive_models": False}})
    mock_services.state["unloads"].clear()
    mock_services.state["running"]["gemma4:26b"] = 17e9
    asyncio.run(core.llm.chat([{"role": "user", "content": "hi"}], model="muse-glimmer:30b-mlx"))
    assert mock_services.state["unloads"] == []


def test_offline_mode_detection(tmp_path, monkeypatch):
    import os
    from parlera.config import DEFAULT_SETTINGS, deep_merge
    from parlera.system import configure_offline, needed_hf_models
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hub"))
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    st = deep_merge(DEFAULT_SETTINGS, {"tts": {"engines": {"en": "kokoro"}}})
    assert needed_hf_models(st) == ["hexgrad/Kokoro-82M", "mlx-community/whisper-large-v3-turbo"]
    r = configure_offline(st)
    assert not r["offline"] and len(r["missing"]) == 2 and "HF_HUB_OFFLINE" not in os.environ
    for repo in r["needed"]:
        (tmp_path / "hub" / ("models--" + repo.replace("/", "--")) / "snapshots" / "abc").mkdir(parents=True)
    r = configure_offline(st)
    assert r["offline"] and os.environ.get("HF_HUB_OFFLINE") == "1"


def test_cache_info_and_clear(client):
    core = client.core
    (core.paths.tts_cache / "a.wav").write_bytes(b"x" * 5000)
    (core.paths.media / "b.wav").write_bytes(b"y" * 3000)
    for d in ("2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"):
        (core.paths.backups / f"parlera-{d}.db").write_bytes(b"z" * 100)
    info = client.get("/api/system").json()
    assert info["cache"]["tts"]["bytes"] == 5000 and info["cache"]["media"]["bytes"] == 3000
    assert info["cache"]["models"]["readonly"]
    r = client.post("/api/cache/clear", json={"targets": ["tts", "media", "old_backups", "models"]}).json()
    assert r["freed"] >= 8000
    assert not any(core.paths.tts_cache.iterdir()) and not any(core.paths.media.iterdir())
    kept = sorted(p.name for p in core.paths.backups.glob("parlera-20*.db"))
    assert len(kept) == 3                                            # newest daily backups kept
    assert core.db.scalar("SELECT COUNT(*) FROM learner") is not None   # data untouched


def test_app_window_launcher(tmp_path, monkeypatch):
    import parlera.system as system
    calls = []
    monkeypatch.setattr(system, "find_app_browser", lambda: "/usr/bin/google-chrome")
    monkeypatch.setattr(system.subprocess, "Popen", lambda args, **kw: calls.append(args))
    monkeypatch.setattr(system.webbrowser, "open", lambda url: calls.append(["tab", url]))
    assert system.open_ui("http://127.0.0.1:8642", "auto", tmp_path / "prof") == "app:google-chrome"
    assert "--app=http://127.0.0.1:8642" in calls[0] and any(a.startswith("--user-data-dir=") for a in calls[0])
    assert system.open_ui("http://127.0.0.1:8642", "browser", tmp_path / "prof") == "browser"
    monkeypatch.setattr(system, "find_app_browser", lambda: None)
    assert system.open_ui("http://127.0.0.1:8642", "auto", tmp_path / "prof") == "browser"


def test_manifest_for_add_to_dock(client):
    assert '/static/manifest.json' in client.get("/").text
    m = client.get("/static/manifest.json").json()
    assert m["display"] == "standalone" and m["name"] == "Parlera"
    assert client.get("/static/icon-512.png").status_code == 200


# ---------------------------------------------------------------------------
# demo mode
# ---------------------------------------------------------------------------
def test_demo_copy_is_isolated(tmp_path):
    import json as _json
    from parlera.config import Paths
    from parlera.db import DB
    from parlera.demo import prepare_demo_dir
    real = Paths(tmp_path / "real")
    real.ensure()
    db = DB(real.db)
    db.insert("memories", {"content": "Real memory", "created_at": "2026-01-01", "updated_at": "2026-01-01"})
    db.close()
    real.settings.write_text(_json.dumps({"llm": {"model": "gemma4:26b-mlx"}, "anki": {"url": "http://127.0.0.1:8765"}}))
    (real.prompts / "tutor_base.md").write_text("MY EDITED PROMPT")

    demo = prepare_demo_dir(real, "copy")
    s = _json.loads((demo / "settings.json").read_text())
    assert s["llm"]["model"] == "gemma4:26b-mlx" and s["app"]["demo"] == "copy"
    assert s["anki"]["url"] == "http://127.0.0.1:9" and s["anki"]["auto_add"] is False   # real Anki untouched
    assert (demo / "prompts" / "tutor_base.md").read_text() == "MY EDITED PROMPT"
    ddb = DB(demo / "parlera.db")
    assert ddb.scalar("SELECT content FROM memories") == "Real memory"
    ddb.insert("memories", {"content": "Demo memory", "created_at": "2026-01-02", "updated_at": "2026-01-02"})
    ddb.close()
    rdb = DB(real.db)
    assert [r["content"] for r in rdb.all("SELECT content FROM memories")] == ["Real memory"]   # unchanged
    rdb.close()

    fresh = prepare_demo_dir(real, "fresh")
    assert not (fresh / "parlera.db").exists() and not (fresh / "prompts").exists()
    assert _json.loads((fresh / "settings.json").read_text())["llm"]["model"] == "gemma4:26b-mlx"
    import shutil
    shutil.rmtree(demo, ignore_errors=True)
    shutil.rmtree(fresh, ignore_errors=True)


def test_demo_server_runs_and_cleans_up(tmp_path):
    """Start a real demo process from a real data folder, use it, end it, check nothing leaked."""
    import json as _json
    import httpx
    from parlera.config import Paths
    from parlera.demo import spawn_demo
    real = Paths(tmp_path / "real")
    real.ensure()
    real.settings.write_text(_json.dumps({"stt": {"backend": "off"}, "tts": {"engine": "browser"},
                                          "llm": {"base_url": "http://127.0.0.1:9"}}))
    before = sorted(p.relative_to(real.root).as_posix() for p in real.root.rglob("*"))
    d = spawn_demo(real.root, "copy", open_window=False)
    try:
        st = httpx.get(d["url"] + "/api/status", timeout=10).json()
        assert st["demo"] == "copy"
        demo_root = st["data_dir"]
        assert demo_root != str(real.root) and "parlera-demo-" in demo_root
        httpx.post(d["url"] + "/api/memories", json={"content": "only in the demo"}, timeout=10)
        httpx.post(d["url"] + "/api/sessions", json={"language": "sv", "mode": "lesson"}, timeout=10)
        sd = httpx.post(d["url"] + "/api/shutdown", timeout=10).json()
        assert sd["ok"]
        d["process"].wait(timeout=20)
    finally:
        if d["process"].poll() is None:
            d["process"].kill()
    assert not Path(demo_root).exists()                                    # temporary copy deleted
    after = sorted(p.relative_to(real.root).as_posix() for p in real.root.rglob("*"))
    assert after == before                                                 # real folder untouched


# ---------------------------------------------------------------------------
# teachers, practice games, grammar lectures
# ---------------------------------------------------------------------------
def test_teacher_name_and_gender_flow_into_prompts(client):
    core = client.core
    ctx = core.build_context("en", "lesson")
    assert ctx["teacher_name"] == "Oliver" and ctx["teacher_gender"] == "male"
    client.put("/api/settings", json={"teachers": {"en": {"name": "Charlotte", "gender": "female"},
                                                   "fr": {"name": "Julien", "gender": "male"}}})
    en = core.render_system_prompt(core.build_context("en", "lesson"))
    assert "You are Charlotte" in en and "Your name is **Charlotte** and you are a woman" in en
    assert "Oliver" not in en
    fr = core.render_system_prompt(core.build_context("fr", "lesson"))
    assert "Julien" in fr and "je suis content**" in fr and "contente" not in fr
    # an empty name falls back to the default instead of producing "Your name is ****"
    client.put("/api/settings", json={"teachers": {"sv": {"name": "  ", "gender": "x"}}})
    assert core.teacher("sv") == {"name": "Astrid", "gender": "female"}


def test_lesson_prompt_shapes_by_level(client):
    core = client.core
    a1 = core.render_system_prompt(core.build_context("sv", "lesson"))
    assert "Notice the grammar" in a1 and "exit quiz" in a1.lower() and "Task first" not in a1
    assert "feedback ladder" in a1.lower() and "Make them remember" in a1
    c1 = core.render_system_prompt(core.build_context("en", "lesson"))      # English course starts at C1
    assert "Task first" in c1 and "Task again, with a twist" in c1
    focused = core.render_system_prompt(core.build_context("sv", "lesson", focus="Grammar: V2"))
    assert "The learner chose a focus for today: **Grammar: V2**" in focused


def test_voice_follows_teacher_gender(client):
    tts = client.core.tts
    tts._macos_voices = [
        {"name": "Ava (Premium)", "locale": "en_US", "quality": 2, "gender": "female"},
        {"name": "Daniel (Enhanced)", "locale": "en_GB", "quality": 1, "gender": "male"},
        {"name": "Alva (Premium)", "locale": "sv_SE", "quality": 2, "gender": "female"},
        {"name": "Oskar", "locale": "sv_SE", "quality": 0, "gender": "male"},
    ]
    assert tts.pick_voice("macos", "en") == "Daniel (Enhanced)"            # Oliver is male → male voice beats premium female
    assert tts.pick_voice("macos", "en", speaker="sv") == "Ava (Premium)"   # Astrid's English explanations: female
    assert tts.pick_voice("macos", "sv") == "Alva (Premium)"
    client.put("/api/settings", json={"teachers": {"sv": {"gender": "male"}}})
    assert tts.pick_voice("macos", "sv") == "Oskar"
    # an explicit choice always wins for the teacher's own language …
    client.put("/api/settings", json={"tts": {"voices": {"macos": {"en": "Ava (Premium)"}}}})
    assert tts.pick_voice("macos", "en") == "Ava (Premium)"
    # … but the English voice of a male Swedish teacher stays male
    assert tts.pick_voice("macos", "en", speaker="sv") == "Daniel (Enhanced)"
    # Kokoro: automatic voice by gender, French has only a female voice
    assert tts.pick_voice("kokoro", "en") == "bm_george"
    assert tts.pick_voice("kokoro", "en", speaker="fr") == "bf_emma"
    assert tts.pick_voice("kokoro", "fr") == "ff_siwis"
    from parlera.tts import voice_gender
    assert voice_gender("macos", "Thomas (Enhanced)") == "male" and voice_gender("piper", "en_GB-alba-medium") == "female"


def test_practice_helpers():
    from parlera import practice
    assert practice.cloze("Jag springer varje dag.", "springa")["answer"] == "springer"
    assert practice.cloze("Elle a une petite maison.", "maison") == {"before": "Elle a une petite ", "answer": "maison", "after": "."}
    assert practice.cloze("Il fait beau aujourd'hui.", "beau temps") is None
    assert practice.cloze("We need to take up a hobby.", "take up")["answer"] == "take up"
    assert practice.split_article("ett hus", "sv") == ("ett", "hus", "ett")
    assert practice.split_article("la maison", "fr") == ("la", "maison", "f")
    assert practice.split_article("l'eau", "fr")[1] == "eau"
    assert practice.phrase_cloze("Jag mår bra, tack.", "sv", {"tack", "jag"})["answer"] == "tack"
    assert not practice.scramble_ok("Je m'appelle …")


def test_practice_pool_results_and_misses(client):
    core = client.core
    client.post("/api/vocab", json={"language": "sv", "lemma": "en bil", "translation": "a car",
                                    "example": "Bilen är röd.", "example_translation": "The car is red."})
    client.post("/api/vocab", json={"language": "sv", "lemma": "springa", "translation": "to run",
                                    "example": "Jag springer varje dag.", "example_translation": "I run every day."})
    ov = client.get("/api/practice/sv").json()
    assert ov["counts"]["vocab"] == 2 and ov["counts"]["unit"] > 10 and ov["round_length"] == 10
    assert ov["topics"] and ov["topics"][0]["level"] == "A1" and any(t["current"] for t in ov["topics"][0]["topics"])
    pool = client.get("/api/practice/sv/items?source=vocab").json()
    car = next(i for i in pool["items"] if i["bare"] == "bil")
    assert car["gender"] == "en" and car["term"] == "en bil" and car["cloze"]["answer"] == "Bilen"
    run = next(i for i in pool["items"] if i["bare"] == "springa")
    assert run["cloze"]["answer"] == "springer" and run["cloze"]["hint"] == "I run every day."
    assert pool["distractors"]
    unit = client.get("/api/practice/sv/items?source=unit&count=20").json()
    assert unit["items"][0]["unit_id"] == unit["unit"]["id"]               # current unit first

    r = client.post("/api/practice/sv/results", json={"game": "choice", "source": "vocab", "seconds": 95, "results": [
        {"term": "en bil", "meaning": "a car", "correct": False}, {"term": "springa", "meaning": "to run", "correct": True}]}).json()
    assert r["score"] == 1 and r["total"] == 2 and r["stats"]["today"] == 1 and r["stats"]["misses"] == 1
    misses = client.get("/api/practice/sv/items?source=misses").json()["items"]
    assert [m["term"] for m in misses] == ["en bil"] and misses[0]["cloze"]       # full item data comes back
    # two correct answers in a row clear a miss
    for _ in range(2):
        client.post("/api/practice/sv/results", json={"game": "typing", "source": "misses",
                                                      "results": [{"term": "en bil", "correct": True}]})
    assert client.get("/api/practice/sv/items?source=misses").json()["items"] == []
    # games count for the streak and practice minutes
    stats = core.stats("sv")
    assert stats["streak"] == 1 and stats["week_minutes"] >= 1


def test_fix_my_mistakes_source(client):
    sid = client.post("/api/sessions", json={"language": "sv", "mode": "lesson"}).json()["id"]
    client.core.db.add_message(sid, "user", "Jag Sam heter")
    client.core.db.add_message(sid, "assistant", "✏️ **Jag heter Sam**")
    client.post(f"/api/sessions/{sid}/end")
    pool = client.get("/api/practice/sv/items?source=errors").json()
    assert pool["items"][0]["kind"] == "fix" and pool["items"][0]["wrong"] == "Jag Sam heter"
    assert pool["items"][0]["term"] == "Jag heter Sam" and pool["counts"]["errors"] == 1


def test_grammar_lecture_create_ask_delete(client):
    client.put("/api/settings", json={"llm": {"analysis_model": "muse-glimmer:30b-mlx"}})
    lec = client.post("/api/lectures", json={"language": "sv", "topic": "Verb second (V2)", "unit_id": "sv-a1-01"}).json()
    c = lec["content"]
    assert c["title"].startswith("Verb second") and c["steps"][1]["examples"][0]["target"].startswith("Idag")
    assert c["table"]["columns"] == ["1", "2 (verb)", "3", "rest"] and len(c["table"]["rows"]) == 2
    assert all(q["answer"] in q["options"] for q in c["quiz"]) and c["speaking_task"]
    assert lec["level"] == "A1" and lec["unit_id"] == "sv-a1-01"
    assert "muse-glimmer:30b-mlx" in mock_services.state["unloads"]          # big analysis model released afterwards
    lst = client.get("/api/lectures?language=sv").json()
    assert lst[0]["id"] == lec["id"] and lst[0]["title"] == c["title"]
    assert client.get("/api/practice/sv").json()["lectures"][0]["id"] == lec["id"]
    qa = client.post(f"/api/lectures/{lec['id']}/ask", json={"question": "Does V2 apply in questions?"}).json()
    assert qa["q"] == "Does V2 apply in questions?" and qa["a"]
    again = client.get(f"/api/lectures/{lec['id']}").json()
    assert again["content"]["followups"][0]["q"] == qa["q"]
    assert client.post("/api/lectures", json={"language": "sv", "topic": "  "}).status_code == 400
    client.delete(f"/api/lectures/{lec['id']}")
    assert client.get(f"/api/lectures/{lec['id']}").status_code == 404


def test_clean_lecture_repairs_model_output():
    from parlera.core import clean_lecture
    c = clean_lecture({"title": "", "quiz": [
        {"question": "Pick", "options": ["a", "b"], "answer": "B", "explanation": ""},      # case mismatch → matched
        {"question": "Pick", "options": ["a", "b"], "answer": "c", "explanation": ""},      # missing → appended
        {"question": "Bad", "options": ["only"], "answer": "only", "explanation": ""}],     # too few options → dropped
        "table": {"caption": "x", "columns": [], "rows": [["1"]]}, "steps": "nonsense"}, "Fallback topic")
    assert c["title"] == "Fallback topic" and c["steps"] == [] and c["table"]["rows"] == []
    assert [q["answer"] for q in c["quiz"]] == ["b", "c"] and c["quiz"][1]["options"] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# English corrections switch, recognition slips, translation with context
# ---------------------------------------------------------------------------
def test_native_corrections_can_be_switched_off(client):
    core = client.core
    on = core.render_system_prompt(core.build_context("fr", "conversation"))
    assert "✏️ English:" in on and "Speech-recognition slips" in on
    client.put("/api/settings", json={"conversation": {"correct_native": False}})
    ctx = core.build_context("fr", "conversation")
    off = core.render_system_prompt(ctx)
    assert "✏️ English:" not in off and "Don't correct the learner's English" in off
    assert "Speech-recognition slips" in off                           # the misrecognition guard stays
    analysis = core.prompts.render("analysis_session", **ctx, transcript="", known_error_patterns=[], existing_memories=[])
    assert "Do NOT include mistakes in their English" in analysis
    # the English course is unaffected (it is all about English)
    assert "Don't correct the learner's English" not in core.render_system_prompt(core.build_context("en", "conversation"))


def test_translate_with_context_and_english_explain(client):
    core = client.core
    word = core.prompts.render("translate", language="sv", language_name="Swedish", native_language="English", level="A1",
                               direction="to_native", text="springer", context="Jag springer varje dag.")
    assert "selected a word or phrase" in word and "Jag springer varje dag." in word
    whole = core.prompts.render("translate", language="sv", language_name="Swedish", native_language="English", level="A1",
                                direction="to_native", text="Hej!", context="")
    assert whole.strip().startswith("Translate the following Swedish text")
    r = client.post("/api/translate", json={"text": "springer", "context": "Jag **springer** varje dag.", "language": "sv",
                                           "direction": "to_native"})
    assert r.status_code == 200 and r.json()["text"]
    # the English course's "Explain" gets its own instructions (monolingual was missing before)
    seen = {}
    real_chat = core.llm.chat

    async def spy(messages, **kw):
        seen["system"] = messages[0]["content"]
        return "explained"
    core.llm.chat = spy
    client.post("/api/translate", json={"text": "ubiquitous", "language": "en", "direction": "to_native"})
    core.llm.chat = real_chat
    assert seen["system"].strip().startswith("Explain the following English text")


def test_auto_mode_rechecks_unsure_english(client):
    import base64
    core = client.core
    calls = []

    def fake_transcribe(wav, lang, prompt):
        calls.append(lang)
        if lang is None:   # auto: Whisper wrongly hears English, with low word confidence
            return {"text": "Shut a pell Sam", "language": "en", "words": [{"word": "Shut", "p": 0.3}, {"word": "pell", "p": 0.4}]}
        return {"text": "Je m'appelle Sam.", "language": "fr", "words": [{"word": "Je", "p": 0.9}, {"word": "m'appelle", "p": 0.85}]}

    core.stt.backend = lambda: "fake"
    core.stt.preload = lambda *a: None
    core.stt.transcribe = fake_transcribe
    s = client.post("/api/sessions", json={"language": "fr", "mode": "conversation"}).json()
    with client.websocket_connect(f"/ws/sessions/{s['id']}") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_audio", "data": base64.b64encode(_tone_wav()).decode(), "lang": "auto"})
        events = _collect_turn(ws)
    assert calls == [None, "fr"]
    assert next(e for e in events if e["type"] == "transcript")["text"] == "Je m'appelle Sam."
    # confident English stays English (no second pass)
    from parlera.tutor import confidence
    assert confidence({"words": [{"p": 0.9}, {"p": 0.8}]}) > 0.7 and confidence({}) == 1.0


def test_edit_teacher_instructions_and_live_prompt_refresh(client):
    from datetime import datetime
    core = client.core
    saved = client.post("/api/directives", json={"language": "fr", "text": "note", "items": [
        {"content": "Speak more slowly.", "kind": "behaviour", "days": 7, "all_languages": False}]}).json()
    did = saved[0]["id"]
    # edit text, make it permanent and valid for all languages
    d = client.patch(f"/api/directives/{did}", json={"content": "Speak slowly and clearly.", "days": 0,
                                                     "all_languages": True, "kind": "behaviour"}).json()
    assert d["content"] == "Speak slowly and clearly." and d["expires_at"] is None and d["language"] is None
    assert "Speak slowly and clearly." in core.render_system_prompt(core.build_context("sv", "lesson"))  # all languages
    d = client.patch(f"/api/directives/{did}", json={"days": 14, "all_languages": False, "language": "fr"}).json()
    assert d["language"] == "fr" and (datetime.fromisoformat(d["expires_at"]) - datetime.now()).days in (13, 14)
    assert "Speak slowly" not in core.render_system_prompt(core.build_context("sv", "lesson"))
    assert client.patch(f"/api/directives/{did}", json={"content": "  "}).status_code == 400
    assert client.patch("/api/directives/99999", json={"active": 0}).status_code == 404

    # an open session picks up changes before its next reply (prompt cached otherwise)
    from parlera.tutor import TutorSession
    s = client.post("/api/sessions", json={"language": "fr", "mode": "conversation"}).json()
    ts = TutorSession.__new__(TutorSession)
    ts.app, ts.session, ts.system_prompt, ts._prompt_version = core, core.db.session(s["id"]), None, -1
    first = ts._system()
    assert "Speak slowly and clearly." in first and ts._system() is first   # cached between turns
    v = core.context_version
    client.post("/api/directives", json={"language": "fr", "text": "x", "items": [
        {"content": "Use lots of food vocabulary.", "kind": "focus", "days": 7, "all_languages": False}]})
    assert core.context_version == v + 1
    client.get("/api/directives?language=fr")
    assert core.context_version == v + 1                                 # reads don't count
    assert "Use lots of food vocabulary." in ts._system()                # rebuilt for the next reply
