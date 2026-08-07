"""
Trendly Support Agent — Flask + Groq (Llama 3.3) with real tool-calling.

Run:
    export GROQ_API_KEY=your_key_here
    python app.py

Then POST to /chat with {"session_id": "abc", "message": "where's my order 1001?"}
Or open http://localhost:5000/ for a minimal chat UI.
"""
import os
import json
import uuid
from flask import Flask, request, jsonify, send_from_directory
from groq import Groq

import tools
from system_prompt import SYSTEM_PROMPT

app = Flask(__name__, static_folder="static")
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

MODEL = "llama-3.3-70b-versatile"

# --- In-memory session state ---------------------------------------------
# NOTE: fine for this assignment. For anything real, swap for Redis/DB.
SESSIONS = {}  # session_id -> list[messages]


def get_session(session_id: str):
    if session_id not in SESSIONS:
        SESSIONS[session_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    return SESSIONS[session_id]


# --- Tool schemas (given to the model) ------------------------------------
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_order",
            "description": "Look up a single order by its order ID. Returns status, items, dates, and tracking info. Use this before answering ANY question about a specific order. If the customer hasn't provided an email yet, call this without customer_email first — the result will indicate whether details are verified, and you should ask for the email on the order before sharing specifics.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "The order ID, e.g. 'TR-4521'"},
                    "customer_email": {"type": "string", "description": "Email to verify the requester owns this order, if they've provided one"},
                },
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_return_eligibility",
            "description": "Determine whether an order is eligible for return or exchange, by combining the order's data with the policy rules. Always use this instead of guessing eligibility yourself.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "The order ID to check"}
                },
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_policy",
            "description": "Search Trendly's shipping & returns policy document for the section(s) relevant to a question. This is the ONLY source of truth for policy — never answer a policy question without calling this first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What the customer wants to know, e.g. 'how long do refunds take'"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_human",
            "description": "Hand the conversation off to a human agent. Use this when the customer is upset, asks for something outside policy (e.g. a discount you can't authorize), the situation is ambiguous, or you cannot resolve the issue with the tools you have.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "A concise summary a human agent could act on immediately: what the customer wants, relevant order ID(s), what's been tried, and why it's being escalated."},
                    "urgency": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["summary", "urgency"],
            },
        },
    },
]

TOOL_IMPL = {
    "get_order": tools.get_order,
    "check_return_eligibility": tools.check_return_eligibility,
    "search_policy": tools.search_policy,
    "escalate_to_human": tools.escalate_to_human,
}


def run_agent_turn(session_id: str, user_message: str, max_tool_hops: int = 6):
    messages = get_session(session_id)
    messages.append({"role": "user", "content": user_message})

    for _ in range(max_tool_hops):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
            temperature=0.2,
        )
        msg = response.choices[0].message

        if not msg.tool_calls:
            # Final answer — no more tools to call
            messages.append({"role": "assistant", "content": msg.content})
            return msg.content

        # Model wants to call one or more tools — append its request, then
        # execute each and append the results before looping again.
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
        })

        for tc in msg.tool_calls:
            fn_name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}
            impl = TOOL_IMPL.get(fn_name)
            result = impl(**args) if impl else {"error": f"unknown tool {fn_name}"}
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": fn_name,
                "content": json.dumps(result),
            })

    # Safety valve: if we somehow loop too long, escalate rather than hang.
    fallback = "I'm having trouble resolving this on my own — let me get a human involved."
    messages.append({"role": "assistant", "content": fallback})
    return fallback


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True)
    session_id = data.get("session_id") or str(uuid.uuid4())
    user_message = data.get("message", "")
    if not user_message.strip():
        return jsonify({"error": "message is required"}), 400

    reply = run_agent_turn(session_id, user_message)
    return jsonify({"session_id": session_id, "reply": reply})


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


if __name__ == "__main__":
    app.run(debug=True, port=5000)
