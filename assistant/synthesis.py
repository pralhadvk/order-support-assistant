"""Post-generation grounding check.

Two rules, enforced in code after the model writes its reply:
1. Every cited DOC must have been returned by search_policy in this conversation (no invented sources).
2. Every timeline figure ("5-7 business days", "48 hours") must be traceable to a retrieved policy's text,
   the customer's own words, or a paragraph citing the order record. Timelines are exactly what a model
   fills in from general knowledge, and they are what customers act on.

This is a lexical heuristic: a coincidental number match passes, and the [ORDER] exemption trusts the model's
arithmetic on record dates. A production version would add an entailment model to verify each claim
against its cited source.
"""

import re
from dataclasses import dataclass, field

DOC_REF = re.compile(r"DOC-\d+")
NUMBER = re.compile(r"\d+")
DURATION = re.compile(
    r"\b\d+(?:\s*(?:-|–|to)\s*\d+)?\s*(?:additional\s+|extra\s+)?(?:business\s+|working\s+)?(?:hours?|days?)\b",
    re.IGNORECASE,
)
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass
class GroundingResult:
    cited_docs: set[str] = field(default_factory=set)
    unknown_citations: set[str] = field(default_factory=set)
    unsupported_claims: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.unknown_citations and not self.unsupported_claims

    def feedback(self) -> str:
        problems = []
        if self.unknown_citations:
            problems.append(f"cites {sorted(self.unknown_citations)}, which search_policy never returned")
        if self.unsupported_claims:
            problems.append(
                "states timeline figures that appear in no retrieved policy, order record or customer message: "
                + " | ".join(self.unsupported_claims)
            )
        return "; ".join(problems)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "cited_docs": sorted(self.cited_docs),
            "unknown_citations": sorted(self.unknown_citations),
            "unsupported_claims": self.unsupported_claims,
        }


def check_grounding(answer: str, retrieved_docs: dict[str, str], customer_messages: list[str]) -> GroundingResult:
    cited = set(DOC_REF.findall(answer))
    supported_numbers = {n for text in [*retrieved_docs.values(), *customer_messages] for n in NUMBER.findall(text)}

    unsupported = []
    for block in filter(None, (b.strip() for b in answer.splitlines())):
        cites_order = "[ORDER]" in block
        for sentence in SENTENCE_SPLIT.split(block):
            for match in DURATION.finditer(sentence):
                if not set(NUMBER.findall(match.group())) <= supported_numbers and not cites_order:
                    unsupported.append(sentence)
                    break

    return GroundingResult(cited_docs=cited, unknown_citations=cited - retrieved_docs.keys(), unsupported_claims=unsupported)
