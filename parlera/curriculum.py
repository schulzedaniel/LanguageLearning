"""Curriculum loading/validation. Curricula are editable YAML files in the data dir."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

LEVEL_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]


class CurriculumError(ValueError):
    pass


def _split_pair(item: Any) -> dict:
    """'hej = hello' -> {'term': 'hej', 'meaning': 'hello'}"""
    if isinstance(item, dict):
        return {"term": str(item.get("term", "")), "meaning": str(item.get("meaning", ""))}
    s = str(item)
    if " = " in s:
        a, b = s.split(" = ", 1)
        return {"term": a.strip(), "meaning": b.strip()}
    return {"term": s.strip(), "meaning": ""}


def validate(data: Any) -> dict:
    if not isinstance(data, dict):
        raise CurriculumError("The curriculum must be a YAML mapping (key: value pairs) at the top level.")
    for key in ("language", "levels"):
        if key not in data:
            raise CurriculumError(f"Missing top-level key '{key}'.")
    if not isinstance(data["levels"], list) or not data["levels"]:
        raise CurriculumError("'levels' must be a non-empty list.")
    seen: set[str] = set()
    for li, level in enumerate(data["levels"]):
        if not isinstance(level, dict) or "code" not in level:
            raise CurriculumError(f"Level #{li + 1} needs a 'code' (e.g. A1).")
        units = level.get("units") or []
        if not isinstance(units, list):
            raise CurriculumError(f"Level {level['code']}: 'units' must be a list.")
        for ui, unit in enumerate(units):
            if not isinstance(unit, dict):
                raise CurriculumError(f"Level {level['code']} unit #{ui + 1} must be a mapping.")
            for key in ("id", "title"):
                if not unit.get(key):
                    raise CurriculumError(f"Level {level['code']} unit #{ui + 1} is missing '{key}'.")
            if unit["id"] in seen:
                raise CurriculumError(f"Duplicate unit id '{unit['id']}'.")
            seen.add(unit["id"])
            for key in ("can_do", "grammar", "vocabulary", "phrases", "scenarios"):
                if key in unit and unit[key] is not None and not isinstance(unit[key], list):
                    raise CurriculumError(f"Unit {unit['id']}: '{key}' must be a list.")
    if not seen:
        raise CurriculumError("The curriculum has no units.")
    return data


def normalize(data: dict) -> dict:
    """Add derived fields used by the app (flat unit list, parsed vocab)."""
    units: list[dict] = []
    for level in data["levels"]:
        level.setdefault("title", "")
        level.setdefault("description", "")
        level.setdefault("exam", {})
        level["units"] = level.get("units") or []
        for unit in level["units"]:
            unit["level"] = level["code"]
            for key in ("can_do", "grammar", "vocabulary", "phrases", "scenarios"):
                unit[key] = [x for x in (unit.get(key) or []) if x is not None]
            unit.setdefault("topic", "")
            unit.setdefault("pronunciation", "")
            unit.setdefault("culture", "")
            unit.setdefault("min_sessions", 2 if level["code"] in ("A1", "A2") else 1)
            unit["vocab_pairs"] = [_split_pair(v) for v in unit["vocabulary"]]
            unit["phrase_pairs"] = [_split_pair(p) for p in unit["phrases"]]
            unit["index"] = len(units)
            units.append(unit)
    data["units"] = units
    data.setdefault("exams", [])
    data.setdefault("name", data["language"])
    return data


class Curricula:
    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self._cache: dict[str, tuple[float, dict]] = {}

    def path(self, language: str) -> Path:
        return self.dir / f"{language}.yaml"

    def get(self, language: str) -> dict:
        p = self.path(language)
        if not p.exists():
            raise CurriculumError(f"No curriculum file for '{language}' at {p}")
        mtime = p.stat().st_mtime
        cached = self._cache.get(language)
        if cached and cached[0] == mtime:
            return cached[1]
        data = normalize(validate(yaml.safe_load(p.read_text(encoding="utf-8"))))
        self._cache[language] = (mtime, data)
        return data

    def raw(self, language: str) -> str:
        return self.path(language).read_text(encoding="utf-8")

    def save_raw(self, language: str, text: str) -> dict:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as e:
            raise CurriculumError(f"YAML syntax error: {e}") from e
        validate(data)
        p = self.path(language)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(p)
        self._cache.pop(language, None)
        return self.get(language)

    # -- lookups ---------------------------------------------------------
    def unit(self, language: str, unit_id: str | None) -> dict | None:
        if not unit_id:
            return None
        return next((u for u in self.get(language)["units"] if u["id"] == unit_id), None)

    def first_unit(self, language: str) -> dict:
        return self.get(language)["units"][0]

    def next_unit(self, language: str, unit_id: str) -> dict | None:
        units = self.get(language)["units"]
        for i, u in enumerate(units):
            if u["id"] == unit_id and i + 1 < len(units):
                return units[i + 1]
        return None

    def level(self, language: str, code: str) -> dict | None:
        return next((lv for lv in self.get(language)["levels"] if lv["code"] == code), None)
