# Prompt iteration log

## v1 — initial system prompt

First draft covered the basics: four tools, ground policy answers in
search_policy, don't invent discounts, escalate when needed. This got
order lookup and simple policy questions working correctly on the first
try.

## v2 — identity verification added, then broke status lookups

Added a rule requiring the agent to verify the customer's email before
sharing order details, to guard against the "no data leakage" requirement
in the assignment. In testing, this backfired: asking about a real order
(e.g. "TR-4521") with no email given caused the model to invent a
placeholder email, call get_order with it, get a mismatch, and escalate
a perfectly normal status question instead of answering it.

Log evidence from that run:
[ESCALATION][LOW] TCK-66981: Customer is trying to access order TR-4521
but the email provided does not match our records.

No email had actually been given by the customer at that point — the
model fabricated one to satisfy the verification rule.

Fix: rewrote the rule to explicitly forbid inventing an email, and
split verification into two tiers — call get_order with just the order_id
first (status/tracking still shown, customer name withheld), and only
ask for and pass a real customer_email when the customer wants to take a
sensitive action (return, refund) or actually provides one unprompted.

After the fix, the same "TR-4521" input correctly asked the customer for
their email instead of guessing, and answered normally once given the
right one.

## v3 — verified against the real dataset's edge cases

Once the real orders.json/trendly_policy.md replaced the placeholders,
tested against orders that looked purpose-built to test specific rules:
outside the return window, jewellery (non-returnable), final sale
(exchange-only), cancelled order, lost-in-transit, and a clean happy
path. All resolved correctly without further prompt changes — the
verification fix plus deterministic eligibility logic handled them.

## v4 — safety and refusal testing

Tested a discount request and a mid-conversation identity check on a
different order than the one already verified. Both handled correctly:
the discount ask was refused and escalated with a clear reason, and
asking about a second order re-triggered verification rather than
assuming the earlier email applied to every order in the session.

## Final prompt

See system_prompt.py in the repo for the version actually running — the
numbered hard-rules list reflects all of the above, especially the
identity verification rule, which changed the most based on real
testing rather than being right the first time.
