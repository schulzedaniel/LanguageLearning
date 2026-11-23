# CLAUDE.md — maintainer notes for Claude

This file is for Claude (or any developer). It explains the whole project so a new session can
make changes **without reading every file**. Read this first, then open only the files you need.
Keep it up to date when you change architecture, data model, settings, endpoints or conventions.
The user-facing documentation is `README.md`.

## 1. What this is

**Parlera** is a local, private language tutor for **Swedish, French and English**, written for one user
(the repo owner). It's a speaking-first web app that runs on their Mac.

**The user and their machine**
- MacBook with an M5 Pro and 48 GB RAM.
- Native/explanation language: English.
- Swedish: total beginner. French: school French, mostly forgotten. English: B2/C1 (probably C1); wants polished grammar and sophisticated vocabulary.
- Long-term goals: DELF (French), Swedex/TISUS (Swedish), and top scores in IELTS Academic, TOEFL iBT and the Duolingo English Test (English).
- Has an existing English Anki deck made elsewhere; it can be linked via *Vocabulary → Import from Anki*.

**The stack, all local**
- Ollama runs the LLM. The default is `gemma4:26b`; the user runs `gemma4:26b-mlx`. Setup's Enter key picks an installed `gemma4*` model, and Gemma 4's thinking mode is turned off via `think:false`.
- Whisper does speech-to-text: `mlx-whisper` on Apple Silicon, `faster-whisper` elsewhere.
- Text-to-speech uses macOS `say` (the Premium system voices), Piper, or the browser's speechSynthesis.
- Anki is reached through the AnkiConnect add-on.
- Backend: FastAPI with SQLite. Frontend: vanilla JS ES modules with **no build step**.

