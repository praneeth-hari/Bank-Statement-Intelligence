"""Extract a bank statement from positioned words: a PDF text layer, or OCR output.

No layout-specific code. The extractor:

1. groups words into visual lines,
2. finds the table header band and turns each header cell into a column (date, description, debit, ...),
3. assigns every later word to a column by its x position,
4. starts a new transaction on every line with a date in the date column, and appends wrapped lines
   (no date, no amount) to the open transaction,
5. treats lines with amounts but no date as markers (opening / carried-forward / closing rows, summary boxes),
6. reads account-level fields from the text above the table.

Two modes share this engine. ``DIGITAL`` trusts the text exactly. ``OCR`` groups lines by centre height
(OCR boxes jitter), widens column tolerance, parses dates and money tolerantly, and starts transactions on
damaged dates too, so a misread date costs one field rather than a whole row.

Every field keeps its text, parsed value, confidence and bounding box, so the review UI can highlight it.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Optional

import pymupdf

from .models import BBox, ExtractedStatement, ExtractedTransaction, FieldValue
from .parse import (DATE_FIND_RE, is_amount, looks_like_date, parse_date, parse_date_tolerant, parse_money)
from .text import reference_matches, snap_prefix

MAX_CONT_GAP = 13.0  # max vertical distance between a wrapped line and the line above it (points)
MIN_WORDS_FOR_DIGITAL = 20
CELL_GAP = 8.0  # header words closer than this belong to the same header cell

TEXT_CONF = 0.99
HEADER_CONF = 0.97
INFERRED_CONF = 0.90
REPAIR_PENALTY = 0.85  # OCR text that needed repair before it parsed
CROSS_VERIFIED_CONF = 0.95  # a value read twice, independently, with both reads agreeing

_MARKER_WORDS = ("opening", "closing", "brought", "carried", "total", "summary")


@dataclass(frozen=True)
class Mode:
    name: str
    source: str  # value written to FieldValue.source
    line_tol: float  # digital: max difference in word tops; ocr: max distance from the line's centre
    col_tol: float  # a word belongs to a column if its left edge is within this of the header's left edge
    tolerant: bool


DIGITAL = Mode("digital", "text_layer", line_tol=3.0, col_tol=4.0, tolerant=False)
OCR = Mode("ocr", "ocr", line_tol=4.5, col_tol=10.0, tolerant=True)


class NotDigitalError(Exception):
    """The PDF has no usable text layer (it is a scan)."""


class ExtractionError(Exception):
    """The document was read but the transaction table could not be located."""


@dataclass
class Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    page: int
    conf: float = 1.0
    display: Optional[tuple[float, float, float, float]] = None  # box on the original image, if different

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class Line:
    page: int
    y0: float
    words: list[Word] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@dataclass
class _Cell:
    x0: float
    x1: float
    words: list[Word]

    @property
    def text(self) -> str:
        ordered = sorted(self.words, key=lambda w: (round(w.y0 / 3.0), w.x0))
        return " ".join(w.text for w in ordered)


@dataclass
class _Row:
    page: int
    words: dict[str, list[Word]] = field(default_factory=dict)
    last_y: float = 0.0


# --------------------------------------------------------------------------- line grouping
def group_lines(words: list[Word], mode: Mode) -> list[Line]:
    if not words:
        return []
    lines: list[Line] = []
    if not mode.tolerant:
        for w in sorted(words, key=lambda w: (w.y0, w.x0)):
            if not lines or w.y0 - lines[-1].y0 > mode.line_tol:
                lines.append(Line(w.page, w.y0, [w]))
            else:
                lines[-1].words.append(w)
    else:
        # OCR: compare centres with a running line centre, so small residual tilt does not split a line.
        heights = [w.y1 - w.y0 for w in words]
        tol = min(mode.line_tol, 0.45 * median(heights)) if heights else mode.line_tol
        centres: list[float] = []
        for w in sorted(words, key=lambda w: (w.yc, w.x0)):
            if lines and abs(w.yc - centres[-1]) <= tol:
                lines[-1].words.append(w)
                n = len(lines[-1].words)
                centres[-1] += (w.yc - centres[-1]) / n
            else:
                lines.append(Line(w.page, w.y0, [w]))
                centres.append(w.yc)
        for line, c in zip(lines, centres):
            line.y0 = c
    for line in lines:
        line.words.sort(key=lambda w: w.x0)
    return lines


def read_lines(doc: pymupdf.Document) -> list[list[Line]]:
    pages: list[list[Line]] = []
    for pno, page in enumerate(doc):
        words = [Word(x0, y0, x1, y1, t, pno) for x0, y0, x1, y1, t, *_ in page.get_text("words") if t.strip()]
        pages.append(group_lines(words, DIGITAL))
    return pages


def _bbox(words: list[Word]) -> Optional[BBox]:
    if not words:
        return None
    boxes = [w.display or (w.x0, w.y0, w.x1, w.y1) for w in words]
    return BBox(page=words[0].page, x0=min(b[0] for b in boxes), y0=min(b[1] for b in boxes),
                x1=max(b[2] for b in boxes), y1=max(b[3] for b in boxes))


# --------------------------------------------------------------------------- table header
def map_header(text: str) -> Optional[str]:
    t = re.sub(r"[^a-z]", "", text.lower())  # OCR often drops spaces and punctuation in headers
    if not t:
        return None
    if "value" in t and "date" in t:
        return "value_date"
    if t in {"date", "txndate", "trandate", "transdate", "transactiondate", "postingdate"}:
        return "date"
    if any(k in t for k in ("narration", "description", "particulars", "remarks", "details")):
        return "description"
    if any(k in t for k in ("chq", "cheque", "ref", "instrument")):
        return "ref"
    if any(k in t for k in ("withdrawal", "debit")):
        return "debit"
    if any(k in t for k in ("deposit", "credit")):
        return "credit"
    if t.startswith("amount"):
        return "amount"
    if "balance" in t:
        return "balance"
    return None


# Real column labels, letters only. Used to recognise headers OCR has damaged ('Marration', 'Credl').
_HEADER_VOCAB: dict[str, tuple[str, ...]] = {
    "value_date": ("valuedate", "valuedt"),
    "date": ("date", "txndate", "trandate", "transdate", "transactiondate", "postingdate", "txndt"),
    "description": ("narration", "description", "particulars", "remarks", "details", "transactiondetails"),
    "ref": ("chqrefno", "chequeno", "refno", "chqno", "reference", "instrumentno"),
    "debit": ("withdrawalamt", "withdrawal", "withdrawals", "debit", "debitamt"),
    "credit": ("depositamt", "deposit", "deposits", "credit", "creditamt"),
    "amount": ("amount",),
    "balance": ("balance", "closingbalance", "runningbalance", "balanceamt"),
}
# Account-information labels that sit above the table; never fuzzy-match these to a column.
_NOT_HEADERS = ("acc", "open", "stat", "curr", "bran", "ifsc", "name", "peri", "summ", "tota")
FUZZY_HEADER_MIN = 0.66
FUZZY_HEADER_MIN_LONG = 0.60  # labels of 7+ letters carry enough signal to tolerate more damage
FUZZY_MIN_LETTERS = 5  # shorter fragments ('ant' from 'Amt.') are too ambiguous for edit-distance matching


def map_header_fuzzy(text: str) -> Optional[str]:
    """``map_header`` first; then a four-letter prefix match; then edit similarity. OCR mode only."""
    exact = map_header(text)
    if exact:
        return exact
    t = re.sub(r"[^a-z]", "", text.lower())
    if len(t) < 3 or t.startswith(_NOT_HEADERS):
        return None
    if len(t) >= 4:
        for name, words in _HEADER_VOCAB.items():
            if any(w.startswith(t[:4]) for w in words):
                return name
    if len(t) < FUZZY_MIN_LETTERS:
        return None
    from difflib import SequenceMatcher

    best_name, best = None, 0.0
    for name, words in _HEADER_VOCAB.items():
        for w in words:
            ratio = SequenceMatcher(None, t, w).ratio()
            if ratio > best:
                best_name, best = name, ratio
    minimum = FUZZY_HEADER_MIN_LONG if len(t) >= 7 else FUZZY_HEADER_MIN
    return best_name if best >= minimum else None


def _build_cells(words: list[Word]) -> list[_Cell]:
    cells: list[_Cell] = []
    for w in sorted(words, key=lambda w: w.x0):
        if cells and w.x0 <= cells[-1].x1 + CELL_GAP:
            cells[-1].words.append(w)
            cells[-1].x1 = max(cells[-1].x1, w.x1)
        else:
            cells.append(_Cell(w.x0, w.x1, [w]))
    return cells


def _line_has_date(line: Line, mode: Mode) -> bool:
    if DATE_FIND_RE.search(line.text):
        return True
    return mode.tolerant and bool(line.words) and looks_like_date(line.words[0].text)


def _line_has_amount(line: Line, mode: Mode) -> bool:
    if any(is_amount(w.text) for w in line.words):
        return True
    return mode.tolerant and any(re.fullmatch(r"[\d,.:;]{4,}\d", w.text) for w in line.words)


_TEXT_COLUMNS = ("date", "value_date", "description", "ref")


def _infer_columns(columns: list[tuple[float, str]], body: list[Line], mode: Mode) -> tuple[list[tuple[float, str]], list[str]]:
    """Fill in columns whose header OCR lost, from what the cells below contain. OCR mode only.

    * a missing **date** column: the leftmost cell of most rows looks like a date;
    * missing **amount** columns: amounts are right-aligned, so their right edges cluster per column; clusters
      no named column claims get the missing names in the standard order (debit, credit, balance).

    The balance chain later confirms or refutes the guess; inferred names are reported in the metadata.
    """
    columns = sorted(columns)
    names = [n for _, n in columns]
    inferred: list[str] = []
    sample = body[:15]

    if "date" not in names:
        xs = [ln.words[0].x0 for ln in sample if ln.words and looks_like_date(ln.words[0].text)]
        if len(xs) >= 3:
            columns = sorted(columns + [(min(xs) - 2.0, "date")])
            names = [n for _, n in columns]
            inferred.append("date")

    canonical = ["amount", "balance"] if "amount" in names else ["debit", "credit", "balance"]
    missing = [n for n in canonical if n not in names]
    if not missing:
        return columns, inferred

    text_x = [x for x, n in columns if n in _TEXT_COLUMNS]
    tokens = []
    for ln in sample:
        for w in ln.words:
            digits = sum(ch.isdigit() for ch in w.text)
            if digits < 3 or digits > 10 or parse_money(w.text, True) is None:
                continue  # reference numbers are long digit runs; amounts are not
            if any(abs(w.x0 - x) <= mode.col_tol for x in text_x):
                continue  # left-aligned with a text column: a reference or a date, not an amount
            if text_x and w.x0 < max(text_x):
                continue
            tokens.append(w)
    if not tokens:
        return columns, inferred

    clusters: list[list[Word]] = []
    for w in sorted(tokens, key=lambda w: w.x1):
        if clusters and w.x1 - clusters[-1][-1].x1 <= 12.0:
            clusters[-1].append(w)
        else:
            clusters.append([w])
    clusters = [c for c in clusters if len(c) >= 2]  # a single stray token is not a column

    xs = [x for x, _ in columns]
    claimed: set[str] = set()
    unclaimed: list[float] = []
    for c in clusters:
        left = min(w.x0 for w in c)
        idx = max(bisect_right(xs, left + mode.col_tol) - 1, 0)
        owner = columns[idx][1]
        if owner in canonical and owner not in claimed:
            claimed.add(owner)
        else:
            unclaimed.append(left - 2.0)
    for x, name in zip(sorted(unclaimed), missing):
        columns.append((x, name))
        inferred.append(name)
    return sorted(columns), inferred


@dataclass
class TableHeader:
    start: int  # index of the first header line
    end: int  # index of the first line after the header band
    columns: list[tuple[float, str]]  # (left x, field name), sorted by x
    inferred: list[str] = field(default_factory=list)  # names inferred from content, not read from labels


def find_header(lines: list[Line], mode: Mode = DIGITAL) -> Optional[TableHeader]:
    """Locate the transaction table header, or return None.

    The header band may span up to three lines (for example 'Withdrawal' over 'Amt.'). In OCR mode damaged
    labels are matched fuzzily and columns whose header was lost are inferred from content
    (see ``_infer_columns``).
    """
    mapper = map_header_fuzzy if mode.tolerant else map_header
    for i, line in enumerate(lines):
        fields = {mapper(c.text) for c in _build_cells(line.words)} - {None}
        if mode.tolerant:
            if len(fields) < 3:
                continue
        elif "date" not in fields or len(fields) < 3:
            continue
        band = [line]
        j = i + 1
        while j < len(lines) and len(band) < 3:
            nxt = lines[j]
            if nxt.y0 - band[-1].y0 > 14 or _line_has_date(nxt, mode) or _line_has_amount(nxt, mode):
                break
            band.append(nxt)
            j += 1
        cells = _build_cells([w for ln in band for w in ln.words])
        columns: list[tuple[float, str]] = []
        seen: set[str] = set()
        for c in cells:
            name = mapper(c.text)
            if name and name not in seen:
                columns.append((c.x0, name))
                seen.add(name)
        if {"debit", "credit"} <= seen and "amount" in seen:
            columns = [(x, n) for x, n in columns if n != "amount"]  # a stray 'Amt.' fragment, not a column
        inferred: list[str] = []
        if mode.tolerant:
            columns, inferred = _infer_columns(columns, lines[j:], mode)
            if "date" not in {n for _, n in columns}:
                continue  # three labels but no date column anywhere: not the transaction table
        return TableHeader(i, j, sorted(columns), inferred)
    return None


def _assign(columns: list[tuple[float, str]], words: list[Word], col_tol: float) -> dict[str, list[Word]]:
    xs = [c[0] for c in columns]
    out: dict[str, list[Word]] = {}
    for w in words:
        idx = max(bisect_right(xs, w.x0 + col_tol) - 1, 0)
        out.setdefault(columns[idx][1], []).append(w)
    return out


# --------------------------------------------------------------------------- field parsing
def _conf(words: list[Word], repaired: bool, mode: Mode) -> float:
    if not mode.tolerant:
        return TEXT_CONF
    base = min((w.conf for w in words), default=0.0)
    return base * (REPAIR_PENALTY if repaired else 1.0)


def _fv(words: list[Word], text: str, value, conf: float, mode: Mode, repaired: bool = False,
        source: Optional[str] = None) -> FieldValue:
    fv = FieldValue(text=text, value=value, confidence=conf if value is not None else 0.0,
                    bbox=_bbox(words), source=source or mode.source)
    if repaired and value is not None:
        fv.flags.append("ocr_repaired")
    return fv


def _parse_date_cell(words: list[Word], mode: Mode) -> FieldValue:
    text = " ".join(w.text for w in words)
    if not mode.tolerant:
        return _fv(words, text, parse_date(text), TEXT_CONF, mode)
    parsed = parse_date_tolerant(text)
    if parsed is None:
        return _fv(words, text, None, 0.0, mode)
    return _fv(words, text, parsed.value, _conf(words, parsed.repaired, mode), mode, parsed.repaired)


def _money_words(words: list[Word]) -> list[Word]:
    """Words of a money cell, in reading order (amount first, then any Dr/Cr suffix)."""
    return sorted(words, key=lambda w: w.x0)


# --------------------------------------------------------------------------- markers
def _marker(label: str, cols: dict[str, list[Word]], page: int, mode: Mode) -> dict:
    low = label.lower()
    kind = "other"
    for key, name in (("opening", "opening"), ("closing", "closing"), ("brought", "brought_forward"),
                      ("carried", "carried_forward")):
        if key in low:
            kind = name
            break
    value = None
    for name in ("balance", "debit", "credit", "amount"):
        ws = cols.get(name, [])
        if ws:
            money = parse_money(" ".join(w.text for w in _money_words(ws)), mode.tolerant)
            if money is not None:
                value = money.value
                break
    return {"kind": kind, "label": label, "value": value, "page": page}


# --------------------------------------------------------------------------- transactions
def _build_txn(row: _Row, previous_balance: Optional[Decimal], mode: Mode) -> ExtractedTransaction:
    f: dict[str, FieldValue] = {}

    for name in ("date", "value_date"):
        ws = row.words.get(name, [])
        if ws:
            f[name] = _parse_date_cell(ws, mode)

    ws = row.words.get("description", [])
    if ws:
        text = " ".join(w.text for w in ws)
        fixed, snapped = snap_prefix(text) if mode.tolerant else (text, None)
        f["description"] = _fv(ws, text, fixed, _conf(ws, snapped is not None, mode), mode)
        if snapped:
            f["description"].flags.append("prefix_snapped")

    ws = row.words.get("ref", [])
    if ws:
        text = "".join(w.text for w in ws)  # references wrap mid-token, so join without spaces
        f["ref"] = _fv(ws, text, text, _conf(ws, False, mode), mode)

    if mode.tolerant and "description" in f and "ref" in f:
        desc, ref = f["description"], f["ref"]
        if desc.value and ref.value and reference_matches(str(desc.value), str(ref.value)):
            ref.confidence = max(ref.confidence, CROSS_VERIFIED_CONF)  # two independent reads agree
            ref.flags.append("matches_description")
            desc.flags.append("reference_matches")

    for name in ("debit", "credit"):
        ws = _money_words(row.words.get(name, []))
        if ws:
            text = " ".join(w.text for w in ws)
            money = parse_money(text, mode.tolerant)
            if money is None and not mode.tolerant:
                # strict: take the first well-formed amount token in the cell
                tokens = [w for w in ws if is_amount(w.text)]
                if tokens:
                    money = parse_money(tokens[0].text)
                    ws = tokens[:1]
                    text = tokens[0].text
            if money is not None:
                f[name] = _fv(ws, text, abs(money.value), _conf(ws, money.repaired, mode), mode, money.repaired)
            else:
                f[name] = _fv(ws, text, None, 0.0, mode)

    pending = None  # an unsigned single 'Amount' column, direction resolved from the balance change
    ws = _money_words(row.words.get("amount", []))
    if ws:
        text = " ".join(w.text for w in ws)
        money = parse_money(text, mode.tolerant)
        if money is None:
            f["debit"] = _fv(ws, text, None, 0.0, mode)  # unreadable; reported as unparseable
        else:
            conf = _conf(ws, money.repaired, mode)
            if money.value < 0:
                f["debit"] = _fv(ws, text, abs(money.value), conf, mode, money.repaired)
            elif money.suffix == "dr":
                f["debit"] = _fv(ws, text, money.value, conf, mode, money.repaired)
            elif money.suffix == "cr":
                f["credit"] = _fv(ws, text, money.value, conf, mode, money.repaired)
            else:
                pending = (ws, text, money)

    ws = _money_words(row.words.get("balance", []))
    if ws:
        text = " ".join(w.text for w in ws)
        money = parse_money(text, mode.tolerant)
        if money is None and not mode.tolerant:
            tokens = [w for w in ws if is_amount(w.text)]
            suffix = [w for w in ws if w.text.lower() in ("dr", "cr")]
            if tokens:
                money = parse_money(" ".join(w.text for w in tokens[:1] + suffix[:1]))
        if money is not None:
            value = -money.value if money.suffix == "dr" else money.value
            f["balance"] = _fv(ws, text, value, _conf(ws, money.repaired, mode), mode, money.repaired)
        else:
            f["balance"] = _fv(ws, text, None, 0.0, mode)

    if pending and "balance" in f and f["balance"].value is not None and previous_balance is not None:
        ws, text, money = pending
        name = "debit" if f["balance"].value < previous_balance else "credit"
        conf = min(INFERRED_CONF, _conf(ws, money.repaired, mode)) if mode.tolerant else INFERRED_CONF
        f[name] = _fv(ws, text, money.value, conf, mode, money.repaired, source="inferred")
    elif pending:
        ws, text, money = pending
        f["debit"] = _fv(ws, text, None, 0.0, mode)  # direction unknown without a readable balance

    return ExtractedTransaction(fields=f)


# --------------------------------------------------------------------------- account-level fields
# Account-level fields are anchored on their labels, not on word boundaries: OCR often merges a whole
# line into one token ('IFSC:SCBS0656525Branch:...') and reads the '|' separator as '1', '/' or 'I'.
_SEP = r"[|1/I]?"
_CODE = r"[A-Z]{4}[0O][A-Z0-9]{6}"
_IFSC_LABELLED = re.compile(rf"ifsc\s*[:\-]?\s*({_CODE})", re.I)
_IFSC_RE = re.compile(rf"\b({_CODE})\b")
_ACCOUNT_RE = re.compile(r"(?:account\s*(?:no\.?|number)|a/c\.?\s*(?:no\.?)?)\s*[:.]?\s*(\d{9,18})", re.I)
_OPEN_RE = re.compile(r"opening\s*balance\s*:?\s*(-?[\d,.:]*\d)", re.I)
_CLOSE_RE = re.compile(r"closing\s*balance\s*:?\s*(-?[\d,.:]*\d)", re.I)
_CURRENCY_RE = re.compile(r"currency\s*[:\-]?\s*([A-Z]{3})(?![A-Z])", re.I)
_HOLDER_LABELLED = re.compile(r"account\s*holder\s*(.+?)\s*account\s*no", re.I)
_HOLDER_NAME = re.compile(r"^name\s*[:.]\s*(.+)$", re.I)
_HOLDER_BEFORE_ACCOUNT = re.compile(rf"^(.+?)\s*{_SEP}\s*a/c", re.I)
_BRANCH_COLON = re.compile(r"branch\s*:\s*(.+)$", re.I)
_BRANCH_BEFORE_IFSC = re.compile(r"branch\s*(.+?)\s*ifsc", re.I)
_BRANCH_AFTER_IFSC = re.compile(rf"ifsc\s*[:\-]?\s*{_CODE}\s*{_SEP}\s*([A-Za-z].+)$", re.I)


def _parse_header(lines: list[Line], mode: Mode) -> dict[str, FieldValue]:
    texts = [ln.text for ln in lines]
    joined = "\n".join(texts)
    out: dict[str, FieldValue] = {}
    conf = HEADER_CONF if not mode.tolerant else 0.0

    def put(name: str, text: str, value, line_words: Optional[list[Word]] = None) -> None:
        if value is None or value == "" or name in out:
            return
        c = conf
        if mode.tolerant:
            c = min((w.conf for w in line_words), default=0.8) if line_words else 0.8
        out[name] = FieldValue(text=text, value=value, confidence=c, source=mode.source,
                               bbox=_bbox(line_words or []))

    if texts:
        put("bank_name", texts[0], texts[0].strip(), lines[0].words)

    if m := (_IFSC_LABELLED.search(joined) or _IFSC_RE.search(joined)):
        code = m.group(1).upper()
        put("ifsc", code, code[:4] + "0" + code[5:], _words_with(lines, m.group(1)))
    account_line = None
    for i, text in enumerate(texts):
        if m := _ACCOUNT_RE.search(text):
            put("account_number", m.group(1), m.group(1), _words_with(lines, m.group(1)))
            account_line = i
            break

    holder = None
    holder_line = None
    for i, text in enumerate(texts):
        if m := (_HOLDER_LABELLED.search(text) or _HOLDER_NAME.search(text) or _HOLDER_BEFORE_ACCOUNT.search(text)):
            holder, holder_line = m.group(1).strip(), i
            break
    if holder is None and account_line and account_line > 1:
        candidate = texts[account_line - 1].strip()
        if candidate and not any(ch.isdigit() for ch in candidate) and len(candidate) <= 60:
            holder, holder_line = candidate, account_line - 1
    if holder:
        put("account_holder", holder, holder, lines[holder_line].words if holder_line is not None else None)

    for i, text in enumerate(texts):
        if m := (_BRANCH_COLON.search(text) or _BRANCH_BEFORE_IFSC.search(text) or _BRANCH_AFTER_IFSC.search(text)):
            put("branch", m.group(1).strip(), m.group(1).strip(), lines[i].words)
            break

    for i, text in enumerate(texts):
        if "period" in text.lower():
            found = DATE_FIND_RE.findall(text)
            dates = [parse_date_tolerant(d) if mode.tolerant else parse_date(d) for d in found]
            dates = [d.value if mode.tolerant and d else d for d in dates]
            dates = [d for d in dates if d]
            if len(dates) >= 2:
                put("period_start", text, dates[0], lines[i].words)
                put("period_end", text, dates[1], lines[i].words)
                break

    for regex, name in ((_OPEN_RE, "opening_balance"), (_CLOSE_RE, "closing_balance")):
        for i, text in enumerate(texts):
            if m := regex.search(text):
                money = parse_money(m.group(1), mode.tolerant)
                if money is not None:
                    put(name, m.group(0), money.value, _words_with(lines, m.group(1)) or lines[i].words)
                break
    if m := _CURRENCY_RE.search(joined):
        put("currency", m.group(0), m.group(1).upper(), _words_with(lines, m.group(1)))
    elif re.search(r"\bINR\b", joined):
        put("currency", "INR", "INR", _words_with(lines, "INR"))
    return out


def _words_with(lines: list[Line], fragment: str) -> list[Word]:
    for line in lines:
        hits = [w for w in line.words if fragment in w.text or w.text in fragment and len(w.text) > 2]
        if hits:
            return hits
    return []


# --------------------------------------------------------------------------- shared engine
def extract_from_pages(pages: list[list[Line]], mode: Mode, source_file: str = "",
                       meta: Optional[dict] = None) -> ExtractedStatement:
    if not pages:
        raise ExtractionError("document has no pages")
    found = find_header(pages[0], mode)
    if found is None:
        raise ExtractionError(f"no transaction table header found on page 1 of {source_file}")
    header_end, columns, inferred_columns = found.end, found.columns, list(found.inferred)
    header = _parse_header(pages[0][:found.start], mode)

    rows: list[_Row] = []
    markers: list[dict] = []
    for pno, lines in enumerate(pages):
        if pno == 0:
            body = lines[header_end:]
        else:
            again = find_header(lines, mode)
            if again:
                columns = again.columns
                body = lines[again.end:]
            else:
                body = lines
        open_row: Optional[_Row] = None
        for line in body:
            cols = _assign(columns, line.words, mode.col_tol)
            date_text = " ".join(w.text for w in cols.get("date", []))
            money_cols = [w for name in ("debit", "credit", "amount", "balance") for w in cols.get(name, [])]
            label = " ".join(w.text for w in line.words if not is_amount(w.text)).strip()
            is_marker_label = any(k in label.lower() for k in _MARKER_WORDS)

            if not mode.tolerant:
                starts_row = bool(date_text) and parse_date(date_text) is not None
                has_amount = any(is_amount(w.text) for w in money_cols)
            else:
                has_amount = any(parse_money(w.text, True) is not None for w in money_cols)
                has_balance = any(parse_money(w.text, True) is not None for w in cols.get("balance", []))
                starts_row = (bool(date_text) and looks_like_date(date_text)) or (
                    has_balance and has_amount and len(money_cols) >= 2 and not is_marker_label)

            if starts_row and not is_marker_label:
                open_row = _Row(page=pno, last_y=line.y0)
                for name, ws in cols.items():
                    open_row.words.setdefault(name, []).extend(ws)
                rows.append(open_row)
            elif has_amount:
                markers.append(_marker(label, cols, pno, mode))
                open_row = None
            elif open_row is not None and line.y0 - open_row.last_y <= MAX_CONT_GAP:
                for name in ("description", "ref"):
                    open_row.words.setdefault(name, []).extend(cols.get(name, []))
                open_row.last_y = line.y0
            else:
                open_row = None  # footer or stray text ends any open transaction

    if "opening_balance" not in header:
        first_open = next((m for m in markers if m["kind"] == "opening" and m["value"] is not None), None)
        if first_open:
            header["opening_balance"] = FieldValue(text=first_open["label"], value=first_open["value"],
                                                   confidence=HEADER_CONF if not mode.tolerant else 0.8,
                                                   source=mode.source)
    if "closing_balance" not in header:
        last_close = next((m for m in reversed(markers) if m["kind"] == "closing" and m["value"] is not None), None)
        if last_close:
            header["closing_balance"] = FieldValue(text=last_close["label"], value=last_close["value"],
                                                   confidence=HEADER_CONF if not mode.tolerant else 0.8,
                                                   source=mode.source)

    transactions: list[ExtractedTransaction] = []
    previous: Optional[Decimal] = header["opening_balance"].value if "opening_balance" in header else None
    for row in rows:
        txn = _build_txn(row, previous, mode)
        transactions.append(txn)
        if txn.value("balance") is not None:
            previous = txn.value("balance")

    info = {"engine": mode.source, "columns": [name for _, name in columns], "inferred_columns": inferred_columns,
            "markers": [{k: str(v) if isinstance(v, Decimal) else v for k, v in m.items()} for m in markers]}
    info.update(meta or {})
    return ExtractedStatement(source_file=source_file, pages=len(pages), header=header,
                              transactions=transactions, meta=info)


# --------------------------------------------------------------------------- digital entry point
def extract_digital(path: str | Path) -> ExtractedStatement:
    path = Path(path)
    with pymupdf.open(path) as doc:
        pages = read_lines(doc)
    if sum(len(ln.words) for page in pages for ln in page) < MIN_WORDS_FOR_DIGITAL:
        raise NotDigitalError(f"{path.name} has no text layer")
    return extract_from_pages(pages, DIGITAL, path.name)
