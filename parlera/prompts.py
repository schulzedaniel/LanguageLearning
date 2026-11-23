"""Editable prompt templates (Markdown + Jinja2) stored in the data dir."""
from __future__ import annotations

import shutil
from pathlib import Path

import jinja2

from .config import DEFAULTS_DIR

# name -> (group, title, description)
PROMPT_INFO: dict[str, tuple[str, str, str]] = {
    "tutor_base": ("Teacher", "Core teaching rules",
                   "How the teacher behaves in every session: turn length, language mixing, teaching principles (four strands, retrieval, recycling), spoken activities, the correction ladder, bold marking for the voice engine."),
    "persona_sv": ("Teacher", "Swedish teacher persona",
                   "Who your Swedish teacher is (background, personality, accent) and what English speakers need in Swedish. Name and gender: Settings → Your teachers."),
    "persona_en": ("Teacher", "English coach persona",
                   "Who your English coach is (IELTS examiner background) and what advanced learners need. Name and gender: Settings → Your teachers."),
    "persona_fr": ("Teacher", "French teacher persona",
                   "Who your French teacher is (background, personality, accent) and what this learner needs in French. Name and gender: Settings → Your teachers."),
    "context": ("Teacher", "Learner & unit context",
                "Injected into every session: learner profile, memories, current unit, previous sessions, weak words, recurring mistakes."),
    "mode_lesson": ("Session modes", "Guided lesson", "Structured lesson: recall → input → chunks → noticing → practice → task → exit quiz (task-first from B1)."),
    "mode_conversation": ("Session modes", "Conversation practice", "Natural conversation around the unit topic."),
    "mode_roleplay": ("Session modes", "Role-play", "Prepare → play the scene → feedback → replay with a twist."),
    "mode_review": ("Session modes", "Review & quiz", "Quiz rounds with a score: weak words, recent words and recurring mistakes, mixed and spaced."),
    "mode_exam": ("Session modes", "Exam simulation", "Simulates the oral exam (DELF / Swedex style) for your level and scores you."),
    "mode_writing": ("Session modes", "Writing practice", "Exam-style writing tasks with corrections."),
    "mode_pronunciation": ("Session modes", "Pronunciation", "Repeat-after-me practice using speech-recognition hints."),
    "mode_workshop": ("Session modes", "Mistake workshop", "Guided training of your collected mistakes: principle, rule, then drills."),
    "mode_break": ("Session modes", "Fika / Pause café / Tea time", "Relaxed chat outside the curriculum."),
    "mode_placement": ("Session modes", "Placement check", "Short diagnostic conversation to find your starting unit."),
    "mode_free": ("Session modes", "Free talk", "Talk about anything, at your level."),
    "opening": ("Session flow", "Session opening", "Hidden instruction sent when a new session starts (the tutor speaks first)."),
    "resume": ("Session flow", "Session resume", "Hidden instruction sent when you come back to an unfinished session."),
    "analysis_session": ("Analysis", "Session analysis",
                         "After a session: summary, feedback, mistakes, memories, unit mastery, exam score (JSON)."),
    "analysis_workshop": ("Analysis", "Mistake summary (workshop)",
                          "Groups your recent mistakes into categories and explains the rules behind them (JSON)."),
    "analysis_vocab": ("Analysis", "Vocabulary extraction", "After a session: picks the words worth turning into Anki cards (JSON)."),
    "teacher_note": ("Utilities", "Message your teacher", "Turns a note you send outside sessions into instructions for the system prompt (JSON)."),
    "translate": ("Utilities", "Translate", "Used by the Translate and 'How do I say…?' buttons."),
    "lecture_grammar": ("Practice", "Grammar lecture",
                        "Practice → Grammar: writes a structured explanation of a grammar topic with examples and a quiz (JSON, may use thinking)."),
    "lecture_followup": ("Practice", "Grammar follow-up question", "Answers your follow-up questions about a grammar lecture."),
    "vocab_pick": ("Analysis", "Picked flashcards",
                   "Review page → Pick words from the transcript: fills in meaning, gender, forms and an example (JSON)."),
    "vocab_autofill": ("Utilities", "Vocabulary autofill", "Fills in translation, gender, forms and an example when you add a word manually."),
}

MODES = {
    "lesson": {"title": "Guided lesson", "icon": "school", "unit": True,
               "description": "Learn the current unit step by step: recall, new phrases, grammar, practice, a real task and a short quiz."},
    "conversation": {"title": "Conversation", "icon": "chat", "unit": True,
                     "description": "Chat naturally about the unit topic and your life, with gentle corrections."},
    "roleplay": {"title": "Role-play", "icon": "theater", "unit": True,
                 "description": "Act out a real-life situation: café, shop, doctor, job interview…"},
    "review": {"title": "Review & quiz", "icon": "refresh", "unit": True,
               "description": "Spoken quiz rounds with a score: your weak words, recent words and recurring mistakes."},
    "exam": {"title": "Exam practice", "icon": "award", "unit": False,
             "description": "Simulated oral exam (DELF / Swedex style) for your level, with a score."},
    "writing": {"title": "Writing", "icon": "pen", "unit": True,
                "description": "Exam-style writing tasks with detailed corrections (text only)."},
    "pronunciation": {"title": "Pronunciation", "icon": "wave", "unit": True,
                      "description": "Repeat-after-me practice: the app flags words that didn't sound right."},
    "workshop": {"title": "Mistake workshop", "icon": "target", "unit": False,
                 "description": "Your recent mistakes, grouped and explained — then trained step by step."},
    "break": {"title": "Chat break", "icon": "coffee", "unit": False,
              "description": "A relaxed chat — fika, pause café or tea time. No curriculum, no review needed."},
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
