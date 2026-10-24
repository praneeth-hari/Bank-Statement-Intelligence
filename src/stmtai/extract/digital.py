"""Extract a bank statement from a digital PDF using its text layer and word positions.

No layout-specific code. The extractor:

1. groups words into visual lines,
2. finds the table header band and turns each header cell into a column (date, description, debit, ...),
3. assigns every later word to a column by its x position,
4. starts a new transaction on every line with a date in the date column, and appends wrapped lines
   (no date, no amount) to the open transaction,
5. treats lines with amounts but no date as markers (opening / carried-forward / closing rows, summary boxes),
6. reads account-level fields from the text above the table.

Every field keeps its text, parsed value, confidence and bounding box, so the review UI can highlight it.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pymupdf

from .models import BBox, ExtractedStatement, ExtractedTransaction, FieldValue
from .parse import DATE_FIND_RE, is_amount, parse_amount, parse_date

LINE_TOL = 3.0  # words whose tops differ by less than this are on the same line (points)
CELL_GAP = 8.0  # header words closer than this belong to the same header cell
COL_TOL = 4.0  # a word belongs to a column if its left edge is within this of the header's left edge
MAX_CONT_GAP = 13.0  # max vertical distance between a wrapped line and the line above it
MIN_WORDS_FOR_DIGITAL = 20

TEXT_CONF = 0.99
HEADER_CONF = 0.97
INFERRED_CONF = 0.90


class NotDigitalError(Exception):
    """The PDF has no usable text layer (it is a scan)."""


class ExtractionError(Exception):
    """The document looks digital but the transaction table could not be located."""


@dataclass
class Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    page: int


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
        ordered = sorted(self.words, key=lambda w: (round(w.y0 / LINE_TOL), w.x0))
        return " ".join(w.text for w in ordered)


@dataclass
class _Row:
    page: int
    words: dict[str, list[Word]] = field(default_factory=dict)
    last_y: float = 0.0


# --------------------------------------------------------------------------- reading
def read_lines(doc: pymupdf.Document) -> list[list[Line]]:
    pages: list[list[Line]] = []
    for pno, page in enumerate(doc):
        words = [Word(x0, y0, x1, y1, t, pno) for x0, y0, x1, y1, t, *_ in page.get_text("words") if t.strip()]
        words.sort(key=lambda w: (w.y0, w.x0))
        lines: list[Line] = []
        for w in words:
            if not lines or w.y0 - lines[-1].y0 > LINE_TOL:
                lines.append(Line(pno, w.y0, [w]))
            else:
                lines[-1].words.append(w)
        for line in lines:
            line.words.sort(key=lambda w: w.x0)
        pages.append(lines)
    return pages


def _bbox(words: list[Word]) -> Optional[BBox]:
    if not words:
        return None
    return BBox(
        page=words[0].page,
        x0=min(w.x0 for w in words), y0=min(w.y0 for w in words),
        x1=max(w.x1 for w in words), y1=max(w.y1 for w in words),
    )


# --------------------------------------------------------------------------- table header
def map_header(text: str) -> Optional[str]:
    t = " ".join(text.lower().split())
    if "value" in t and "date" in t:
        return "value_date"
    if t in {"date", "txn date", "tran date", "trans date", "transaction date", "posting date"}:
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


def _build_cells(words: list[Word]) -> list[_Cell]:
    cells: list[_Cell] = []
    for w in sorted(words, key=lambda w: w.x0):
        if cells and w.x0 <= cells[-1].x1 + CELL_GAP:
            cells[-1].words.append(w)
            cells[-1].x1 = max(cells[-1].x1, w.x1)
        else:
            cells.append(_Cell(w.x0, w.x1, [w]))
    return cells


def _has_date(line: Line) -> bool:
    return bool(DATE_FIND_RE.search(line.text))


def _has_amount(line: Line) -> bool:
    return any(is_amount(w.text) for w in line.words)


def find_header(lines: list[Line]) -> Optional[tuple[int, int, list[tuple[float, str]]]]:
    """Return (first header line index, index after the header band, columns) or None.

    Columns are (left x, field name) sorted by x. The header band may span up to three lines
    (for example 'Withdrawal' over 'Amt.').
    """
    for i, line in enumerate(lines):
        fields = {map_header(c.text) for c in _build_cells(line.words)} - {None}
        if "date" not in fields or len(fields) < 3:
            continue
        band = [line]
        j = i + 1
        while j < len(lines) and len(band) < 3:
            nxt = lines[j]
            if nxt.y0 - band[-1].y0 > 14 or _has_date(nxt) or _has_amount(nxt):
                break
            band.append(nxt)
            j += 1
        cells = _build_cells([w for ln in band for w in ln.words])
        columns: list[tuple[float, str]] = []
        seen: set[str] = set()
        for c in cells:
            name = map_header(c.text)
            if name and name not in seen:
                columns.append((c.x0, name))
                seen.add(name)
        return i, j, sorted(columns)
    return None


def _assign(columns: list[tuple[float, str]], words: list[Word]) -> dict[str, list[Word]]:
    xs = [c[0] for c in columns]
    out: dict[str, list[Word]] = {}
    for w in words:
        idx = max(bisect_right(xs, w.x0 + COL_TOL) - 1, 0)
        out.setdefault(columns[idx][1], []).append(w)
    return out


# --------------------------------------------------------------------------- markers
def _marker(label: str, cols: dict[str, list[Word]], page: int) -> dict:
    low = label.lower()
    if "opening" in low:
        kind = "opening"
    elif "closing" in low:
        kind = "closing"
    elif "brought" in low:
        kind = "brought_forward"
    elif "carried" in low:
        kind = "carried_forward"
    else:
        kind = "other"
    candidates = [w for w in cols.get("balance", []) if is_amount(w.text)]
    if not candidates:
        candidates = [w for name in ("debit", "credit", "amount") for w in cols.get(name, []) if is_amount(w.text)]
    value = parse_amount(candidates[0].text) if candidates else None
    return {"kind": kind, "label": label, "value": value, "page": page}


# --------------------------------------------------------------------------- transactions
def _field(words: list[Word], text: str, value, conf: float = TEXT_CONF, source: str = "text_layer") -> FieldValue:
    return FieldValue(text=text, value=value, confidence=conf if value is not None else 0.0,
                      bbox=_bbox(words), source=source)


def _build_txn(row: _Row, previous_balance: Optional[Decimal]) -> ExtractedTransaction:
    f: dict[str, FieldValue] = {}

    for name in ("date", "value_date"):
        ws = row.words.get(name, [])
        if ws:
            text = " ".join(w.text for w in ws)
            f[name] = _field(ws, text, parse_date(text))

    ws = row.words.get("description", [])
    if ws:
        text = " ".join(w.text for w in ws)
        f["description"] = _field(ws, text, text)

    ws = row.words.get("ref", [])
    if ws:
        text = "".join(w.text for w in ws)  # references wrap mid-token, so join without spaces
        f["ref"] = _field(ws, text, text)

    for name in ("debit", "credit"):
        tokens = [w for w in row.words.get(name, []) if is_amount(w.text)]
        if tokens:
            f[name] = _field(tokens[:1], tokens[0].text, parse_amount(tokens[0].text))

    pending = None  # an unsigned single 'Amount' column, direction resolved from the balance change
    ws = row.words.get("amount", [])
    tokens = [w for w in ws if is_amount(w.text)]
    if tokens:
        suffix_words = [w for w in ws if w.text.lower() in ("dr", "cr")]
        suffix = suffix_words[0].text.lower() if suffix_words else None
        value = parse_amount(tokens[0].text)
        box = tokens[:1] + suffix_words[:1]
        text = " ".join(w.text for w in box)
        if value is not None and value < 0:
            f["debit"] = _field(box, text, abs(value))
        elif suffix == "dr":
            f["debit"] = _field(box, text, value)
        elif suffix == "cr":
            f["credit"] = _field(box, text, value)
        else:
            pending = (box, text, value)

    ws = row.words.get("balance", [])
    tokens = [w for w in ws if is_amount(w.text)]
    if tokens:
        suffix_words = [w for w in ws if w.text.lower() in ("dr", "cr")]
        value = parse_amount(tokens[0].text)
        if value is not None and suffix_words and suffix_words[0].text.lower() == "dr":
            value = -value
        box = tokens[:1] + suffix_words[:1]
        f["balance"] = _field(box, " ".join(w.text for w in box), value)

    if pending and "balance" in f and f["balance"].value is not None and previous_balance is not None:
        box, text, value = pending
        name = "debit" if f["balance"].value < previous_balance else "credit"
        f[name] = _field(box, text, value, conf=INFERRED_CONF, source="inferred")

    return ExtractedTransaction(fields=f)


# --------------------------------------------------------------------------- account-level fields
_IFSC_RE = re.compile(r"\b([A-Z]{4}0[A-Z0-9]{6})\b")
_ACCOUNT_RE = re.compile(r"(?:account\s*(?:no\.?|number)|a/c\.?\s*(?:no\.?)?)\s*:?\s*(\d{9,18})", re.I)
_OPEN_RE = re.compile(r"opening\s+balance\s*:?\s*(-?[\d,]+\.\d{2})", re.I)
_CLOSE_RE = re.compile(r"closing\s+balance\s*:?\s*(-?[\d,]+\.\d{2})", re.I)
_HOLDER_LABELLED = re.compile(r"account\s+holder\s+(.+?)\s+account\s+no", re.I)
_HOLDER_NAME = re.compile(r"^name\s*:\s*(.+)$", re.I)
_HOLDER_BEFORE_ACCOUNT = re.compile(r"^(.+?)\s*\|\s*a/c", re.I)
_BRANCH_COLON = re.compile(r"branch\s*:\s*(.+)$", re.I)
_BRANCH_BEFORE_IFSC = re.compile(r"branch\s+(.+?)\s+ifsc", re.I)
_BRANCH_AFTER_IFSC = re.compile(r"ifsc\s+\w+\s*\|\s*(.+)$", re.I)


def _parse_header(lines: list[Line]) -> dict[str, FieldValue]:
    texts = [ln.text for ln in lines]
    joined = "\n".join(texts)
    out: dict[str, FieldValue] = {}

    def put(name: str, text: str, value) -> None:
        if value is not None and value != "" and name not in out:
            out[name] = FieldValue(text=text, value=value, confidence=HEADER_CONF)

    if texts:
        put("bank_name", texts[0], texts[0].strip())

    if m := _IFSC_RE.search(joined):
        put("ifsc", m.group(1), m.group(1))
    account_line = None
    for i, text in enumerate(texts):
        if m := _ACCOUNT_RE.search(text):
            put("account_number", m.group(1), m.group(1))
            account_line = i
            break

    holder = None
    for text in texts:
        if m := (_HOLDER_LABELLED.search(text) or _HOLDER_NAME.search(text) or _HOLDER_BEFORE_ACCOUNT.search(text)):
            holder = m.group(1).strip()
            break
    if holder is None and account_line and account_line > 1:
        candidate = texts[account_line - 1].strip()
        if candidate and not any(ch.isdigit() for ch in candidate) and len(candidate) <= 60:
            holder = candidate
    put("account_holder", holder or "", holder)

    for text in texts:
        if m := (_BRANCH_COLON.search(text) or _BRANCH_BEFORE_IFSC.search(text) or _BRANCH_AFTER_IFSC.search(text)):
            put("branch", m.group(1).strip(), m.group(1).strip())
            break

    for text in texts:
        if "period" in text.lower():
            dates = [parse_date(d) for d in DATE_FIND_RE.findall(text)]
            dates = [d for d in dates if d]
            if len(dates) >= 2:
                put("period_start", text, dates[0])
                put("period_end", text, dates[1])
                break

    if m := _OPEN_RE.search(joined):
        put("opening_balance", m.group(0), parse_amount(m.group(1)))
    if m := _CLOSE_RE.search(joined):
        put("closing_balance", m.group(0), parse_amount(m.group(1)))
    if re.search(r"\bINR\b", joined):
        put("currency", "INR", "INR")
    return out


# --------------------------------------------------------------------------- main entry point
def extract_digital(path: str | Path) -> ExtractedStatement:
    path = Path(path)
    with pymupdf.open(path) as doc:
        pages = read_lines(doc)
    if sum(len(ln.words) for page in pages for ln in page) < MIN_WORDS_FOR_DIGITAL:
        raise NotDigitalError(f"{path.name} has no text layer")

    found = find_header(pages[0])
    if found is None:
        raise ExtractionError(f"no transaction table header found on page 1 of {path.name}")
    header_start, header_end, columns = found
    header = _parse_header(pages[0][:header_start])

    rows: list[_Row] = []
    markers: list[dict] = []
    for pno, lines in enumerate(pages):
        if pno == 0:
            body = lines[header_end:]
        else:
            again = find_header(lines)
            if again:
                columns = again[2]
                body = lines[again[1]:]
            else:
                body = lines
        open_row: Optional[_Row] = None
        for line in body:
            cols = _assign(columns, line.words)
            date_text = " ".join(w.text for w in cols.get("date", []))
            has_date = bool(date_text) and parse_date(date_text) is not None
            has_amount = any(is_amount(w.text) for name in ("debit", "credit", "amount", "balance")
                             for w in cols.get(name, []))
            if has_date:
                open_row = _Row(page=pno, last_y=line.y0)
                for name, ws in cols.items():
                    open_row.words.setdefault(name, []).extend(ws)
                rows.append(open_row)
            elif has_amount:
                label = " ".join(w.text for w in line.words if not is_amount(w.text)).strip()
                markers.append(_marker(label, cols, pno))
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
                                                   confidence=HEADER_CONF)
    if "closing_balance" not in header:
        last_close = next((m for m in reversed(markers) if m["kind"] == "closing" and m["value"] is not None), None)
        if last_close:
            header["closing_balance"] = FieldValue(text=last_close["label"], value=last_close["value"],
                                                   confidence=HEADER_CONF)

    transactions: list[ExtractedTransaction] = []
    previous: Optional[Decimal] = header["opening_balance"].value if "opening_balance" in header else None
    for row in rows:
        txn = _build_txn(row, previous)
        transactions.append(txn)
        if txn.value("balance") is not None:
            previous = txn.value("balance")

    return ExtractedStatement(
        source_file=path.name,
        pages=len(pages),
        header=header,
        transactions=transactions,
        meta={"engine": "text_layer", "columns": [name for _, name in columns],
              "markers": [{k: str(v) if isinstance(v, Decimal) else v for k, v in m.items()} for m in markers]},
    )
