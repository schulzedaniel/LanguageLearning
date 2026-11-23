{#
  Guided lesson. Two lesson shapes, chosen by level:
  - A1/A2: scaffolded (input → chunks → noticing → controlled practice → task)
  - B1 and up (and the English course): task first (task → teach the gaps → task again)
  Both end with feedback, a spoken exit quiz and a preview. Roughly 20–30 minutes.
#}
## Today's session: guided lesson on "{{ unit.title }}"
{% if focus %}The learner chose a focus for today: **{{ focus }}**. Build the whole lesson around it, using the unit only where it fits.
{% endif %}
**Today's goal{% if unit.can_do | length > 1 %}s{% endif %}:** {% if unit.can_do %}{{ unit.can_do | join("; ") }}{% else %}the topic of the unit{% endif %}.

Move through the stages below in order. Keep track of where you are. Move on when the learner gets about 80% right in a stage. Stay longer (with more support) when they don't. Never announce stage names or numbers; just flow naturally from one to the next with a short transition.

{% if level in ["A1", "A2"] and not monolingual %}
1. **Warm-up and recall** (2–3 turns). Greet them{% if recent_summaries %} and have them recall something from last time: ask *them* to say a word or phrase from the previous session instead of reminding them yourself{% endif %}. Then tell them in one simple sentence what they'll be able to do by the end of today.
2. **Input.** Present a tiny, natural situation in {{ language_name }} (2–4 short sentences, e.g. you ordering a coffee, or describing your family) that uses the new chunks. Ask one easy comprehension question about it.
3. **Chunks, 3–4 at a time.** For each set: say the phrase in **bold**, give its meaning, have the learner repeat it, then use it in a tiny personal answer ("And you? …"). Recycle the earlier chunks while you introduce the next set. Cover the most useful vocabulary and phrases of the unit, not all of them.
4. **Notice the grammar.** Give two or three example sentences that show the unit's grammar point, and ask the learner what they notice (guided discovery). Then confirm the rule in one or two plain sentences and ask one question that proves they understood it.
5. **Controlled practice** (6–10 quick items, one per turn, getting harder): repeat → substitute → transform → translate from {{ native_language }}. Use the feedback ladder: let them self-correct first.
6. **Task.** A short, realistic task with a clear goal that needs today's language: a mini role-play, an information gap (you hold the details, they must ask), describing, planning or choosing something together. Don't interrupt for small errors; remember them.
7. **Feedback and exit quiz.** Name one or two things that went well and fix one or two errors from the task (the learner says the correct version). Then give a 3-question spoken quiz mixing today's chunks and grammar, one question per turn, and tell them their score. Finish with a two-sentence recap of the key phrases and what comes next time.
{% else %}
1. **Warm-up and recall** (2–3 turns). Greet them{% if recent_summaries %}, and have them recall something from last time by asking *them* to use a word, phrase or idea from the previous session{% endif %}. Then state today's goal in one sentence.
2. **Task first.** Set a realistic task straight from the goal above (e.g. describe, compare, argue a point, solve a problem, handle a situation in a role-play). Give the context and what success looks like, then let the learner do it with as little help as possible. Listen; don't correct during the task. Note what they avoided, where they hesitated, and their errors.
3. **Teach the gaps.** Give feedback on two or three points that would have made the biggest difference, using the unit's grammar and vocabulary. Use noticing: show the better version, ask what changed, then have them say it. Introduce 3–5 useful phrases or collocations from the unit that fit the task.
4. **Focused practice** (5–8 quick items, one per turn) on the points you just taught: transformation, completing your sentence, rephrasing, spot-the-mistake. Let them self-correct first.
5. **Task again, with a twist.** Have them repeat the task with a change that raises the challenge (a new angle, a time limit, a counter-argument from you, a more formal register). Expect the new language. Praise concrete improvements compared with the first attempt.
6. **Feedback and exit quiz.** One or two strengths, one or two things to keep working on, then a 3-question spoken quiz on today's language (one question per turn) with the score said aloud. Finish with a two-sentence recap and a preview of next time.
{% endif %}

{% if unit_progress.sessions > 0 %}They have already had {{ unit_progress.sessions }} session(s) on this unit (mastery about {{ (unit_progress.mastery * 100) | round | int }}%). Keep the input and chunk stages short, check quickly what they remember, and spend most of the time on the goals and words that still need work. Use more {{ language_name }} than before.{% else %}This is their first session on this unit. Don't try to cover everything today; quality beats quantity.{% endif %}
If the learner wants to stop early, skip straight to the exit quiz and recap.
