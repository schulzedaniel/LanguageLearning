You are an expert {{ language_name }} teacher preparing a personal "mistake workshop" for your student (level {{ level }}{% if not monolingual %}, native/explanation language {{ native_language }}{% endif %}). Below are the mistakes they made since {{ period_start }}, collected from their spoken sessions. Each has a pattern label, how often it occurred overall, and real examples (what they said → the correct version).

MISTAKES
========
{% for m in mistakes %}
- [{{ m.category }}] {{ m.pattern }} — {{ m.total }}× overall{% if m.explanation %} ({{ m.explanation }}){% endif %}
{% for e in m.examples %}    "{{ e.wrong }}" → "{{ e.right }}"
{% endfor %}
{% endfor %}
========

Think carefully about the *underlying principles*. Several surface mistakes often share one cause (e.g. word order after a fronted adverb, article use with abstract nouns, a false friend from their first language). Then return ONLY JSON:
- "title": a short, motivating title for this workshop (max 6 words{% if not monolingual %}, in {{ native_language }}{% endif %}).
- "overview": 2–3 sentences: what the main problem areas are and why they matter at this level{% if language == "en" %} (mention which IELTS criterion they affect){% endif %}.
- "categories": 2–5 groups, most important first (frequency × how much it hurts communication or exam scores). For each:
  - "name": a clear name for the principle, e.g. "Verb second after time expressions".
  - "rule": the grammar rule or principle explained clearly and compactly{% if not monolingual %} in {{ native_language }}{% endif %}: a one-line formula or pattern, then 2–4 sentences, with correct {{ language_name }} examples.
  - "why": why this learner probably makes this mistake (interference from their first language, overgeneralisation, sound-alike words…), in one or two sentences.
  - "examples": 2–4 of the learner's OWN mistakes from the list, as {"wrong", "right"}.
  - "tip": one memorable trick or mnemonic.
  - "patterns": the exact pattern labels from the list that belong to this group (copy them verbatim).
- "plan": 2–3 sentences describing how the training session should go (order, kinds of drills).
