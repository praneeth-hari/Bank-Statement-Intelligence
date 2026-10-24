"""A statement repeats itself: the same merchants appear again and again, and OCR rarely misreads all of them.

``RCTC`` is one edit from ``IRCTC``, and ``IRCTC`` is printed a dozen times elsewhere on the same statement. The
document is its own dictionary. This needs no model and no merchant list: the vocabulary is whatever the statement
itself says at least twice, so a name read once (most people) is never "corrected" towards a stranger.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Iterable, Optional

from ..extract.scoring import edit_distance

_NAME = re.compile(r"^((?:UPI|IMPS)/\d{10,13}/)(.+)$", re.S)
MIN_COUNT = 2           # a name must appear at least this often elsewhere to count as known
MAX_EDITS = 2           # the rule's reach; the hint list for a model reaches one edit further
MAX_EDIT_RATIO = 0.25


def squash(text: str) -> str:
    return "".join(text.split()).casefold()


def name_of(description: str) -> Optional[str]:
    m = _NAME.match(description.strip())
    return m.group(2).strip() if m else None


class Vocabulary:
    def __init__(self, descriptions: Iterable[str]):
        self.count: Counter[str] = Counter()
        self._display: dict[str, Counter[str]] = defaultdict(Counter)
        for d in descriptions:
            n = name_of(d or "")
            if n:
                key = squash(n)
                self.count[key] += 1
                self._display[key][n] += 1

    def display(self, key: str) -> str:
        return self._display[key].most_common(1)[0][0]

    def near(self, name: str, max_edits: int = MAX_EDITS) -> list[tuple[str, int]]:
        """Known names close to ``name`` (other than itself), nearest first."""
        key = squash(name)
        out = []
        for cand, n in self.count.items():
            if cand == key or n < MIN_COUNT:
                continue
            d = edit_distance(key, cand)
            if d <= max_edits and d <= MAX_EDIT_RATIO * max(len(cand), 1):
                out.append((cand, d))
        out.sort(key=lambda x: (x[1], -self.count[x[0]]))
        return [(self.display(c), d) for c, d in out]

    def is_known(self, name: str, own: int = 1) -> bool:
        key = squash(name)
        return self.count.get(key, 0) - own >= MIN_COUNT


def vocab_rule(read: str, vocab: Vocabulary) -> Optional[str]:
    """The description with its name replaced by the one known name it is closest to, if that is unambiguous."""
    m = _NAME.match(read.strip())
    if not m:
        return None
    head, name = m.group(1), m.group(2).strip()
    if vocab.is_known(name):
        return None  # printed identically elsewhere, so it is probably right as it stands
    near = vocab.near(name)
    if not near:
        return None
    if len(near) > 1 and near[1][1] == near[0][1]:
        return None  # two known names equally close: do not guess
    return head + near[0][0]


def hints_for(read: str, vocab: Vocabulary, limit: int = 3) -> list[str]:
    """Known names within reach of the cell, for the model's prompt."""
    m = _NAME.match(read.strip())
    if not m:
        return []
    return [n for n, _ in vocab.near(m.group(2).strip(), max_edits=MAX_EDITS + 1)[:limit]]
