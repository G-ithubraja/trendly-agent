"""
Tool implementations the agent calls, built against the REAL assignment
data: orders.json (nested customers/orders) and trendly_policy.md.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent
ORDERS_PATH = BASE_DIR / "orders.json"
POLICY_PATH = BASE_DIR / "trendly_policy.md"

with open(ORDERS_PATH) as f:
    _data = json.load(f)

CUSTOMERS = {c["customer_id"]: c for c in _data["customers"]}
ORDERS = {o["order_id"]: o for o in _data["orders"]}

with open(POLICY_PATH) as f:
    POLICY_TEXT = f.read()

# --- Split policy into sections on markdown headings (# / ## / ###) -------
_SECTIONS = []
_current_heading, _current_body = "Overview", []
for line in POLICY_TEXT.splitlines():
    if re.match(r"^#{1,3}\s+", line):
        if _current_body:
            _SECTIONS.append((_current_heading, "\n".join(_current_body).strip()))
        _current_heading = re.sub(r"^#{1,3}\s+", "", line).strip()
        _current_body = []
    else:
        _current_body.append(line)
if _current_body:
    _SECTIONS.append((_current_heading, "\n".join(_current_body).strip()))

# Policy 2.3: non-returnable categories (matched against orders.json item
# "category" values, which are lowercase strings like "innerwear", "jewellery").
NON_RETURNABLE_CATEGORIES = {"innerwear", "jewellery", "beauty", "fragrance", "face masks", "gift cards"}
RETURN_WINDOW_DAYS = 30  # policy 2.1


def _parse_dt(s):
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def get_order(order_id: str, customer_email: str = None) -> dict:
    """
    If customer_email is provided, it must match the order's customer record
    or we refuse to disclose details (policy 7: never discuss another
    customer's order). If not provided, the order is returned but flagged
    unverified so the agent knows to ask for verification before sharing
    specifics.
    """
    order = ORDERS.get(order_id)
    if not order:
        return {"found": False, "error": f"No order found with ID {order_id}"}

    customer = CUSTOMERS.get(order["customer_id"], {})

    if customer_email:
        if customer.get("email", "").lower() != customer_email.strip().lower():
            return {
                "found": False,
                "error": "The email provided does not match our records for this order. "
                         "For privacy, I can't share order details without verifying identity.",
            }
        verified = True
    else:
        verified = False

    return {
        "found": True,
        "verified": verified,
        "order": order,
        "customer_name": customer.get("name") if verified else None,
    }


def check_return_eligibility(order_id: str) -> dict:
    """Combines order data with the real policy rules (sections 2, 4, 6)."""
    order = ORDERS.get(order_id)
    if not order:
        return {"order_id": order_id, "order_level_eligible": False,
                 "order_level_reason": f"No order found with ID {order_id}", "items": []}

    status = order.get("status")

    if status == "cancelled":
        return {"order_id": order_id, "order_level_eligible": False,
                 "order_level_reason": "Order was cancelled — no return can be raised against it (policy 2.6).",
                 "items": []}

    if status == "lost_in_transit":
        return {"order_id": order_id, "order_level_eligible": False,
                 "order_level_reason": "This is a lost-parcel claim, not a return, and must be handled by a human agent (policy 1.6).",
                 "requires_escalation": True, "items": []}

    if status != "delivered":
        return {"order_id": order_id, "order_level_eligible": False,
                 "order_level_reason": f"Order has not been delivered yet (status: {status}) — returns can only be raised after delivery.",
                 "items": []}

    delivered_at = _parse_dt(order.get("delivered_at"))
    days_since = None
    if delivered_at:
        days_since = (datetime.now(timezone.utc) - delivered_at).days
        if days_since > RETURN_WINDOW_DAYS:
            return {"order_id": order_id, "order_level_eligible": False,
                     "order_level_reason": f"Delivered {days_since} days ago — outside the {RETURN_WINDOW_DAYS}-day return window (policy 2.1).",
                     "items": []}

    item_results = []
    for item in order.get("items", []):
        category = (item.get("category") or "").lower()
        name = item.get("name", item.get("sku"))
        if category in NON_RETURNABLE_CATEGORIES:
            item_results.append({
                "sku": item.get("sku"), "name": name, "eligible": False,
                "reason": f"'{name}' is in a non-returnable category ({category}) per policy 2.3.",
            })
        elif item.get("final_sale"):
            item_results.append({
                "sku": item.get("sku"), "name": name, "eligible": True,
                "exchange_only": True,
                "reason": f"'{name}' is final sale — eligible for size exchange only, no refund/store credit (policy 2.4).",
            })
        else:
            note = ""
            if category == "footwear":
                note = " Must be returned in original shoe box or a ₹300 deduction applies (policy 2.5)."
            item_results.append({
                "sku": item.get("sku"), "name": name, "eligible": True,
                "reason": f"Within the {RETURN_WINDOW_DAYS}-day window, returnable category.{note}",
            })

    any_eligible = any(i["eligible"] for i in item_results)
    return {
        "order_id": order_id,
        "order_level_eligible": any_eligible,
        "order_level_reason": f"Delivered {days_since} day(s) ago, within the {RETURN_WINDOW_DAYS}-day window."
                               if days_since is not None else "Delivered date unknown.",
        "items": item_results,
    }


def search_policy(query: str) -> dict:
    """Naive keyword-overlap retrieval over policy sections."""
    if not _SECTIONS:
        return {"found": False, "sections": []}

    query_terms = set(re.findall(r"\w+", query.lower()))
    scored = []
    for heading, body in _SECTIONS:
        text = (heading + " " + body).lower()
        score = sum(1 for term in query_terms if term in text)
        if score > 0:
            scored.append((score, heading, body))

    scored.sort(key=lambda x: -x[0])
    top = scored[:2]
    if not top:
        return {"found": False, "sections": [], "note": "No matching section — do not answer from outside knowledge, tell the customer you don't know."}

    return {"found": True, "sections": [{"heading": h, "text": b} for _, h, b in top]}


def escalate_to_human(summary: str, urgency: str = "medium") -> dict:
    ticket_id = f"TCK-{abs(hash(summary)) % 100000}"
    print(f"[ESCALATION][{urgency.upper()}] {ticket_id}: {summary}")
    return {"escalated": True, "ticket_id": ticket_id, "urgency": urgency}
