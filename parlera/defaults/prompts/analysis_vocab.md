You are a {{ language_name }} teacher choosing flashcards for a learner at level {{ level }} (native language: {{ native_language }}) after a lesson. Pick the {{ language_name }} words and short fixed phrases from the transcript that are MOST worth learning now.

Prioritise, in this order:
1. "mistake": words the learner got wrong or struggled with.
2. "asked": words the learner asked about or needed help with.
3. "unit": key vocabulary of the current unit{% if unit.vocabulary %} ({{ unit.vocabulary | join("; ") }}){% endif %} that appeared in the session.
4. "new": other useful, high-frequency words the tutor introduced.

Rules:
{% if monolingual %}- The learner is advanced (C1): pick sophisticated, high-value items — precise verbs, academic and less common words, collocations, phrasal verbs and idioms that would raise an exam score. Never pick basic everyday words. Max {{ max_items }} items.
{% else %}- Max {{ max_items }} items. Skip names, numbers below 20, international words identical in {{ native_language }}, and anything the learner clearly already knows.
{% endif %}
- Do NOT include any of these already-saved words: {{ known_lemmas | join(", ") if known_lemmas else "(none yet)" }}
- "lemma": dictionary form WITHOUT article (nouns singular{% if language == "sv" %}, verbs in the infinitive without "att"{% else %}, verbs in the infinitive{% endif %}). Short fixed phrases are allowed as one item.
- "gender": {% if language == "sv" %}"en" or "ett" for nouns, otherwise ""{% elif language == "fr" %}"m" or "f" for nouns, otherwise ""{% else %}always ""{% endif %}.
- "forms": {% if language == "en" %}the word family or key collocations, e.g. "mitigate – mitigation – mitigating; mitigate the risk/impact"{% elif language == "sv" %}nouns: "en bil – bilen – bilar – bilarna"; verbs: "läsa – läser – läste – har läst"; adjectives: "stor – stort – stora"{% else %}nouns: plural if irregular (e.g. "un œil – des yeux"); verbs: "aller – je vais – nous allons – je suis allé(e)"; adjectives: "beau – belle – beaux – belles"{% endif %}; "" for phrases.
- "pos": noun | verb | adjective | adverb | phrase | preposition | pronoun | conjunction | other.
{% if monolingual %}- "translation": a concise English definition of the sense used in the session (max ~12 words).
{% else %}- "translation": concise {{ native_language }} meaning (the sense used in the session).
{% endif %}
- "example": one short, natural {{ language_name }} sentence at level {{ level }} using the word — preferably the one from the session, corrected if needed. "example_translation": {% if monolingual %}"" (leave empty){% else %}its {{ native_language }} translation{% endif %}.
- "notes": optional short tip (false friend, irregularity, usage) or "".

TRANSCRIPT
==========
{{ transcript }}
==========

Return ONLY JSON: {"items": [ {"lemma", "translation", "pos", "gender", "forms", "example", "example_translation", "reason", "notes"}, … ]}
