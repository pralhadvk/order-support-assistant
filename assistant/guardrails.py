"""Pre-LLM inspection of each customer message: PII redaction, injection and scope signals, escalation triggers.

Detection here is deliberately cheap and conservative (regexes, no model call). It is not the security
boundary: the executor's gates hold even if a crafted message slips past these patterns. What detection
buys is (a) locking write actions for the rest of a suspicious conversation, (b) an audit trail, and
(c) deterministic handoff for requests that should never depend on the model's judgement.
"""

import re
from dataclasses import dataclass, field

# Applied in order: secrets and long digit runs first so shorter patterns don't split them.
_PII_PATTERNS = [
    ("SECRET", re.compile(r"\b(otp|cvv|pin|password)\s*(?:is|:|=)\s*\S+", re.I)),
    ("CARD", re.compile(r"\b(?:\d[ -]?){12,18}\d\b")),  # 13-19 digits; over-redacting is the safe failure
    ("AADHAAR", re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b")),
    ("PHONE", re.compile(r"(?<![\w-])(?:\+?91[ -]?)?[6-9]\d{4}[ -]?\d{5}(?!\d)")),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("UPI", re.compile(r"\b[\w.-]+@[a-z]{2,}\b", re.I)),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
]

_INJECTION_PATTERNS = {
    "instruction_override": re.compile(
        r"\b(ignore|disregard|forget|override|bypass)\b.{0,30}\b(instructions?|rules?|polic(?:y|ies)|guidelines|prompt|system)\b",
        re.I,
    ),
    "prompt_extraction": re.compile(r"\b(reveal|show|print|repeat)\b.{0,30}\b(system prompt|instructions|system message)\b", re.I),
    "role_play": re.compile(r"\byou are now\b|\bpretend (?:to be|you are)\b|\bact as (?:an? )?(?:admin|administrator|supervisor|developer)\b", re.I),
    "claimed_authorisation": re.compile(
        r"\b(manager|supervisor|boss|admin|ceo|staff)\b.{0,40}\b(said|says|approved|authori[sz]ed|allowed|okay|fine|ok)\b", re.I
    ),
    "delimiter_spoofing": re.compile(r"</?\s*customer_message|^\s*(system|assistant|developer)\s*:", re.I | re.M),
}

_SCOPE_PATTERNS = {
    "other_customer_reference": re.compile(r"\bCUST-\d+\b", re.I),
    "third_party_order": re.compile(
        r"\b(another|other|someone else'?s?|my (?:friend|wife|husband|brother|sister|mother|father|colleague)'?s?) "
        r"(?:customer'?s? )?(order|account)s?\b",
        re.I,
    ),
}

_WANTS_HUMAN = re.compile(
    r"\b(speak|talk|chat|connect)\b.{0,20}\b(human|person|agent|representative|executive)\b|\b(real person|live agent|human agent)\b",
    re.I,
)
_LEGAL_OR_COMPLAINT = re.compile(r"\b(lawyer|legal action|sue|consumer (?:court|forum)|police|fraud|scam)\b", re.I)


def redact_pii(text: str) -> tuple[str, list[str]]:
    found = []
    for label, pattern in _PII_PATTERNS:
        text, count = pattern.subn(f"[{label}]", text)
        if count:
            found.append(label)
    return text, found


@dataclass
class GuardrailReport:
    redacted_text: str
    pii_redacted: list[str] = field(default_factory=list)
    injection_signals: list[str] = field(default_factory=list)
    scope_signals: list[str] = field(default_factory=list)
    wants_human: bool = False
    legal_or_complaint: bool = False

    def to_dict(self) -> dict:
        return {
            "pii_redacted": self.pii_redacted,
            "injection_signals": self.injection_signals,
            "scope_signals": self.scope_signals,
            "wants_human": self.wants_human,
            "legal_or_complaint": self.legal_or_complaint,
        }

    def wrapped_for_llm(self) -> str:
        """Customer text is delimited so the system prompt can tell the model it is data, not instructions.

        Angle brackets are escaped so a customer cannot close the tag and append text that looks like
        it came from outside the delimiter.
        """
        flags = self.injection_signals + self.scope_signals
        attr = f' flags="{",".join(flags)}"' if flags else ""
        body = self.redacted_text.replace("<", "&lt;").replace(">", "&gt;")
        return f"<customer_message{attr}>\n{body}\n</customer_message>"


def inspect(message: str) -> GuardrailReport:
    redacted, pii = redact_pii(message)
    return GuardrailReport(
        redacted_text=redacted,
        pii_redacted=pii,
        injection_signals=[name for name, p in _INJECTION_PATTERNS.items() if p.search(message)],
        scope_signals=[name for name, p in _SCOPE_PATTERNS.items() if p.search(message)],
        wants_human=bool(_WANTS_HUMAN.search(message)),
        legal_or_complaint=bool(_LEGAL_OR_COMPLAINT.search(message)),
    )