**User requests that shaped the design (keep honouring them)**
- Real voice conversation in English plus the target language, with a curriculum that runs from session to session.
- Anki cards from each session, **auto-added to a deck chosen in Settings** (per language, default `Parlera::Swedish` / `Parlera::French`).
- Editable teacher prompts and curricula, a nice GUI, and resumable sessions and memories.
- The tutor speaks **primarily the target language** and **also corrects the user's English**.
- Pronunciation feedback, implemented heuristically (see §7).
- Everything local. Models are never duplicated: we only use Ollama's own model store.
- Recently learned words are reinforced subtly in sessions, depending on when they were added and their Anki status (§6, "Reinforcement").
- Updates must never lose progress: data lives outside the program folder, and unedited default prompts/curricula upgrade themselves (§4).
- Proper quitting: a "Quit Parlera" button, auto-quit after the last tab closes, the model unloaded, Ollama quit per setting (§6, "Quitting").
- Natural voices: Kokoro, selectable per language (English, French), alongside macOS/Piper.
- A weekly mistake workshop (§6), situation presets (can't speak / can't listen), "Message your teacher" instructions, and a chat break (Fika / Pause café / Tea time).
- A demo mode that leaves no lasting changes (§6, "Demo mode").
- Configurable teachers: name + gender per language (Settings → Your teachers); the voice follows the gender (§6, "Teachers & voices").
- Research-based teaching prompts (Nation's four strands, Lyster & Ranta feedback ladder, TBLT task cycle, retrieval practice) (§10).
- A Practice page for short sessions without speaking: local quick games + grammar lectures written by the reasoning model (§6, "Practice").
- Markdown must render properly wherever model/prompt text is shown (prompt preview, review, lectures).
- Settings must survive updates; cache clearing; a dedicated app window; fully offline after setup; never two big models in RAM.
- The user asked about `muse-glimmer:30b-mlx` (Meta, 30B, reasoning, agent-focused, ~21 GB). Recommended: keep Gemma 4 for conversation, and optionally try Muse Glimmer as the *analysis* model.

## 2. Run, test, develop

```bash
./setup.sh            # macOS: venv, deps, choose/pull Ollama model, Whisper prefetch, ~/Applications/Parlera.app
./run.sh              # starts Ollama if needed, serves http://127.0.0.1:8642, opens browser
.venv/bin/python -m pytest -q          # 46 tests, ~10 s, no GPU/Ollama/Anki needed (also verified on Python 3.12)
python3 tools/update_default_hashes.py # run BEFORE committing changes to parlera/defaults/{prompts,curricula}
.venv/bin/python tools/mock_services.py [ollama_port] [anki_port]   # fake Ollama (:11434) + AnkiConnect (:8765)
```

**Running against the fakes:** run `mock_services.py`, then write a `settings.json` in a temp data
dir that points `llm.base_url` and `anki.url` at the mock ports. Set `tts.engine: "browser"` and
start with `PARLERA_DATA=<dir> python -m parlera --no-browser`.

**UI checks:** drive the app with Playwright. Chromium is preinstalled in cloud sessions; use
`require('playwright')` with `NODE_PATH=$(npm root -g)`. The flags
`--use-fake-ui-for-media-stream --use-fake-device-for-media-stream` give the page a fake mic.
That mic plays a constant beep, so hands-free voice detection never sees a pause; test push-to-talk instead.

**Cloud-session limits:** huggingface.co is blocked, so you can't download Whisper or Piper models.
There's no macOS `say` and no Ollama. Test speech by stubbing `core.stt` / `core.tts`, as in
`tests/test_parlera.py::test_voice_pipeline_with_fake_engines`.

**Git:** `main` holds the merged app (PR #2). Make changes on a new branch from `origin/main`, push it, and give the user the compare link so they can merge. This clone only fetches `main` by default; when the push hook complains about a missing remote branch, add a fetch refspec for that branch.
Pushing to `schulzedaniel/LanguageLearning` has worked from cloud sessions.

## 3. Repository map (≈ line counts)

```
setup.sh (129)          interactive mac setup; writes parlera.env (PARLERA_DATA=…), sets llm.model in settings,
                        lists already-installed Ollama models (no duplicate downloads), creates ~/Applications/Parlera.app (osacompile → Terminal → ./run.sh; Info.plist renamed to "Parlera" + ad-hoc re-signed so the Automation prompt doesn't say "applet")
run.sh (45)             sources parlera.env; starts Ollama (open -g -a Ollama | ollama serve) if not running; on exit quits Ollama only if it started it
Parlera.command (3)     Finder double-click launcher → run.sh
pyproject.toml          deps; extras: mac (mlx-whisper), faster (faster-whisper), piper (piper-tts), dev (pytest)
parlera/
  __main__.py (38)      CLI: --host --port(8642) --no-browser --data
  config.py (174)       Paths (data dir layout), DEFAULT_SETTINGS (single source of truth for settings keys), Settings (JSON, deep-merged, thread-safe)
  db.py (252)           SQLite schema (PRAGMA user_version migrations list MIGRATIONS), DB helper (all/one/scalar/insert/update/backup_to), learner/session/message helpers
  core.py (1200)        class Parlera = app core. Wires everything; context building; analysis; progression; vocab pipeline; Anki push/sync; stats;
                        teacher(); grammar lectures (create_lecture/ask_lecture, LECTURE_SCHEMA, clean_lecture)
  practice.py (270)     Practice games data: build_pool (sources unit|vocab|mix|misses|errors), cloze/phrase_cloze/split_article,
                        record_results (practice_log + practice_items), stats, grammar_topics
  main.py (660)         create_app(): all REST endpoints + WebSocket + static; exception→HTTP mapping; startup backup; shutdown unloads Ollama model
  tutor.py (262)        TutorSession: WebSocket conversation loop (STT → LLM stream → sentence TTS), interrupt handling, pronunciation hints
  llm.py (200)          OllamaClient (chat_stream, chat, chat_json w/ JSON-schema `format`, list_models, warm, unload), ThinkFilter, parse_json_loose
  prompts.py (123)      PROMPT_INFO (prompt registry shown in UI), MODES (session types), PromptStore (Jinja2, data dir overrides defaults)
  curriculum.py (138)   YAML load/validate/normalize (adds level, index, vocab_pairs, phrase_pairs), Curricula cache by mtime
  textproc.py (204)     strip_for_speech, SentenceStream (streaming splitter, never splits inside **bold**, flags ✏️ lines), language detection (lingua + stopword heuristic), segment_languages
  pronunciation.py (85) low-confidence words + repetition diff vs last tutor **bold** phrases → hint note
  stt.py (119)          STTManager: backend auto-select (mlx on Apple Silicon > faster), transcribe() returns {text, language, words:[{word,p}]}, hallucination filter
  tts.py (330)          TTSManager: engines macos/piper/kokoro/browser/off, voice listing & gender-aware auto-pick (pick_voice: teacher gender > Premium > Enhanced >
                        locale > preferred names), MACOS_GENDER, voice_gender(), disk cache, PIPER_CATALOG (with gender)
  audio.py (71)         WAV decode/resample/concat (numpy, no ffmpeg)
  demo.py (110)         demo mode: prepare_demo_dir (temporary copy; sqlite backup API), spawn_demo (second server process)
  system.py (170)       app window (open_ui: Chrome/Edge/Brave --app with private profile <data>/browser), offline mode
                        (configure_offline → HF_HUB_OFFLINE=1 when all needed HF repos are cached), cache_info/clear_cache
  anki.py (231)         note type "Parlera Vocab" (fields/templates/CSS), deck_name(), display_word() (adds en/ett, le/la/l'), AnkiConnect client, build_apkg (genanki)
  defaults/prompts/*.md copied to <data>/prompts on first run (never overwritten afterwards)
  defaults/curricula/{sv,fr}.yaml   31 units each: A1 12, A2 8, B1 6, B2 5
  defaults/curricula/en.yaml        19 units: B2 5, C1 9, C2 5; `start_unit: en-c1-01`
  defaults/known_hashes.json        hashes of every committed version of the defaults → auto-upgrade of unedited user copies
  static/logo.svg, icon-1024.png    app logo (macOS-style tile); favicon.svg is the cropped tile; setup builds the .icns from the PNG
  static/index.html, css/app.css (350), favicon.svg
  static/js/  app.js (shell, router, sidebar status, auto push-pending to Anki) · nav.js (navigate, applyTheme, refreshStatusSoon)
              api.js (fetch wrapper, state, LANGS — `LANGS[x].tutor`/`tutorGender` are getters reading settings.teachers; teacher(lang))
              speech.js (say(text, lang): server voice or browser fallback, outside sessions) · ui.js (h() DOM helper, icons, modal/toast/confirm, mount) · markdown.js (renderMarkdown: bold→.tl, ✏️ → .correction; renderDocument: full documents with headings/nested lists/tables, used by the prompt preview)
              audio.js (Recorder: AudioWorklet + energy VAD + PTT, WAV encode; Player: queue of WAV/speechSynthesis) · recorder-worklet.js
  static/js/views/ dashboard · session (561, the live conversation) · practice (games picker + player + Grammar tab, explainGrammar) · lecture (lecture reader + quiz + follow-ups) · review (post-session) · curriculum (+YAML editor) · vocab (+addWordDialog)
                   history · memory (memories, recurring errors, notes) · prompts (editor + preview) · settings · start (new-session dialog)
docs/architecture.svg   architecture/data-flow diagram embedded in README — regenerate with `python3 docs/make_architecture.py`
                        (hand-placed coordinates; update it when components/flows change, then render with Playwright to check)
tests/test_parlera.py (980)  end-to-end against mock services (spins them up on free ports)
tools/mock_services.py (160) fake Ollama (canned streaming Swedish replies; JSON by schema shape) + fake AnkiConnect
                        (in-memory notes with fields/decks; a pre-existing "English Vocab" deck for import tests)
tools/update_default_hashes.py  scans git history of the defaults and writes parlera/defaults/known_hashes.json
```

## 4. Data folder (`PARLERA_DATA`, default `~/Parlera`)

`setup.sh` asks for the location and stores it in `parlera.env` (gitignored) next to the code.
`run.sh` sources that file. The folder contains:

- `parlera.db`
- `settings.json`
- `prompts/`, `curricula/`
- `voices/` (Piper `.onnx` files)
- `media/`
- `cache/tts/` (sha1-keyed WAVs, pruned after 30 days)
- `backups/parlera-YYYY-MM-DD.db` (daily at startup, the last 14 are kept)

Backup zip: `parlera.db`, `settings.json`, `prompts/*`, `curricula/*`, `manifest.json`. On restore,
a `before-restore-*.db` safety copy is written first.

**Default upgrades** (`config.Paths.ensure`, runs at every start; returns the upgraded files, which are logged):
- A missing file is copied from the defaults (new courses and prompts arrive this way).
- A file equal to the current default is left alone.
- A file equal to an **older** default (its hash is in `defaults/known_hashes.json`) is overwritten with the current default.
- Anything else counts as user-edited and is never touched.

**Whenever you change a default prompt or curriculum, run `tools/update_default_hashes.py` before committing**, so the
version being replaced is recorded. `test_known_hashes_cover_git_history` fails if you forget.

**Where models live (never duplicated):**
- Ollama models: Ollama's own store, `~/.ollama/models`.
- Whisper: the Hugging Face cache, `~/.cache/huggingface/hub`.
- macOS voices: managed by the system.

## 5. Database schema (db.py, `user_version` = 3)

- `learner(language PK, current_unit_id, started_at, notes)`: `notes` holds the user's "notes for the tutor".
- `unit_progress(language, unit_id, status active|completed, mastery 0–1, sessions, last_session_at)`
- `sessions(id, language, mode, unit_id, scenario, focus, title, status active|completed, created_at, updated_at, ended_at, summary, analysis JSON, model)`
- `messages(id, session_id FK cascade, role user|assistant, content, hidden, created_at, meta JSON)`
  - `hidden=1` marks the opening/resume instructions.
  - `meta` keys: `input` (voice|text), `stt_lang`, `words`, `pron` ({low, rep}), `pron_note` (appended to the LLM copy only), `interrupted`.
- `vocab(id, language, lemma, lemma_norm UNIQUE per language, forms, gender en|ett|m|f, pos, translation, example, example_translation, notes, unit_id, session_id, status candidate|learning|known|ignored, source extracted|manual, reason mistake|asked|unit|new|manual, freq zipf, anki_note_id, anki_interval, anki_lapses, anki_reps, anki_synced_at, created_at, updated_at)`
- `errors(id, language, category, pattern, pattern_norm UNIQUE per language, example_wrong, example_right, explanation, count, first_seen, last_seen, last_session, resolved)`
- `memories(id, language NULL=all, category personal|preference|goal|other, content, source_session_id, pinned, active, created_at, updated_at)`
- `exam_scores(id, language, level, session_id, score, max_score, breakdown, created_at)`
- V2 adds:
  - `error_events(id, error_id→errors, language, session_id, wrong, right, created_at)`: one row per occurrence (not written for workshop sessions). The migration backfills one event per existing error.
  - `workshops(id, language, created_at, period_start, period_end, digest JSON, session_id)`
  - `directives(id, language NULL=all, kind behaviour|focus|vocabulary|other, content, source_text, expires_at NULL=permanent, active, created_at)`

- V3 adds (Practice):
  - `practice_log(id, language, game, source, score, total, seconds, created_at)`: one row per finished game round (counts for the streak and minutes in `core.stats`).
  - `practice_items(language, term_norm PK, term, meaning, vocab_id, seen, wrong, streak, last_seen, last_wrong)`: per-item stats; "My misses" = wrong > 0 and streak < 2.
  - `lectures(id, language, topic, unit_id, level, content JSON (clean_lecture shape + followups[{q,a,at}]), model, created_at, updated_at)`

**Schema changes:** append a new SQL script to `MIGRATIONS` in `db.py`. Never edit a shipped schema (V1, V2, and V3 once merged), because users' databases are already at that version.

Timestamps are local, naive ISO strings (`db.now()`); streaks use local dates.

## 6. Core flows

### Building the system prompt (`core.render_system_prompt`)
The prompt is `tutor_base` + `persona_<lang>` + `context` + `mode_<mode>`, all rendered with the
same context dict from `core.build_context()`:

| Key(s) | Content |
|---|---|
| `language`, `language_name`, `native_language` | Language codes and names |
| `teacher_name`, `teacher_gender` | From `settings.teachers[lang]` via `core.teacher()` (empty/invalid → defaults Astrid f / Élodie f / Oliver m) |
| `learner_name`, `learner_goal`, `learner_notes` | From Settings and the Memory page |
| `level`, `unit`, `unit_number`, `units_total` | `unit` is the normalized unit dict |
| `unit_progress` | `{sessions, mastery, status}` |
| `level_units`, `all_units` | Unit lists |
| `mode`, `mode_title`, `scenario`, `focus` | Session settings |
| `immersion` | % target language (see below) |
| `memories` | Active memories, pinned first, max 40 |
| `recent_summaries` | Last 3 completed sessions |
| `weak_vocab` | Anki lapses ≥ 2 or interval < 4, else recent learning words |
| `recurring_errors` | Unresolved, most frequent first |
| `exam` | The level's `exam` from the YAML |
| `exams`, `today` | Exam list and today's date |
| `monolingual` | True when the studied language is the explanation language (English course): prompts switch to an English-only coach with "✏️ Upgrade:" suggestions |
| `reinforce_vocab` | Recently learned words sampled for subtle reuse (see below) |
| `directives` | Active, unexpired instructions from "Message your teacher" (rendered in `context.md`) |
| `workshop` | The workshop digest (only in `workshop` sessions) |
| `break_name` | fika / pause café / tea time |

`TutorSession` caches the system prompt per WebSocket connection, so it stays stable for Ollama's KV cache.

**Reinforcement** (`core.reinforce_vocab`, settings `vocab.reinforce`, `vocab.reinforce_count`=6):
- Considers `learning`/`known` words added within the last 90 days, excluding `anki_lapses ≥ 2` (those go to `weak_vocab`) and words already in `weak_vocab`.
- Weight = age × Anki status:
  - age: added today 0.4, 1–21 days 1.0, 22–45 days 0.6, 46–90 days 0.3
  - Anki: not linked/not synced 0.7, never reviewed 0.5, interval ≤ 7 days 1.0, 8–20 days 0.6, ≥ 21 days 0.15
- Weighted sampling without replacement, seeded with the session id: stable within a session (KV cache), different between sessions.
- `context.md` tells the tutor to use two or three of them naturally and never quiz; `mode_review` may practise them openly.
- `POST /api/sessions` first runs `sync_anki` (4 s timeout) when `anki.auto_sync` is on, so the statuses are fresh.

**English course specifics:**
- `is_monolingual` compares the language name with `learner.native_language`. When true, immersion is 100.
- `textproc.segment_languages` sends all text to the English voice, and the session UI hides the "I speak…" toggle.
- Translate becomes "Explain", and "How do I say…" becomes "Say it better".
- `store_candidates` drops `reason=new` English words with zipf > 5.2 (too basic).
- The review page shows IELTS (max 9), TOEFL (max 6) or DET (max 160) scores as bands.
- Pronunciation hints also run when the target is English.

**Mistake workshop** (`core.workshop_status`, `core.create_workshop`; settings `workshop.interval_days` 7, `min_mistakes` 3, `thinking` true):
- **Status:** counts `error_events` since the last workshop. It's `due` when there are ≥ min_mistakes and ≥ interval_days since the last one (or there was never one). The dashboard shows a banner when due, and a "Mistake workshop" button whenever material exists.
- **Create:** groups the events by pattern (up to 4 examples each) and falls back to unresolved recurring errors when there are none. `analysis_workshop.md` then produces `WORKSHOP_SCHEMA` (title, overview, 2–5 categories with rule/why/examples/tip/patterns, plan) using `chat_json(think=True)`, retried with `think=False` on failure. This creates a `workshop` session and stores the digest.
- **Training:** `mode_workshop.md` runs explain → their own mistake → drills → mixed review → recap. The session panel shows the categories.
- **Analysis:** returns `mastered_patterns` (strict, workshop only); `_apply_analysis` sets those errors to `resolved=1`.

**Message your teacher** (`core.parse_teacher_note`, `save_directives`, `active_directives`):
- `teacher_note.md` turns a free-text note into `NOTE_SCHEMA` items (`days` 0 = permanent, `all_languages`). The UI (`views/teachernote.js`) lets the user edit each item, set its duration (7/14/30 days or permanent) and save.
- Active, unexpired items are listed in every system prompt under "The learner's own requests".

**Chat break** (mode `break`): `mode_break.md` makes it relaxed, with recast corrections and no curriculum. The session view hides the unit panel and titles it "Fika with Astrid" etc. The sidebar has a button labelled per language.

**Quitting** (`main.py`, `__main__.py`, `run.sh`; settings `app.auto_quit`, `app.idle_quit_minutes` 30, `app.quit_ollama` if_started|always|never):
- `__main__` runs `uvicorn.Server` and stores it in `app.state.server`; `request_quit()` sets `should_exit`.
- The frontend sends `POST /api/heartbeat` every 20 s, plus on `visibilitychange` and `pageshow`, and `sendBeacon('/api/bye')` on pagehide.
- The watchdog quits when a bye arrived and no heartbeat followed within 45 s (a reload survives), or after `idle_quit_minutes` without any heartbeat.
- **Never quit quickly on silence alone:** Safari pauses timers in hidden tabs.
- If heartbeats fail twice, the page shows a "Parlera is not running" overlay. If the heartbeat returns a different `build`, the page reloads itself.
- `POST /api/shutdown` is the sidebar's Quit button; the page then shows "Parlera has stopped".
- On shutdown: unload the model(s), write `backups/parlera-last-quit.db`, and if `quit_ollama == always`, `osascript quit app "Ollama"` + `pkill -x ollama`. `run.sh` quits an Ollama it started unless the setting is `never`.
- The launcher's Terminal command ends with `; exit`, so the window closes.

**Settings safety:**
- `Settings.update` copies the previous valid file to `settings.json.bak` before writing.
- `_load` falls back to `.bak`, then `backups/settings-latest.json`, if the file is damaged.
- `daily_backup` also writes `settings-latest.json` and `settings-YYYY-MM-DD.json`.
- `setup.sh` reads the current `llm.model` and offers it as the Enter default; it writes the model only if it changed.
- `GET /api/settings/export`, `POST /api/settings/import` (multipart, deep-merged).

**Model memory** (`llm.exclusive_models` true, `llm.big_model_gb` 6):
- `OllamaClient.ensure_exclusive(model)` runs before every chat/stream/warm. It reads `/api/ps` and unloads (`keep_alive: 0`) every other running model ≥ big_model_gb.
- `core.release_analysis_model()` runs after the session analysis and the workshop digest. When `analysis_model` differs from `model`, it unloads the analysis model and warms the conversation model in the background.

**Window & offline** (`app.window` auto|app|browser, `app.offline` auto|always):
- `__main__` builds `Paths`/`Settings` first, then calls `system.configure_offline()` (before any model library is imported) and opens the UI via `system.open_ui`.
- `GET /api/system` returns offline status, needed models (downloaded?), the app browser found, and cache sizes. `POST /api/cache/clear` with `{targets: tts|media|old_backups|browser}`.
- Setup prefetches Whisper, and with Kokoro also `hexgrad/Kokoro-82M` + spaCy `en_core_web_sm` (misaki needs it). The venv is created with `uv venv --seed` so pip exists for spaCy.
- `static/manifest.json` + `icon-512.png` support Safari "Add to Dock" / Chrome "Install".

**Demo mode** (`demo.py`, `python -m parlera --demo copy|fresh`, `POST /api/demo/start {mode}`):
- The main server spawns `sys.executable -m parlera --demo <mode> --port <free ≥8650>` with `PARLERA_DATA` = the real root.
- The child copies into `tempfile.mkdtemp("parlera-demo-")`: the db (via the backup API), prompts/ and curricula/ in copy mode; only settings in fresh mode. `voices/` is symlinked.
- `DEMO_OVERRIDES` disables Anki (url `127.0.0.1:9`, auto_add/auto_sync off) and sets `quit_ollama=never`. The child sets `PARLERA_DEMO` and uses `PARLERA_DATA` = the temp dir.
- On exit, `__main__` closes the db and `rmtree`s the temp dir. A demo shutdown skips the model unload, the backup and the Ollama quit (`main.DEMO`).
- `/api/status.demo` makes the UI show the striped banner and "End demo", and hides the "Demo mode" button.
- The main server terminates its demo children on shutdown. The demo window reuses the real app-window browser profile (mic permission). The last demo's log is `$TMPDIR/parlera-demo.log`.

**Teachers & voices** (`settings.teachers.{sv,fr,en}.{name,gender}`, `core.teacher`, `tts.pick_voice`):
- Personas use `{{ teacher_name }}`/`teacher_gender` (French persona: self-agreement *contente/content*). The UI never hard-codes names: `LANGS[x].tutor` is a getter over settings.
- `tts.synth(text, lang, rate, speaker)`: `speaker` = the session language (whose teacher is talking). For `lang == speaker` an explicit voice in Settings always wins; for the other language (English explanations in a Swedish lesson) the explicit voice is used only if its gender matches, else a matching voice is auto-picked. "" = auto by gender (macOS: MACOS_GENDER; Kokoro: 2nd letter f/m, default bm_george/bf_emma, French only ff_siwis; Piper: catalog `gender`, downloaded voices only). Browser voices: `audio.js voiceGender` name regex, same rule in `Player._voiceFor`.
- Changing a teacher's gender in Settings resets that language's voices (all engines) to "" (auto). Voice defaults are "" since this change; older settings files may still hold `bm_george`/`ff_siwis`/piper names (treated as explicit).

**Practice** (`practice.py`, `views/practice.js`, `views/lecture.js`; settings `practice.round_length` 10, `practice.lecture_thinking` true):
- Games are pure client logic over `GET /api/practice/{lang}/items?source=&count=` (items + distractors). Question types: flash, choice (t2m/m2t), typing, cloze, scramble, gender, fix, match (boards of 5); `mix` picks a type per item. `checkAnswer` ignores case/punctuation/articles and tolerates accents (with a note). Results → `POST /api/practice/{lang}/results`.
- Item sources: `unit` (current unit first, then the 3 before, from `vocab_pairs`/`phrase_pairs`), `vocab` (vocab table, cloze from `example`), `mix`, `misses`, `errors` (errors table example_wrong/right → "Fix my mistakes").
- Grammar lectures: `core.create_lecture` renders `lecture_grammar.md`, `chat_json(LECTURE_SCHEMA, analysis_model, think=practice.lecture_thinking)` with a think=False retry, then `release_analysis_model()` (one big model rule). `clean_lecture` repairs quiz answers/options and table shape. Follow-ups (`lecture_followup.md`) use the conversation model and are stored in `content.followups`. "Practise with X" starts a `lesson` with `focus` (mode_lesson builds the lesson around a focus). `explainGrammar` opens an existing lecture with the same topic instead of writing a new one; the Curriculum drawer has *Explain* buttons.
- Model-written Markdown is rendered everywhere (review feedback/strengths/explanations, memory, history summaries, workshop panel).

**Situation presets** (`session.js` `SITUATIONS`, stored in localStorage `parlera.situation`): full / nospeak (text input, audio on) / nolisten (voice input, audio off, text shown) / silent. They map onto the existing `inputMode` + `audioOn`.

**Immersion** (`core.immersion`): the setting `conversation.immersion` is `"auto"` or a number 0–100.
In auto mode the base is A1 50, A2 70, B1 85, B2 95, plus a span that grows with the unit's position
in the level (A1 +20, A2 +15, B1 +10, B2 +5).

### Live turn (`tutor.py`, WebSocket `/ws/sessions/{id}`)
- **Client → server:** `start{resume}`, `user_text{text}`, `user_audio{data: b64 WAV 16 kHz, lang: target|en|auto}`, `interrupt`, `settings{audio}`, `ping`.
- **Server → client:**
  - `ready{tts: server|browser|off, stt}`, `transcribing`
  - `transcript{text, message_id, pron | empty}`, `user_saved`
  - `assistant_start`, `token{text}`
  - `audio{data: b64 WAV, text}` (server TTS) **or** `speak{segments: [{lang, text}], rates}` (browser TTS, also used as fallback when server TTS errors)
  - `assistant_end{message_id, content, failed?}`, `audio_end`, `error{message}`

**How `start` behaves:**
- No visible messages yet: insert a hidden user message rendered from `opening.md`; the tutor speaks first.
- More than 20 minutes since the last message and `resume=true`: insert a hidden message from `resume.md`.
- A completed session that gets reopened goes back to `active`.

**How a turn runs:**
1. `chat_messages()` builds the history: the last `llm.context_messages` messages, trimmed so it starts with a user turn, with `pron_note` appended to user content.
2. The reply is streamed. `SentenceStream` splits it into sentences, and a TTS worker queue turns each sentence into audio in order.
3. `segment_languages` splits each sentence into English and target-language parts. **Bold = target language**; lingua checks with a 0.2 confidence margin, with a stopword/diacritics heuristic as fallback.
4. `rates` slows the target language down at A1 (0.82) and A2 (0.9) when `tts.beginner_slowdown` is on.
5. `speak_corrections=false` skips sentences on ✏️ lines.
6. On interrupt, the turn task is cancelled and the partial reply is saved with `meta.interrupted`.

**Speech recognition details:** Whisper gets an initial prompt built from the unit's vocabulary
terms, which biases it towards those words. This is skipped in `pronunciation` mode. Whisper runs
in a thread executor.

### End & review (`POST /api/sessions/{id}/end` → `core.analyze_session`)
1. `analysis_session.md` is rendered with the transcript (max 24k characters, middle trimmed). Ollama returns JSON matching `ANALYSIS_SCHEMA`, which `_clean_analysis` normalizes.
2. `_apply_analysis` then:
   - upserts errors by `pattern_norm` (count+1, un-resolves them)
   - inserts new memories (skipping duplicates; `personal` memories get `language=NULL`)
   - updates unit progress for `UNIT_MODES`: mastery is a running average (first session sets it, then 0.5 × old + 0.5 × new), sessions+1
   - suggests advancing when mastery ≥ `curriculum.advance_threshold` (0.75), sessions ≥ the unit's `min_sessions`, and the model says it's ready (or mastery ≥ threshold + 0.1). It auto-advances if `curriculum.auto_advance` is on.
   - inserts `exam_scores` in exam mode
   - marks the session completed, storing the summary, title and analysis JSON.
3. `extract_vocab` renders `analysis_vocab.md` with the transcript, known lemmas (last 400) and `max_items`, and gets JSON back (`VOCAB_SCHEMA`).
4. `store_candidates`:
   - `clean_lemma` strips articles and Swedish infinitive "att"
   - dedupes against **all** existing vocab (any status, including `ignored`)
   - drops `reason=new` single words below `vocab.min_zipf` (wordfreq)
   - ranks by reason priority (mistake < asked < unit < new), then by frequency
   - caps the list at `vocab.max_cards_per_session`
   - inserts the words as `candidate`.
5. If `anki.auto_add` is on and AnkiConnect is reachable, the candidates become `learning` and go through `push_to_anki`, and the result is stored as `analysis.anki_auto`. Otherwise `anki_auto={queued:n}`.
6. The frontend calls `/api/anki/push-pending` once per page load when Anki is up and `auto_add` is on. `push_pending` sends `learning` words without a note id, plus `candidate` extracted words if `auto_add` is on.

### Anki (`anki.py`, `core.push_to_anki`, `core.sync_anki`)
- **Cards:** the "Parlera Vocab" note type has fields `Word, Translation, Forms, Gender, POS, Example, ExampleTranslation, WordAudio, ExampleAudio, Notes, Language, Reverse, ParleraID`. `ensure_model` adds missing fields to an existing note type. There are two templates: Recognition, and Production (only generated when `Reverse` is non-empty). Gender colour classes are `g-en`, `g-ett`, `g-m`, `g-f`.
- **Decks:** the deck comes from `settings.anki.decks[lang]`, falling back to `deck_root::Language`. With `deck_per_unit`, a unit sub-deck `::A1 Title` is appended. Duplicates are checked per deck; if the note already exists, `findNotes` links the existing one.
- **Audio:** generated only when the TTS engine is server-side (`macos`/`piper`). Files are named `parlera_<lang>_<id>_w.wav` and `parlera_<lang>_<id>_e.wav` and stored via `storeMediaFile`.
- **Sync back:** `notesInfo` → `cardsInfo`. For each note we take the max interval and the summed lapses and reps. Interval ≥ 21 days marks the word `known`.
- **Removing:** bulk action `unanki` deletes the notes from Anki and sets the words to `ignored`.
- **Importing a deck** (`core.import_anki_deck`, `GET /api/anki/deck-preview?deck=`, `POST /api/anki/import`):
  - Reads the notes of any deck (`findNotes` "deck:X" → `notesInfo`) and strips HTML and `[sound:]` tags (`anki.strip_html`).
  - Maps the chosen word/meaning/example fields and inserts the words as `learning` with `source=anki`, `reason=imported` and the note id linked.
  - `created_at` comes from the note id, which is the creation time in milliseconds.
  - Existing words get linked rather than duplicated. Review stats are synced afterwards.
  - Nothing in Anki is modified.

## 7. Pronunciation feedback (honest limits)

The LLM only sees text. `pronunciation.analyse` combines two signals:

1. Words with Whisper probability below `stt.confidence_threshold` (0.55).
2. A repetition diff. The learner's utterance is compared with each **bold** phrase in the last tutor message. If the best match has a ratio ≥ 0.5, the differing words are reported, e.g. expected `jag` → heard `ja`.

The result becomes `meta.pron_note`, a bracketed hint appended to the LLM copy of the user message.
`tutor_base.md` tells the tutor to give one tip and never to mention the hint.

In the UI, the flagged words get a `.unsure` dotted underline (`session.js` → `userHtml`), and the
analysis prompt turns them into `pronunciation` errors.

**Possible upgrades:**
- Phoneme-level scoring (GOP): a wav2vec2 phoneme CTC model aligned against espeak-ng phonemes (Piper ships espeak data).
- An audio-capable LLM, once Ollama supports one well.
- KB-Whisper for Swedish (`stt.models.sv`, faster-whisper backend).

## 8. Settings keys (config.DEFAULT_SETTINGS)

| Section | Keys |
|---|---|
| `ui` | `language` (sv\|fr\|en, the currently studied language), `theme` (auto\|light\|dark) |
| `app` | `auto_quit` (true), `idle_quit_minutes` (30), `quit_ollama` (if_started\|always\|never), `window` (auto\|app\|browser), `offline` (auto\|always) |
| `workshop` | `interval_days` (7), `min_mistakes` (3), `thinking` (true) |
| `teachers` | `{sv,fr,en}.{name, gender female\|male}` (defaults Astrid/f, Élodie/f, Oliver/m) |
| `learner` | `name`, `native_language` ("English"), `goals.{sv,fr}` |
| `practice` | `round_length` (10), `lecture_thinking` (true) |
| `llm` | `base_url`, `model`, `analysis_model` ("" = same), `temperature`, `num_ctx` (16384), `keep_alive` ("30m"), `disable_thinking` (sends `think:false`, retried without it on a 400), `context_messages` (40), `exclusive_models` (true), `big_model_gb` (6) |
| `stt` | `backend` (auto\|mlx\|faster\|off), `model` (mlx-community/whisper-large-v3-turbo), `models.{fr,sv}` overrides, `default_input_language` (target\|en\|auto), `pronunciation_hints`, `confidence_threshold` |
| `tts` | `engine` (auto\|macos\|piper\|kokoro\|browser\|off; auto = macos > piper > browser), `engines.{fr,sv,en}` per-language override, `speed`, `beginner_slowdown`, `speak_corrections`, `voices.{macos,piper,kokoro,browser}.{fr,sv,en}` ("" = auto-pick matching the teacher's gender) |
| `conversation` | `input_mode` (handsfree\|ptt\|text), `silence_ms` (1400), `barge_in`, `immersion`, `show_text` |
| `anki` | `url`, `decks.{sv,fr,en}`, `auto_add`, `deck_per_unit`, `add_reverse`, `include_audio`, `auto_sync` (sync review data when a session is created) |
| `vocab` | `max_cards_per_session` (15), `min_zipf` (2.0), `reinforce` (true), `reinforce_count` (6) |
| `curriculum` | `advance_threshold` (0.75), `auto_advance` |

**Adding a setting:**
1. Add it to `DEFAULT_SETTINGS`. The deep merge means existing users get it automatically.
2. Add a control in `static/js/views/settings.js` using the helpers `text`, `select`, `check`, `range` and `section`. Paths are dotted, and changes autosave after a 400 ms debounce through `PUT /api/settings` (deep-merged patch).

## 9. REST API (main.py)

**Status, settings, learner, curriculum**
- `GET /api/status` returns Ollama models/installed, STT, TTS, Anki, `MODES`, `LANGUAGES`, data dir.
- `GET|PUT /api/settings`, `GET /api/models`
- `GET /api/dashboard/{lang}`
- `PUT /api/learner/{lang}` with `{current_unit_id, complete_previous, notes}`; `POST /api/learner/{lang}/advance`
- `GET /api/curriculum/{lang}`
- `GET|PUT /api/curriculum/{lang}/raw`, `POST …/validate`, `POST …/reset`
- `POST /api/curriculum/{lang}/units/{id}` with `{action: set_current|completed|active|reset}`

**Prompts**
- `GET /api/prompts`
- `GET|PUT /api/prompts/{name}`: PUT validates the Jinja syntax.
- `POST /api/prompts/{name}/reset`
- `POST /api/prompts-preview` with `{language, mode, unit_id?, …}`

**Sessions**
- `POST|GET /api/sessions`
- `GET|PATCH|DELETE /api/sessions/{id}`
- `POST /api/sessions/{id}/end`
- `GET /api/sessions/{id}/export.md`
- `DELETE /api/messages/{id}`

**Vocabulary and Anki**
- `GET|POST /api/vocab`, `POST /api/vocab/autofill`
- `PATCH|DELETE /api/vocab/{id}`
- `POST /api/vocab/bulk` with `{ids, action: accept|anki|ignore|known|unanki|delete}`
- `POST /api/vocab/export.apkg` with `{ids | language}`; `GET /api/vocab/export.csv`
- `POST /api/anki/sync`, `POST /api/anki/push-pending`, `GET /api/anki/decks`, `GET /api/anki/test`
- `GET /api/anki/deck-preview?deck=`, `POST /api/anki/import` with `{language, deck, word_field, meaning_field, example_field}`

**Memories and errors:** `GET|POST /api/memories`, `PATCH|DELETE /api/memories/{id}`, `GET /api/errors?language=`, `PATCH|DELETE /api/errors/{id}`

**Speech**
- `POST /api/stt` (multipart)
- `POST /api/speak` with `{text, language, slow, mixed, lang, rate}`; returns `audio/wav`
- `POST /api/segments`
- `GET /api/tts/voices?engine=`, `GET /api/tts/piper/catalog`, `POST /api/tts/piper/download`, `POST /api/tts/test`
- `POST /api/translate` with `{text, language, direction: to_native|to_target}`

**Backup:** `GET /api/backup`, `POST /api/restore`

**App lifecycle:** `POST /api/heartbeat`, `POST /api/bye`, `POST /api/shutdown`

**Demo:** `POST /api/demo/start` with `{mode: copy|fresh, open_window}`

**System:** `GET /api/system`, `POST /api/cache/clear`, `GET /api/settings/export`, `POST /api/settings/import`

**Practice & lectures:**
- `GET /api/practice/{lang}` (stats, grammar topics, lectures, counts, round_length), `GET /api/practice/{lang}/items?source=&count=`, `POST /api/practice/{lang}/results` with `{game, source, seconds, results:[{term, meaning, vocab_id, correct}]}`
- `GET /api/lectures?language=`, `POST /api/lectures` with `{language, topic, unit_id?}`, `GET|DELETE /api/lectures/{id}`, `POST /api/lectures/{id}/ask` with `{question}`
- `POST /api/tts/test` accepts `speaker`; `/api/speak` passes its `language` as speaker.

**Workshop & teacher notes:**
- `GET /api/workshops/status/{lang}`, `POST /api/workshops` with `{language}` (returns the new session)
- `POST /api/teacher-note/parse` with `{language, text}`
- `POST|GET /api/directives`, `PATCH|DELETE /api/directives/{id}`
- `GET /api/tts/engines`

**Errors:** `ValueError` and `CurriculumError` map to 400, `LLMError` and `AnkiError` to 502, `TTSError` to 500. The body is `{detail}`.

## 10. Prompts (`defaults/prompts`, Jinja2 with ChainableUndefined, trim_blocks)

**Teacher**
- `tutor_base`: core rules. Short spoken turns, one question at a time, ~immersion% target language, **bold every target-language word** (the TTS router depends on this), ✏️ corrections, English corrections ("✏️ English: …"), how to handle pronunciation hints.
- `persona_sv` (Astrid, Stockholm/Umeå, SFI teacher), `persona_fr` (Élodie, Lyon, FLE/DELF) and `persona_en` (Oliver, Edinburgh/London, former IELTS examiner).
- Language-specific branches use `{% if monolingual %}` (English course) or `language == "sv"/"fr"/"en"`. The English course gets no "Mixing languages" section, stricter corrections and "✏️ Upgrade:" lines; its analysis adds `upgrade` errors.
- `context`: learner and unit block.

**Teaching design (keep it when editing prompts):** Nation's four strands (input, output, language focus, fluency); learner talks most; chunks before rules for beginners; retrieval ("make them remember") and recycling 2–3 turns later; concept-check questions instead of "do you understand?"; a spoken activity toolbox; the **feedback ladder** — prompt/elicit first (repetition with rising tone, metalinguistic clue, clarification) for known forms, then ✏️ explicit correction, quiet recasts for off-focus slips, delayed feedback during tasks (Lyster & Ranta; Lyster & Saito meta-analysis: prompts > recasts). `mode_lesson`: A1/A2 = recall → input → chunks → noticing → controlled practice → task → feedback + 3-question exit quiz; B1+ and English = task first → teach the gaps → focused practice → task again with a twist → feedback + exit quiz (Willis TBLT). `mode_roleplay` = pre-task → task (no form focus) → post-task reformulations → replay. `mode_review` = scored quiz rounds, interleaved, missed items brought back.

**Session modes** (`mode_*`): `lesson`, `conversation`, `roleplay`, `review`, `exam`, `writing`, `placement`, `free`, `pronunciation`, `workshop` (created via `POST /api/workshops`, not the start dialog), `break`.
**Other prompts:** `analysis_workshop` (digest JSON, thinking), `teacher_note` (note → instructions JSON), `lecture_grammar` (lecture JSON, thinking), `lecture_followup` (plain text).

**Flow:** `opening` and `resume` are hidden user messages.

**Analysis:** `analysis_session` and `analysis_vocab` return JSON constrained by the schemas in `core.py`. `translate` and `vocab_autofill` are utilities.

**Adding a mode:**
1. Add it to `MODES` in `prompts.py`, with `unit: bool` and an `icon` name from `ui.js` `P`.
2. Add it to `PROMPT_INFO`.
3. Create `defaults/prompts/mode_x.md`.
4. Add it to `MODE_ORDER` in `views/start.js`, and to the `MODE_ICON`/`MODE_LABEL` maps in `session.js`, `history.js` and `dashboard.js`.
5. If unit mastery should count for it, add it to `UNIT_MODES` in `core.py`.

**Shipping prompt changes:** unedited user copies upgrade automatically (§4), but **only if you run `tools/update_default_hashes.py` before committing**. Copies the user edited keep their version; tell the user to press "Reset" if they want the new one.

## 11. Curriculum YAML format

Top level: `language`, `name`, `native_name`, `description`, `exams[]` (`{id, name, levels, description}`) and `levels[]`.

Each level has `code`, `title`, `description`, `exam` (`{name, format, scoring}`) and `units[]`.

Each unit has:
- `id` and `title` (required). Ids must stay stable: progress is keyed by id.
- `topic`, `can_do[]`, `grammar[]`
- `vocabulary[]` as `"term = meaning"`, with nouns written with en/ett or le/la
- `phrases[]` as `"phrase = meaning"`
- `pronunciation`, `culture`, `scenarios[]`
- `min_sessions` (default 2 at A1/A2, otherwise 1)

Optional top level: `start_unit` (where a new learner starts; used by `Curricula.first_unit`). Exams may carry a
`format` text; `mode_exam` lists all of a language's exam formats, so the learner can name IELTS/TOEFL/DET.

**Unit ids:** `sv-a1-01` … `sv-b2-05`, `fr-a1-01` … `fr-b2-05` and `en-b2-01` … `en-c2-05`.

The `exam.format` text is inserted into `mode_exam`. The same caveat about user copies applies (Reset in the Curriculum page).

## 12. Frontend conventions

- **Languages in the UI:** `LANGS` and `GENDERS` in `api.js` (`GENDERS.en = []` hides gender fields). Adding a language means updating `config.LANGUAGES`, `LANGS`, the CSS accent, the settings goal/deck/STT fields, `anki.LANG_NAMES`, `ARTICLES` in `core.py`, and adding a persona and curriculum.
- **No framework, no build.** Use `h(tag, attrs, ...children)` from `ui.js`. Style objects support CSS variables (`{ '--steps': 3 }`). **Always use `mount(el, ...children)` instead of `el.replaceChildren(...)`**: `replaceChildren` turns `null` into the text "null". `h`/`mount` skip null, false and undefined.
- **Views:** each view is `export default async function view(main, params)` and may return a cleanup function. Routes are defined in `app.js` `ROUTES` (hash router, `#/session/12`).
- **Imports:** put shared helpers in `nav.js`, not `app.js`, to avoid import cycles.
- **Theming:** CSS custom properties on `:root`. `data-lang` (sv|fr|en) sets the accent colour (English uses a red accent), and `data-theme` covers dark mode alongside `prefers-color-scheme`. Classes:
  - `.tl`: a target-language word (clickable, opens a popover to listen or add a card)
  - `.correction`: a ✏️ line
  - `.unsure`: a pronunciation flag
  - `.word-g-{en,ett,m,f}`: gender colours
- **Session view state machine** (`session.js`):
  - Phases: idle, recording, transcribing, thinking, speaking.
  - `awaitingReply` combined with `player.busy` pauses the recorder (barge-in raises the voice threshold instead).
  - The start gate (one click) is required to unlock autoplay and the mic.
  - Empty sessions are deleted on teardown.
- **Recorder** (`audio.js`):
  - Voice detection uses an adaptive noise floor. The threshold is max(0.012, 3 × floor); speech starts after ~90 ms above it and ends after `silence_ms` of quiet.
  - It keeps 300 ms of pre-roll and caps utterances at 60 s (90 s in push-to-talk).
  - Audio is downsampled to 16 kHz and encoded as a 16-bit mono WAV.
- **Player** (`audio.js`):
  - The queue holds WAV buffers (decoded with WebAudio) or speechSynthesis segments.
  - Each speech segment has a safety timeout in case `onend` never fires.
  - `openStream`/`endStream` signal when a turn's audio is complete.

## 13. Gotchas & decisions

- The **bold convention** carries the voice routing. If you change the prompt, keep it or update `textproc.segment_languages`.
- `SentenceStream` merges very short sentences (< 8 characters) into the next one on purpose, to avoid choppy TTS.
- **Whisper:** known hallucinations on silence ("Tack för att du tittade", "Sous-titrage…") are filtered in `stt.clean_transcript`. Audio with RMS < 0.003 or shorter than 0.25 s is ignored.
- **macOS voices:** parsed from `say -v ?`. Names may contain parentheses, e.g. "Alva (Premium)", and novelty voices are excluded. French Premium voices may have different names (the user noticed this). The dropdown lists **all** `fr_*` voices, and auto-pick prefers Premium, then Enhanced, then the `fr_FR` locale.
- **Analysis cost:** two non-streamed LLM calls; with a 27B model this takes 30–90 s. The UI shows an overlay.
- **Reasoning models:** `<think>` blocks are stripped from both streamed and JSON output.
- **Memory on quit:** on server shutdown the model is unloaded (`keep_alive: 0`), and `run.sh` quits Ollama only if it started it.
- **Settings** is a single JSON file; the frontend patches nested keys. Because `Settings.update` writes the whole merged dict, **changing a default doesn't reach existing users**; rename the key instead (as done with `app.auto_quit_minutes` → `app.idle_quit_minutes`).
- **Browser cache / blank screen (fixed):** Safari reused stale cached JS after updates and mixed it with new modules, which left the app blank.
  - `GET /` now rewrites `index.html` to load `/static/v-<build>/js/app.js` and `/static/v-<build>/css/app.css`. `build` is a SHA-1 over the static files (`main.static_build_id`), and relative module imports stay inside that folder.
  - Responses are `immutable` for the current build and `no-cache` otherwise; unversioned `/static/*` is always `no-cache`; `/` is `no-store`.
  - An inline classic script in `index.html` shows a "didn't start properly" box with the collected errors if `window.__parleraBooted` isn't set within 12 s.
  - Use absolute `/static/...` URLs only for non-module assets (favicon, worklet).
- **Kokoro** (`tts._kokoro_synth`): `KPipeline(lang_code=voice[0])` (a/b English, f French via espeak-ng), output 24 kHz, and torch tensors are moved to the CPU. **Kokoro/misaki require Python < 3.13**, so `setup.sh` prefers 3.12, uses `uv` to fetch 3.12 when Kokoro is chosen, rebuilds `.venv` if its Python version differs, and installs `espeak-ng` via brew. The extra is `kokoro`. The model downloads from HF on first use (blocked in cloud sessions, so it's untested here). The tutor uses server audio only if both the target language and English are on server engines (`tts.server_side((target, "en"))`).
- **Licensing:** piper-tts ≥ 1.3 is GPL (fine for personal use). Everything else is MIT/BSD/Apache.

## 14. Ideas / backlog (not done)

- Phoneme-level pronunciation scoring (see §7).
- Listening and reading exercises for the other DELF/Swedex skills.
- Unit sub-deck renaming, a field mapping to the user's own Anki note types.
- Spaced review of past units, streak reminders.
- AI-generated exercise sets in Practice (beyond the local games and lecture quizzes); listening dictation game using TTS.
- Updating users' prompt/curriculum copies on upgrade (e.g. offer a diff/merge when defaults change).
