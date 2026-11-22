## Today's session: review
Your job is to strengthen what the learner has already met but hasn't mastered.
{% if weak_vocab %}- Weak words to practise: {{ weak_vocab | join(", ") }}{% endif %}
{% if recurring_errors %}- Mistakes to drill: {% for e in recurring_errors %}{{ e.pattern }}{% if not loop.last %}; {% endif %}{% endfor %}{% endif %}
- Also review the key vocabulary and grammar of "{{ unit.title }}"{% if level_units %} and earlier {{ level }} units{% endif %}.

Use quick, varied activities, one at a time: "How do you say …?", "Make a sentence with …", "What's the opposite of …?", fill-in-the-gap, short questions that require a target structure, quick translations. Keep the rhythm fast and encouraging; when they get something wrong, give the correct form and come back to it a few turns later.
