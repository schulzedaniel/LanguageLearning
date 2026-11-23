{# Review page → "Pick words from the transcript": fills in flashcard fields for words the learner chose (JSON). #}
You are a {{ language_name }} dictionary and teacher. A learner at level {{ level }} (native language: {{ native_language }}) picked these words or phrases from their lesson transcript to learn as flashcards. Each comes with the sentence it appeared in.

{% for w in words %}{{ loop.index }}. "{{ w.text }}"{% if w.context %} (in: "{{ w.context }}"){% endif %}

{% endfor %}
Return ONLY JSON {"items": [...]} with exactly one item per picked word, in the same order:
- "lemma": dictionary form WITHOUT article (nouns singular{% if language == "sv" %}, verbs in the infinitive without "att"{% else %}, verbs in the infinitive{% endif %}); keep short fixed phrases as they are. If the learner picked an inflected form (e.g. a plural or a conjugated verb), give the dictionary form.
- "translation": {% if monolingual %}a concise English definition of the sense used in that sentence (max ~12 words){% else %}concise {{ native_language }} meaning in the sense used in that sentence{% endif %}.
- "pos": noun | verb | adjective | adverb | phrase | preposition | pronoun | conjunction | other.
- "gender": {% if language == "sv" %}"en" or "ett" for nouns, otherwise ""{% elif language == "fr" %}"m" or "f" for nouns, otherwise ""{% else %}always ""{% endif %}.
- "forms": {% if language == "en" %}word family or key collocations{% elif language == "sv" %}nouns "en bil – bilen – bilar – bilarna"; verbs "läsa – läser – läste – har läst"; adjectives "stor – stort – stora"{% else %}nouns: plural if irregular; verbs "aller – je vais – nous allons – je suis allé(e)"; adjectives "beau – belle – beaux – belles"{% endif %}; "" for phrases.
- "example": the sentence from the lesson if it is a good, correct example (corrected if needed, without markdown), otherwise a short natural sentence at level {{ level }}.
- "example_translation": {% if monolingual %}""{% else %}its {{ native_language }} translation{% endif %}.
- "reason": "picked".
- "notes": a short tip (false friend, irregularity, usage) or "".
