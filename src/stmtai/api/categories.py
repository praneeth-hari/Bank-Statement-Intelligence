"""Categories you define yourself.

A rule says "if the description contains this text, call it that". Matching ignores case, and the oldest rule that
matches wins, so the order never changes under you. A transaction no rule matches is ``Uncategorised``: it is
never guessed at. Nothing is categorised until a rule exists, and the starter list below is only offered, never applied.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

UNCATEGORISED = "Uncategorised"
MAX_RULES = 100
PATTERN_LEN = (2, 40)
CATEGORY_LEN = (1, 24)


@dataclass(frozen=True)
class Rule:
    id: int
    pattern: str
    category: str


# Offered on the Transactions page, with how many approved transactions each would match. Never applied on its own.
STARTERS: list[tuple[str, str]] = [
    ("APOLLO", "Health"), ("PHARMEASY", "Health"), ("PHARMACY", "Health"),
    ("BIGBASKET", "Groceries"), ("BLINKIT", "Groceries"), ("DMART", "Groceries"), ("RELIANCE SMART", "Groceries"),
    ("MYNTRA", "Shopping"), ("AMAZON", "Shopping"), ("FLIPKART", "Shopping"),
    ("AIRTEL", "Phone and internet"), ("JIO", "Phone and internet"),
    ("SPOTIFY", "Entertainment"), ("NETFLIX", "Entertainment"), ("BOOKMYSHOW", "Entertainment"),
    ("IRCTC", "Travel"), ("ZOMATO", "Food"), ("SWIGGY", "Food"),
    ("EMI", "Loan"), ("ATM WDL", "Cash"), ("SALARY", "Salary"),
    ("SMS ALERT", "Bank charges"), ("DEBIT CARD AMC", "Bank charges"), ("INTEREST", "Interest"),
]


def clean(pattern: str, category: str) -> tuple[str, str]:
    p, c = " ".join((pattern or "").split()), " ".join((category or "").split())
    if not PATTERN_LEN[0] <= len(p) <= PATTERN_LEN[1]:
        raise ValueError(f"The text to look for must be {PATTERN_LEN[0]} to {PATTERN_LEN[1]} characters.")
    if not CATEGORY_LEN[0] <= len(c) <= CATEGORY_LEN[1]:
        raise ValueError(f"The category name must be {CATEGORY_LEN[0]} to {CATEGORY_LEN[1]} characters.")
    if c.casefold() == UNCATEGORISED.casefold():
        raise ValueError(f"'{UNCATEGORISED}' is what is left when no rule matches, so it cannot be a rule's category.")
    return p, c


def first_rule(description: str, rules: list[Rule]) -> Optional[Rule]:
    text = description.casefold()
    for r in rules:                       # oldest first
        if r.pattern.casefold() in text:
            return r
    return None


def category_of(description: str, rules: list[Rule]) -> str:
    rule = first_rule(description, rules)
    return rule.category if rule else UNCATEGORISED
