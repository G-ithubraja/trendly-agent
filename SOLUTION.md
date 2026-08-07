# Solution Note — Trendly Support Agent

## Architecture

The agent is a Flask app (`app.py`) that runs a ReAct-style tool-calling loop
against Llama 3.3 70B via Groq's OpenAI-compatible API. On each user message:

1. The message is appended to that session's conversation history (kept
   in-memory, keyed by a session ID from the client).
2. The model is called with the full history plus four tool definitions. It
   either returns a final answer, or one or more tool calls.
3. Tool calls are executed against local data (`tools.py`) and the results
   are appended back into the conversation as `tool` messages.
4. This repeats (up to a safety cap of 6 hops) until the model has enough
   information to answer, or the loop bails out to an escalation message if
   something goes wrong.

**The four tools:**
- `get_order(order_id, customer_email?)` — looks up order data; withholds
  the customer's name unless a matching email is supplied, so the agent
  can't casually leak PII to an unverified requester.
- `check_return_eligibility(order_id)` — combines order status, delivery
  date, and item categories with the policy rules (return window,
  non-returnable categories, final-sale exchange-only, footwear box
  deduction, cancelled/lost-in-transit special cases) and returns a
  structured, per-item eligibility verdict rather than a yes/no.
- `search_policy(query)` — keyword-overlap retrieval over the policy
  markdown, split into sections by heading. Returns the top matching
  section(s) or an explicit "not found" signal, which the system prompt
  treats as a hard stop against inventing an answer.
- `escalate_to_human(summary, urgency)` — logs a ticket with a
  human-readable summary and returns a ticket ID.

**Grounding and guardrails** live primarily in the system prompt
(`system_prompt.py`) as a numbered list of hard rules — always call a tool
before stating order/policy facts, never invent an email for identity
verification, treat lost-in-transit and cancelled orders as special cases
rather than running normal return logic on them, never collect payment
details, and escalate rather than freelance when policy is silent or the
customer is upset.

## Key trade-offs

- **Keyword search over embeddings for policy retrieval.** The policy doc
  is one short file. A proper vector index would be more robust to
  paraphrasing but was overkill for this scope; if Trendly's policy grows
  to many documents, this should be swapped for real retrieval.
- **In-memory session state over a database.** Simplest thing that works
  for a single-instance demo. Doesn't survive a restart and doesn't scale
  across multiple server instances — fine here, not fine in production.
- **Identity verification is opt-in, not blanket.** The agent will share
  basic order status without an email, but withholds the customer's name
  and requires verification before eligibility/return actions. This was a
  deliberate balance between the "no data leakage" requirement and not
  making every single status check feel like an interrogation — a real
  product would probably tie this to actual customer auth instead of an
  email the customer just types in, which is really only friction, not
  real security.
- **Rule-based eligibility logic over letting the model reason it out.**
  `check_return_eligibility` is deterministic Python, not the LLM
  inferring from raw policy text. This trades some flexibility for
  correctness and auditability — the exact scenarios the dataset was
  built to test (window expiry, non-returnable categories, final sale,
  lost parcel, cancelled order) all resolve correctly and repeatably.

## Known limitations

- Free-tier Groq rate limits (100k tokens/day on Llama 3.3 70B) were hit
  during testing and are a real constraint on how much live evaluation
  this can absorb in a day.
- Render's free instance sleeps after 15 minutes idle; the first request
  after a gap can take 30-50 seconds.
- Session state is lost on server restart/redeploy.
- No real authentication — email-based verification is a UX nod toward
  privacy, not a security boundary.
- `search_policy`'s keyword matching will miss questions that are
  phrased very differently from the policy doc's own wording.

## Five discovery questions for Trendly's ops team

1. What does real customer authentication look like in the production
   chat surface — is there already a logged-in session/customer ID we
   should key off, instead of asking for an email in-chat?
2. How should the agent behave differently for customers who are already
   flagged (e.g. serial returners, open disputes, VIP tiers) — is that
   data available to pull in, and should policy apply differently to them?
3. What's the actual expected escalation path — does `escalate_to_human`
   need to write into a real ticketing system (Zendesk, Freshdesk, etc.)
   immediately, and what SLA should the customer be told to expect?
4. How often does the policy document change, and who owns keeping it in
   sync with what's actually enforced by ops — since the agent is only as
   correct as that document?
5. What's the acceptable error mode when the agent is uncertain — should
   it always default to escalating, or is there a middle ground (e.g.
   answering with a caveat) that ops would rather it use for borderline
   cases?
