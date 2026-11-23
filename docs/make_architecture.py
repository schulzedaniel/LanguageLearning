"""Generates docs/architecture.svg — the architecture & data-flow diagram shown in README.md.

    python3 docs/make_architecture.py            # writes docs/architecture.svg

Plain Python, no dependencies. Coordinates are hand-placed on a 1600x1340 canvas:
columns = You (x30) | Browser (x290) | Server (x670) | Local services (x1230); bottom band = folders.
"""
from html import escape
from pathlib import Path
import sys

W, H = 1600, 1340
BLUE, ORANGE, GRAY = "#1f5fbf", "#c2610c", "#6b7280"
out = []
def add(s): out.append(s)

def box(x, y, w, h, fill, stroke, r=12, sw=1.5, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')

def text(x, y, s, size=12.5, weight=400, color="#1f2937", anchor="start", italic=False, family=None):
    st = ' font-style="italic"' if italic else ""
    fam = f' font-family="{family}"' if family else ""
    add(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{color}" text-anchor="{anchor}"{st}{fam}>{escape(s)}</text>')

def lines(x, y, items, size=12.5, gap=17, color="#374151", weight=400):
    for i, s in enumerate(items):
        if isinstance(s, tuple):
            text(x, y + i * gap, s[0], size, s[1], color)
        else:
            text(x, y + i * gap, s, size, weight, color)

def num(cx, cy, n, color):
    add(f'<circle cx="{cx}" cy="{cy}" r="11" fill="{color}"/>')
    text(cx, cy + 4.5, str(n), 12, 700, "#fff", "middle")

def arrow(d, color, dash=None, both=False, sw=2):
    m = {"#1f5fbf": "b", "#c2610c": "o", "#6b7280": "g"}[color]
    da = f' stroke-dasharray="{dash}"' if dash else ""
    ms = f' marker-start="url(#s{m})"' if both else ""
    add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{sw}"{da} marker-end="url(#e{m})"{ms}/>')

def label(x, y, s, color, anchor="middle", size=11.5):
    # text with a white halo so it stays readable on top of lines
    add(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="600" fill="{color}" text-anchor="{anchor}" '
        f'stroke="#ffffff" stroke-width="4" paint-order="stroke">{escape(s)}</text>')

add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
    f'font-family="-apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, Helvetica, Arial, sans-serif">')
add('<defs>')
for k, c in (("b", BLUE), ("o", ORANGE), ("g", GRAY)):
    add(f'<marker id="e{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="{c}"/></marker>')
    add(f'<marker id="s{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="{c}"/></marker>')
add('</defs>')
add(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')

# ---------------- title ----------------
text(30, 44, "Parlera — architecture & data flow", 26, 750, "#111827")
text(30, 70, "Everything runs locally on your Mac. Blue = live conversation · Orange = after the session · Grey dashed = files on disk. Numbers show the order.", 14, 400, "#4b5563")

# ---------------- band labels ----------------


# ---------------- column A: You ----------------
box(30, 112, 220, 610, "#f8fafc", "#cbd5e1")
text(140, 138, "YOU", 14, 750, "#334155", "middle")
for (y, h, title, sub) in [
    (155, 60, "Microphone", "hands-free or push-to-talk"),
    (245, 56, "Keyboard", "typing, “How do I say…?”"),
    (370, 96, "Browser window", "http://127.0.0.1:8642"),
    (628, 60, "Headphones / speakers", "the tutor’s voice"),
]:
    box(46, y, 188, h, "#ffffff", "#cbd5e1", 10)
    text(140, y + 25, title, 13.5, 650, "#111827", "middle")
    text(140, y + 44, sub, 11.5, 400, "#64748b", "middle")
text(140, 448, "opened by run.sh / Parlera.app", 11, 400, "#64748b", "middle")

# ---------------- column B: Browser frontend ----------------
box(290, 112, 340, 610, "#eff6ff", "#93c5fd")
text(460, 138, "BROWSER — web interface", 14, 750, "#1e3a8a", "middle")
text(460, 156, "parlera/static/  (plain JavaScript, no build)", 11.5, 400, "#3b5b9a", "middle")
box(306, 168, 308, 72, "#ffffff", "#93c5fd", 10)
lines(320, 190, [("Recorder  (audio.js)", 650), "voice-activity detection → 16 kHz WAV", "sends each utterance when you pause"], 12)
box(306, 252, 308, 52, "#ffffff", "#93c5fd", 10)
lines(320, 274, [("Text box & buttons", 650), "replay · slow · translate · add card"], 12)
box(306, 330, 308, 190, "#ffffff", "#93c5fd", 10)
lines(320, 352, [("Pages  (views/*.js)", 650), "Home · Session · Review · Curriculum", "Vocabulary · Sessions · Memory", "Teacher prompts (editor + preview)", "Settings (model, voices, Anki decks…)", "", "talks to the server via", "REST /api/*  and  WebSocket"], 12)
box(306, 612, 308, 92, "#ffffff", "#93c5fd", 10)
lines(320, 634, [("Player  (audio.js)", 650), "plays the sentence audio in order", "(or browser voices as fallback)", "Esc / speaking interrupts the tutor"], 12)
# review page (post band)
box(290, 778, 340, 150, "#fff7ed", "#fdba74")
lines(306, 802, [("Review page", 700), "feedback & level estimate", "mistakes to learn from", "unit progress → “move on” button", "new flashcards (remove any with ×)", "what the tutor will remember"], 12)

# ---------------- column C: server ----------------
box(670, 84, 480, 968, "#f5f3ff", "#c4b5fd")
text(910, 106, "PARLERA SERVER — Python · FastAPI  (parlera/, in your program folder)", 13.5, 750, "#5b21b6", "middle")

steps_live = [
    (122, 52, 2, "Receive your turn", "tutor.py — audio or text over the WebSocket"),
    (186, 52, 3, "Transcribe speech", "stt.py → Whisper: text + confidence for each word"),
    (250, 52, 4, "Pronunciation hints", "pronunciation.py — unclear / misheard words"),
    (314, 88, 5, "Build the system prompt", "core.py: tutor_base + persona + your context + session"),
    (378, 0, 0, "", ""),
    (408, 52, 6, "Stream the tutor’s reply", "Ollama sends the answer word by word"),
    (472, 52, 7, "Split & route languages", "textproc.py — **bold** = target voice, rest = English"),
    (536, 52, 8, "Speak each sentence", "tts.py — French/Swedish + English voices (cached)"),
    (600, 52, 9, "Send audio + text back", "and save both messages in parlera.db"),
]
for (y, h, n, title, sub) in steps_live:
    if not n:
        continue
    box(726, y, 412, h, "#ffffff", "#a78bfa", 10)
    num(746, y + 20, n, BLUE)
    text(766, y + 24, title, 13.5, 650, "#111827")
    text(766, y + 42, sub, 11.5, 400, "#4b5563")
text(766, 380, "+ curriculum unit, memories, recent sessions,", 11.5, 400, "#4b5563")
text(766, 395, "  weak Anki words, recurring mistakes, history", 11.5, 400, "#4b5563")

steps_post = [
    (778, 10, "Analyse the session", "core.py → Ollama returns JSON (schema-checked)"),
    (842, 11, "Save what was learned", "mistakes, memories, unit mastery, exam score"),
    (906, 12, "Pick flashcards", "model ranks words; app drops known & rare ones"),
    (970, 13, "Sync with Anki", "anki.py — add cards with audio; read reviews back"),
]
for (y, n, title, sub) in steps_post:
    box(726, y, 412, 52, "#ffffff", "#fdba74", 10)
    num(746, y + 20, n, ORANGE)
    text(766, y + 24, title, 13.5, 650, "#111827")
    text(766, y + 42, sub, 11.5, 400, "#4b5563")

# ---------------- column D: local services ----------------
def service(y, h, title, items, fill="#ecfdf5", stroke="#6ee7b7"):
    box(1230, y, 340, h, fill, stroke)
    text(1246, y + 26, title, 14, 750, "#065f46")
    lines(1246, y + 48, items, 12, 17, "#1f2937")

service(140, 92, "Whisper  (speech → text)", ["mlx-whisper on Apple Silicon", "model: whisper-large-v3-turbo", "stored in ~/.cache/huggingface"])
service(268, 200, "Ollama  (the language model)", ["local server on port 11434", "e.g. gemma4:26b-mlx, qwen3, mistral", "models live in ~/.ollama/models —", "shared with your other Ollama apps,", "never downloaded twice", "started/quit by run.sh if needed;", "model unloaded when Parlera quits"])
service(492, 150, "Voices  (text → speech)", ["macOS “say” with Premium voices", "  (System Settings → Spoken Content)", "or Piper neural voices", "  (data folder/voices/)", "or browser voices (fallback)"])
service(842, 190, "Anki  +  AnkiConnect add-on", ["local API on port 8765", "deck per language, set in Settings", "  e.g. Parlera::Swedish (or your own)", "note type “Parlera Vocab”:", "  word, forms, example, audio", "AnkiWeb sync → your phone", "queued if Anki is closed"], "#ecfeff", "#67e8f9")

# ---------------- data folder ----------------
box(290, 1092, 1280, 220, "#fffbeb", "#fcd34d")
text(306, 1118, "YOUR DATA FOLDER", 14, 750, "#92400e")
text(600, 1118, "~/Parlera by default — chosen in setup.sh, remembered in parlera.env · backed up daily · one-click backup/restore", 12, 400, "#92400e")
data_boxes = [
    (306, 270, "parlera.db  (SQLite)", ["sessions & every message", "progress per unit (mastery)", "vocabulary + Anki links", "recurring mistakes · memories", "exam scores"]),
    (592, 250, "prompts/*.md", ["teacher’s instructions (editable)", "tutor_base · persona_sv / _fr", "context · mode_lesson, _exam …", "analysis_session · analysis_vocab", "→ edit in “Teacher prompts”"]),
    (858, 230, "curricula/*.yaml", ["sv.yaml · fr.yaml", "A1 → B2, 31 units each", "goals, grammar, words, phrases", "exam formats (DELF, Swedex)", "→ edit in “Curriculum”"]),
    (1104, 210, "settings.json", ["model, voices, speed", "Anki decks, auto-add", "immersion %, input mode", "pronunciation hints", "→ edit in “Settings”"]),
    (1330, 224, "backups/ · cache/ · voices/", ["daily copies of parlera.db", "cached speech audio", "Piper voice files", "", ""]),
]
for (x, w, title, items) in data_boxes:
    box(x, 1132, w, 164, "#ffffff", "#fcd34d", 10)
    text(x + 14, 1156, title, 13.5, 700, "#78350f")
    lines(x + 14, 1178, items, 12, 18, "#374151")

# ---------------- program folder ----------------
box(30, 1092, 240, 220, "#f9fafb", "#d1d5db")
text(46, 1118, "PROGRAM FOLDER", 14, 750, "#374151")
lines(46, 1140, ["e.g. ~/Library/Application", "Support/Parlera/app (git clone)", ("setup.sh · run.sh", 650), "Parlera.app in ~/Applications", ".venv/  Python packages", "parlera/  server code", "parlera/static/  web UI", "parlera/defaults/  prompts &", "  curricula (copied once)", "README.md · CLAUDE.md"], 11.5, 17, "#374151")

# ---------------- legend (left, post band) ----------------
box(30, 778, 240, 274, "#ffffff", "#e5e7eb")
text(46, 802, "HOW TO READ THIS", 12.5, 750, "#374151")
arrow("M46 826 H112", BLUE); text(122, 830, "live conversation", 12, 400, "#374151")
arrow("M46 852 H112", ORANGE); text(122, 856, "after the session", 12, 400, "#374151")
arrow("M46 878 H112", GRAY, "5 4"); text(122, 882, "reads / writes files", 12, 400, "#374151")
num(56, 908, 1, BLUE); text(76, 912, "order of steps", 12, 400, "#374151")
lines(46, 942, ["Nothing leaves your computer:", "all services listen only on", "127.0.0.1 (localhost).", "", "The tutor learns about you from", "steps 11–13 and uses it in step 5."], 11.5, 17, "#4b5563")

text(686, 690, "main.py serves the web pages, the REST /api/* used by all pages,", 11.5, 400, "#5b21b6")
text(686, 706, "and the WebSocket for the live conversation", 11.5, 400, "#5b21b6")
text(686, 756, "AFTER THE SESSION — you press “End & review”", 12, 750, ORANGE)
# ---------------- arrows: live loop ----------------
# 1 mic -> recorder
arrow("M234 185 H304", BLUE); num(268, 172, 1, BLUE)
# keyboard -> text box
arrow("M234 273 H304", BLUE)
# browser window <-> pages
arrow("M234 418 H304", GRAY, "5 4", both=True)
# recorder / text -> server (2)
arrow("M614 200 H650 V148 H724", BLUE); label(668, 140, "audio / text", BLUE)
add(f'<path d="M614 278 H650 V160" fill="none" stroke="{BLUE}" stroke-width="2"/>')
# pages <-> REST (grey)
arrow("M614 470 H668", GRAY, "5 4", both=True); label(641, 462, "REST", GRAY)
# 3 transcribe <-> whisper
arrow("M1138 212 H1228", BLUE, both=True); label(1183, 204, "WAV → text", BLUE)
# 5 prompt -> ollama, 6 ollama -> reply
arrow("M1138 345 H1228", BLUE); label(1183, 337, "prompt + chat", BLUE)
arrow("M1228 434 H1140", BLUE); label(1183, 426, "reply tokens", BLUE)
# 8 speak <-> voices
arrow("M1138 562 H1228", BLUE, both=True); label(1183, 554, "text → audio", BLUE)
# 9 -> player -> headphones
arrow("M724 626 H616", BLUE); label(670, 618, "audio + text", BLUE)
arrow("M306 658 H236", BLUE)
# unclear words are shown underlined in the chat (part of step 9's payload)
# data folder reads for step 5 (grey dashed, via channel x=1196)
arrow("M1196 1090 V392 H1140", GRAY, "5 4")
add('<text x="1210" y="760" font-size="11.5" font-weight="600" fill="#6b7280" transform="rotate(-90 1210 760)" text-anchor="middle" stroke="#ffffff" stroke-width="4" paint-order="stroke">reads prompts, curriculum, memories, mistakes, weak words</text>')

# ---------------- arrows: post-session ----------------
arrow("M630 804 H724", ORANGE); label(677, 796, "End & review", ORANGE)
# 10 analyse <-> ollama (route around right edge)
arrow("M1138 804 H1588 V420 H1572", ORANGE, both=True); label(1400, 796, "transcript → JSON", ORANGE)
# 11 save -> db (grey dashed, down the left channel)
arrow("M726 868 H656 V1078 H520 V1130", GRAY, "5 4"); label(600, 1072, "writes", GRAY)
# results back to review page
arrow("M726 932 H632", ORANGE); label(679, 924, "results", ORANGE)
# 13 sync <-> anki
arrow("M1138 990 H1228", ORANGE, both=True); label(1183, 982, "cards ⇄ reviews", ORANGE)
# defaults copied
arrow("M270 1260 H288", GRAY, "5 4")

add('</svg>')
target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("architecture.svg")
target.write_text("\n".join(out), encoding="utf-8")
print("written", target)
