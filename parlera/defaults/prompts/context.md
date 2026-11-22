## About the learner
- Name: {{ learner_name or "not known yet (ask naturally if it fits)" }}
- Native language: {{ native_language }}
- Current level: **{{ level }}** — unit {{ unit_number }} of {{ units_total }} in the curriculum
{% if learner_goal %}- Goal: {{ learner_goal }}
{% endif %}
{% if learner_notes %}- Notes: {{ learner_notes }}
{% endif %}
{% if memories %}- Things you know about them (use naturally, don't recite):
{% for m in memories %}  - {{ m }}
{% endfor %}
{% endif %}

{% if unit.id %}
## Current unit: {{ unit.title }} ({{ unit.level }})
{% if unit.topic %}{{ unit.topic }}
{% endif %}
{% if unit.can_do %}By the end of this unit the learner can:
{% for g in unit.can_do %}- {{ g }}
{% endfor %}
{% endif %}
{% if unit.grammar %}Grammar:
{% for g in unit.grammar %}- {{ g }}
{% endfor %}
{% endif %}
{% if unit.vocabulary %}Key vocabulary: {{ unit.vocabulary | join("; ") }}
{% endif %}
{% if unit.phrases %}Useful phrases: {{ unit.phrases | join("; ") }}
{% endif %}
{% if unit.pronunciation %}Pronunciation focus: {{ unit.pronunciation }}
{% endif %}
{% if unit.culture %}Culture note: {{ unit.culture }}
{% endif %}
Progress on this unit: {{ unit_progress.sessions }} previous session(s), estimated mastery {{ (unit_progress.mastery * 100) | round | int }}%.
{% endif %}

{% if recent_summaries %}
## Previous sessions (most recent first)
{% for s in recent_summaries %}- {{ s.created_at[:10] }} — {{ s.title }}: {{ s.summary }}
{% endfor %}
{% endif %}
{% if weak_vocab %}
## Words the learner keeps forgetting (weave 2–4 of them in naturally)
{{ weak_vocab | join(", ") }}
{% endif %}
{% if recurring_errors %}
## Recurring mistakes to watch for
{% for e in recurring_errors %}- {{ e.pattern }}{% if e.example_wrong %} (e.g. "{{ e.example_wrong }}" → "{{ e.example_right }}"){% endif %} — seen {{ e.count }}×
{% endfor %}
{% endif %}
{% if focus %}
## The learner asked to focus on
{{ focus }}
{% endif %}
