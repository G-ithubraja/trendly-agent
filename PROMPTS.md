# Prompt iteration log

## v1 — initial system prompt
[Paste your first draft here. What did it get wrong when you tested it?]

## v2 — after testing order lookup
[e.g. "Model answered order status from memory when the same order was
mentioned 2 turns earlier, instead of re-calling get_order. Added rule 1
in system_prompt.py to force a re-check."]

## v3 — after testing policy grounding
[e.g. "Model answered a policy question that search_policy didn't have a
good match for, by guessing. Added explicit 'do not invent an answer'
instruction and a 'found: false' signal from search_policy."]

## v4 — after testing escalation
[...]

## Final prompt
See `system_prompt.py` in the repo — this is the version actually running.
