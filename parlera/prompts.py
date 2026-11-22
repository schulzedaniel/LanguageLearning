"""Editable prompt templates (Markdown + Jinja2) stored in the data dir."""
from __future__ import annotations

import shutil
from pathlib import Path

import jinja2

from .config import DEFAULTS_DIR

# name -> (group, title, description)
PROMPT_INFO: dict[str, tuple[str, str, str]] = {
    "tutor_base": ("Teacher", "Core teaching rules",
                   "How the tutor behaves in every session: turn length, language mixing, corrections, bold marking for the voice engine."),
    "persona_sv": ("Teacher", "Swedish teacher persona",
                   "Who your Swedish teacher is (name, background, accent) and Swedish-specific teaching notes."),
    "persona_fr": ("Teacher", "French teacher persona",
                   "Who your French teacher is (name, background, accent) and French-specific teaching notes."),
    "context": ("Teacher", "Learner & unit context",
                "Injected into every session: learner profile, memories, current unit, previous sessions, weak words, recurring mistakes."),
    "mode_lesson": ("Session modes", "Guided lesson", "Structured lesson on the current curriculum unit."),
    "mode_conversation": ("Session modes", "Conversation practice", "Natural conversation around the unit topic."),
    "mode_roleplay": ("Session modes", "Role-play", "The tutor plays a character in a real-life scenario."),
    "mode_review": ("Session modes", "Review", "Drills your weak words and recurring mistakes."),
    "mode_exam": ("Session modes", "Exam simulation", "Simulates the oral exam (DELF / Swedex style) for your level and scores you."),
    "mode_writing": ("Session modes", "Writing practice", "Exam-style writing tasks with corrections."),
    "mode_pronunciation": ("Session modes", "Pronunciation", "Repeat-after-me practice using speech-recognition hints."),
    "mode_placement": ("Session modes", "Placement check", "Short diagnostic conversation to find your starting unit."),
    "mode_free": ("Session modes", "Free talk", "Talk about anything, at your level."),
    "opening": ("Session flow", "Session opening", "Hidden instruction sent when a new session starts (the tutor speaks first)."),
    "resume": ("Session flow", "Session resume", "Hidden instruction sent when you come back to an unfinished session."),
    "analysis_session": ("Analysis", "Session analysis",
                         "After a session: summary, feedback, mistakes, memories, unit mastery, exam score (JSON)."),
    "analysis_vocab": ("Analysis", "Vocabulary extraction", "After a session: picks the words worth turning into Anki cards (JSON)."),
    "translate": ("Utilities", "Translate", "Used by the Translate and 'How do I say…?' buttons."),
    "vocab_autofill": ("Utilities", "Vocabulary autofill", "Fills in translation, gender, forms and an example when you add a word manually."),
}

MODES = {
    "lesson": {"title": "Guided lesson", "icon": "school", "unit": True,
               "description": "Learn the current unit step by step: new words, grammar, then practice."},
    "conversation": {"title": "Conversation", "icon": "chat", "unit": True,
                     "description": "Chat naturally about the unit topic and your life, with gentle corrections."},
    "roleplay": {"title": "Role-play", "icon": "theater", "unit": True,
                 "description": "Act out a real-life situation: café, shop, doctor, job interview…"},
    "review": {"title": "Review", "icon": "refresh", "unit": True,
               "description": "Drill your weak words and recurring mistakes."},
    "exam": {"title": "Exam practice", "icon": "award", "unit": False,
             "description": "Simulated oral exam (DELF / Swedex style) for your level, with a score."},
    "writing": {"title": "Writing", "icon": "pen", "unit": True,
                "description": "Exam-style writing tasks with detailed corrections (text only)."},
    "pronunciation": {"title": "Pronunciation", "icon": "wave", "unit": True,
                      "description": "Repeat-after-me practice: the app flags words that didn't sound right."},
    "placement": {"title": "Placement check", "icon": "compass", "unit": False,
                  "description": "A short diagnostic chat to find where you should start."},
    "free": {"title": "Free talk", "icon": "sparkle", "unit": False,
             "description": "Talk about anything you like, at your level."},
}


class PromptStore:
    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.defaults = DEFAULTS_DIR / "prompts"
        self.env = jinja2.Environment(
            loader=jinja2.FileSystemLoader([str(self.dir), str(self.defaults)]),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=False,
            undefined=jinja2.ChainableUndefined,
        )

    def names(self) -> list[str]:
        found = {p.stem for p in self.defaults.glob("*.md")} | {p.stem for p in self.dir.glob("*.md")}
        order = list(PROMPT_INFO)
        return sorted(found, key=lambda n: (order.index(n) if n in order else 999, n))

    def _file(self, name: str) -> Path:
        if not name.replace("_", "").isalnum():
            raise ValueError("Invalid prompt name")
        return self.dir / f"{name}.md"

    def read(self, name: str) -> str:
        f = self._file(name)
        if f.exists():
            return f.read_text(encoding="utf-8")
        d = self.defaults / f"{name}.md"
        if d.exists():
            return d.read_text(encoding="utf-8")
        raise FileNotFoundError(name)

    def default(self, name: str) -> str | None:
        d = self.defaults / f"{name}.md"
        return d.read_text(encoding="utf-8") if d.exists() else None

    def write(self, name: str, text: str) -> None:
        # Validate template syntax before saving.
        try:
            self.env.parse(text)
        except jinja2.TemplateSyntaxError as e:
            raise ValueError(f"Template error on line {e.lineno}: {e.message}") from e
        f = self._file(name)
        f.write_text(text, encoding="utf-8")

    def reset(self, name: str) -> None:
        d = self.defaults / f"{name}.md"
        if not d.exists():
            raise FileNotFoundError(name)
        shutil.copy2(d, self._file(name))

    def info(self, name: str) -> dict:
        group, title, desc = PROMPT_INFO.get(name, ("Custom", name, ""))
        current = self.read(name)
        default = self.default(name)
        return {"name": name, "group": group, "title": title, "description": desc,
                "modified": default is not None and current.strip() != default.strip(),
                "has_default": default is not None}

    def render(self, name: str, **ctx) -> str:
        # Re-read every time so edits apply immediately.
        source = self.read(name)
        return self.env.from_string(source).render(**ctx).strip()
