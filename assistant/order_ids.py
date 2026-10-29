"""Order ID extraction and normalisation.

Deliberately strict: only explicit order references count. "My order of Rs 5000" must NOT yield
ORD-5000, otherwise the model could "find" an order ID in an amount and query a real order.
"""

import re

_MENTION_PATTERNS = [
    re.compile(r"\bORD[-\s]?(\d{4})\b", re.IGNORECASE),  # ORD-4521, ORD4521, ord 4521
    re.compile(r"(?<![\w₹])#\s?(\d{4})\b"),  # #4521
    re.compile(r"\border\s+(?:no\.?|number|id)?\s*:?\s*#?(\d{4})\b", re.IGNORECASE),  # order 4521, order no. 4521
]
_NORMALISE = re.compile(r"^(?:ORD)?[-\s#]*(\d{4})$", re.IGNORECASE)


def normalize_order_id(raw: str) -> str | None:
    match = _NORMALISE.match(raw.strip())
    return f"ORD-{match.group(1)}" if match else None


def mentioned_order_ids(texts: list[str]) -> set[str]:
    return {f"ORD-{m.group(1)}" for text in texts for p in _MENTION_PATTERNS for m in p.finditer(text)}
