"""Turn a question into a ``Query`` with plain rules, or say why it cannot.

Deliberately modest: it understands a fixed vocabulary of aggregates, spending words, transaction types, dates
and amounts, and it knows the payee names that actually occur in the data it is asked about. A question outside
that vocabulary is refused rather than guessed, because a confident wrong number is worse than "I can't answer
that".
"""

from __future__ import annotations

import calendar
import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable, Optional

from .data import Row
from .model import Query

MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
MONTHS["sept"] = 9
_MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))

NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}

UNSUPPORTED = re.compile(r"\b(will i|going to|forecast|predict|should i|can i afford|advice|recommend|why|weather|joke|"
                         r"who is|what is the capital|translate|write me|password|tax|invest)\b")
DATA_CUE = re.compile(r"\b(transactions?|payments?|balance|statement|account|money|rupees|spen[dt]|spending|paid|pay|"
                      r"debits?|credits?|withdraw\w*|deposit\w*|income|expenses?|received|earned|salary|upi|imps|neft|"
                      r"pos|atm|emi|loan|charges|fees?|interest|cash|bought|purchases?|outgoings?|outflows?|inflows?|came in|come in|"
                      r"coming in|expensive)\b|₹")

CATEGORY_WORDS = {
    "upi": r"\bupi\b", "imps": r"\bimps\b", "neft": r"\bneft\b", "pos": r"\bpos\b|card (?:swipes?|purchases?|payments?)",
    "atm": r"\batms?\b|cash withdrawals?", "emi": r"\bemis?\b|\bloan\b", "salary": r"\bsalary\b|\bsalaries\b|\bpayroll\b",
    "charges": r"\bcharges?\b|\bfees?\b|sms alert|maintenance|\bamc\b|\bgst\b", "interest": r"\binterest\b",
}


@dataclass
class Parsed:
    query: Optional[Query] = None
    notes: list[str] = field(default_factory=list)
    reason: Optional[str] = None


def known_terms(rows: Iterable[Row]) -> list[str]:
    """Payee and merchant names present in the data, longest first, so 'amazon pay' wins over 'amazon'."""
    terms: set[str] = set()
    for r in rows:
        if r.payee:
            terms.add(r.payee)
        if r.description.upper().startswith("POS "):
            words = r.description[4:].casefold().split()
            if len(words) >= 2:
                terms.add(" ".join(words[:-1]))   # the last word is the city
    return sorted((t for t in terms if len(t) >= 3), key=lambda t: (-len(t), t))


def _num(s: str) -> Decimal:
    return Decimal(s.replace(",", ""))


def _year_for_month(month: int, rows: list[Row], today: dt.date) -> tuple[int, Optional[str]]:
    years = sorted({r.date.year for r in rows if r.date.month == month})
    if not years:
        return today.year, None
    if len(years) == 1:
        return years[0], None
    return years[-1], f"No year given and {calendar.month_name[month]} appears in {', '.join(map(str, years))}; used {years[-1]}."


def _dates(q: str, rows: list[Row], today: dt.date, notes: list[str]) -> tuple[Optional[dt.date], Optional[dt.date]]:
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", q)
    if m:
        d = dt.date(int(m[1]), int(m[2]), int(m[3]))
        return d, d

    # "between 1 march and 15 march [2025]" / "from 1 march to 15 march"
    pair = re.search(rf"(?:between|from)\s+(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_RE})(?:\s+(\d{{4}}))?\s+(?:and|to|until|till)\s+"
                     rf"(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_RE})(?:\s+(\d{{4}}))?", q)
    if pair:
        d1, m1, y1, d2, m2, y2 = pair.groups()
        y2v = int(y2) if y2 else (int(y1) if y1 else _year_for_month(MONTHS[m2], rows, today)[0])
        y1v = int(y1) if y1 else y2v
        try:
            return dt.date(y1v, MONTHS[m1], int(d1)), dt.date(y2v, MONTHS[m2], int(d2))
        except ValueError:
            notes.append("Could not read the dates in that range.")

    day = re.search(rf"\b(?:on\s+)?(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_RE})(?:\s+(\d{{4}}))?\b", q) or \
        re.search(rf"\b(?:on\s+)?({_MONTH_RE})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b", q)
    if day:
        a, b, y = day.groups()
        d, mon = (int(a), MONTHS[b]) if a.isdigit() else (int(b), MONTHS[a])
        if 1 <= d <= 31:
            year = int(y) if y else _year_for_month(mon, rows, today)[0]
            try:
                date = dt.date(year, mon, d)
                return date, date
            except ValueError:
                pass

    m = re.search(rf"\b({_MONTH_RE})\b\s*,?\s*(\d{{4}})?", q)
    if m and not re.search(r"\bmay i\b|\bmay be\b", q):
        mon = MONTHS[m[1]]
        if m[2]:
            year = int(m[2])
        else:
            year, note = _year_for_month(mon, rows, today)
            if note:
                notes.append(note)
        return dt.date(year, mon, 1), dt.date(year, mon, calendar.monthrange(year, mon)[1])

    if re.search(r"\b(last|previous|past) month\b", q):
        first = today.replace(day=1) - dt.timedelta(days=1)
        return first.replace(day=1), first
    if re.search(r"\bthis month\b", q):
        return today.replace(day=1), today
    m = re.search(r"\b(?:last|past)\s+(\d{1,3})\s+days\b", q)
    if m:
        return today - dt.timedelta(days=int(m[1]) - 1), today
    if re.search(r"\blast year\b", q):
        return dt.date(today.year - 1, 1, 1), dt.date(today.year - 1, 12, 31)
    if re.search(r"\bthis year\b", q):
        return dt.date(today.year, 1, 1), today
    m = re.search(r"\b(?:in|during|for|of)\s+(20\d{2})\b", q)
    if m:
        return dt.date(int(m[1]), 1, 1), dt.date(int(m[1]), 12, 31)
    return None, None


# Words the rules either use or can safely ignore. A question with any other word is refused by name, because the
# word might have changed the meaning ("cash machines", "groceries", "last week") and a guess would be a wrong number.
NEUTRAL = set("""a an the i me my mine we our you your of on in at to for from by with and or is was were are be been am did do does done
have has had how what which who when whose much many total all any there that this these those it its as than per each every
please tell give show list get got made make during over under between until till since after before about around approximately
roughly only just also still now then so if not no yes can could would may might will shall up down out into onto off back
happened happen via through using altogether overall whole entire during within here these single big
amount amounts sum number numbers count counted times time often one ones thing things transactions transaction txn txns
money cash rupees rupee rs inr account accounts bank statement statements entries entry record records""".split())
DOMAIN = set("""spent spend spending spends paid pay pays payment payments debit debits debited credit credits credited
withdrew withdraw withdrawal withdrawals withdrawn received receive receives deposit deposits deposited income incoming earned earn
salary salaries payroll expense expenses expensive outgoing outgoings outflow outflows inflow inflows cost costs bought buy purchase
purchases charged charge charges fee fees interest refund refunds net saved savings difference flow cashflow balance
average avg mean typical largest biggest highest maximum max smallest lowest least cheapest minimum min top first most priciest
month months monthly year years day days week last previous past current closing ending end left remaining remain remains
category categories type types merchant merchants payee payees whom upi imps neft pos atm atms emi emis loan swipe swipes card
machine amc gst sms alert maintenance more less above below exceeding least most atleast greater higher lower
sent send lost lose put taken take took come came coming comes went going leaving split splits change changes breakdown wise
outstanding""".split())


def _unknown_words(q: str, rows: list[Row], extra: Iterable[str] = ()) -> list[str]:
    """Words in the question that no rule uses and that are not harmless filler."""
    payee_words = {w for t in known_terms(rows) for w in re.findall(r"[a-z]+", t)}
    skip = NEUTRAL | DOMAIN | payee_words | set(MONTHS) | set(extra)
    words = [w.split("'")[0] for w in re.findall(r"[a-z]+(?:'[a-z]+)?", re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", q))]
    words = [w for w in words if w]
    out = []
    for w in words:
        stem = w[:-1] if w.endswith("s") and len(w) > 3 else w
        if w in skip or stem in skip or re.fullmatch(r"(st|nd|rd|th)", w):
            continue
        if w not in out:
            out.append(w)
    return out


def _unused_numbers(q: str, lo: Optional[Decimal], hi: Optional[Decimal], limit: Optional[int]) -> list[str]:
    """Amounts of three or more digits that no filter took. Silently dropping one would answer a different question."""
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", q)
    used = {str(v) for v in (lo, hi, limit) if v is not None}
    out = []
    for m in re.finditer(r"(?<![\d.])\d[\d,]*(?:\.\d+)?", text):
        raw = m[0].rstrip(",")
        digits = raw.replace(",", "")
        if len(digits.split(".")[0]) < 3 or re.fullmatch(r"(19|20)\d{2}", digits):
            continue
        if any(Decimal(digits) == Decimal(u) for u in used):
            continue
        out.append(raw)
    return out


def parse(question: str, rows: list[Row], today: Optional[dt.date] = None) -> Parsed:
    q = " " + re.sub(r"[?!]", " ", question.lower()).replace("’", "'") + " "
    q = re.sub(r"\s+", " ", q)
    q = re.sub(r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\b", lambda m: str(NUMBER_WORDS[m[1]]), q)
    if UNSUPPORTED.search(q):
        return Parsed(reason="That is not a question about the transactions.")
    today = today or (max((r.date for r in rows), default=dt.date.today()))
    notes: list[str] = []

    # ---- what to compute
    top = re.search(r"\btop (\d+)\b|\b(\d+) (?:largest|biggest|highest|smallest|lowest|most expensive)\b|\bfirst (\d+)\b|"
                    r"\b(?:which|show|list|name|give me|what are)(?: me)?(?: the)? (\d+)\b(?! ?(?:of|days?|months?))", q)
    limit = int(next(g for g in top.groups() if g)) if top else 10
    asc = bool(re.search(r"\b(smallest|lowest|least|cheapest|minimum|min)\b", q))

    credit_w = re.search(r"\b(received|receive|credited|credits?|deposits?|deposited|income|earned|earn|incoming|inflows?|refunds?|salary|"
                         r"salaries|payroll)\b|\bmoney (?:come|came|coming|comes|going) in(?:to)?\b|\bcame in\b|\bcoming in\b", q)
    debit_w = re.search(r"\b(spent|spend|spending|paid|pay|payments?|debits?|debited|withdrew|withdrawals?|expenses?|outgoing|outgoings?|"
                        r"outflows?|costs?|cost|bought|purchases?|charged|expensive)\b|\bmoney (?:went|going|leaving|left) out\b", q)
    net_w = re.search(r"\b(net|saved|savings|difference|net change|cash ?flow)\b", q)
    balance_w = re.search(r"\bbalance\b", q)

    if re.search(r"balance (?:on|as of|at the end|after)|closing balance|ending balance|current balance|what (?:is|was) my balance|"
                 r"balance (?:at|by) the end|(?:left|remaining|remains?) in (?:my|the) account|money (?:i have )?left", q):
        aggregate, measure = "last", "balance"
    elif re.search(r"\b(how many|number of|count of|count|how often|how many times)\b", q):
        aggregate = "count"
        measure = "credit" if credit_w and not debit_w else "debit" if debit_w and not credit_w else "net"
    elif re.search(r"\b(average|avg|mean|typical)\b", q):
        aggregate = "avg"
        measure = "balance" if balance_w else "credit" if credit_w and not debit_w else "debit"
    elif re.search(r"\b(list|show|which|what were|name the|give me)\b|^ any\b", q) or (top and not re.search(r"merchant|payee|people|person", q)):
        aggregate = "list"
        measure = "credit" if credit_w and not debit_w else "debit" if debit_w else "net"
    elif re.search(r"\b(largest|biggest|highest|maximum|max|most expensive|priciest|top)\b", q):
        aggregate = "max"
        measure = "balance" if balance_w else "credit" if credit_w and not debit_w else "debit"
    elif asc:
        aggregate = "min"
        measure = "balance" if balance_w else "credit" if credit_w and not debit_w else "debit"
    elif net_w:
        aggregate, measure = "sum", "net"
    else:
        aggregate = "sum"
        measure = "credit" if credit_w and not debit_w else "debit"

    # ---- filters
    categories = [c for c, pat in CATEGORY_WORDS.items() if re.search(pat, q)]
    if categories == ["interest"] and not re.search(r"\bloan\b|interest (?:charged|paid on)|charged", q) and aggregate != "last":
        measure = "credit"   # interest on a savings account is something the bank pays in
    if categories == ["salary"] and aggregate in ("sum", "list", "count", "max", "min", "avg"):
        measure = "credit"
    if "salary" in categories and measure == "debit" and not debit_w:
        measure = "credit"
    text: list[str] = []
    for term in known_terms(rows):
        if re.search(rf"(?<![a-z]){re.escape(term)}(?![a-z])", q):
            text.append(term)
            break

    date_from, date_to = _dates(q, rows, today, notes)

    min_amount = max_amount = None
    m = re.search(r"(?:over|above|more than|greater than|at least|exceeding|>=?)\s*(?:rs\.?|₹|inr)?\s*(\d[\d,]*(?:\.\d+)?)", q)
    if m:
        min_amount = _num(m[1])
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(?:rs\.?|₹|rupees)?\s*(?:or more|and above|or above|and over|or higher|\+)", q)
    if m and min_amount is None:
        min_amount = _num(m[1])
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(?:rs\.?|₹|rupees)?\s*(?:or less|and below|or below|or under|or lower)", q)
    if m:
        max_amount = _num(m[1])
    m = re.search(r"(?:under|below|less than|at most|up to|<=?)\s*(?:rs\.?|₹|inr)?\s*(\d[\d,]*(?:\.\d+)?)", q)
    if m:
        max_amount = _num(m[1])

    group_by = None
    if re.search(r"\b(per month|each month|by month|monthly|month[ -]by[ -]month|month-?wise|every month)\b", q):
        group_by = "month"
    elif re.search(r"\b(by|per|each) (?:category|type)\b|category-?wise|breakdown by type|split by type", q):
        group_by = "category"
    elif re.search(r"\b(by|per|each) (?:merchant|payee)\b|top (?:\d+ )?(?:merchants|payees)|who did i (?:pay|spend)|\bwhom\b", q):
        group_by = "payee"
    if group_by and aggregate in ("list", "last", "max", "min") and group_by != "month":
        aggregate = "sum"
    if group_by and aggregate in ("list", "last"):
        aggregate = "sum"
    if group_by == "month" and aggregate == "avg":
        return Parsed(reason="'Average per month' could mean the average transaction in each month or the average of the monthly "
                             "totals. Ask for the total each month, or the average payment in a named month.")

    stray = _unused_numbers(q, min_amount, max_amount, limit if top else None)
    if stray:
        return Parsed(reason=f"I saw the number {stray[0]} but could not tell how it applies to your question.")

    unknown = _unknown_words(q, rows)
    if unknown:
        return Parsed(reason="I did not understand " + ", ".join(f"'{w}'" for w in unknown[:3]) +
                             ". Rephrase with words like spend, received, UPI, ATM, a month, or a name from your statement.")

    has_cue = bool(DATA_CUE.search(q)) or bool(categories) or bool(text) or bool(top and group_by)
    if not has_cue or not (aggregate or categories or text):
        return Parsed(reason="I could not find anything about your transactions in that question.")

    if aggregate == "last" and date_from == date_to:
        date_from = None  # "balance on the 15th" means the last balance up to and including that day
    try:
        query = Query(aggregate=aggregate, measure=measure, date_from=date_from, date_to=date_to, categories=categories,
                      text=text, min_amount=min_amount, max_amount=max_amount, group_by=group_by, limit=limit,
                      order="asc" if asc else "desc")
    except ValueError as exc:
        return Parsed(reason=f"I could not turn that into a valid question ({exc}).")
    return Parsed(query=query, notes=notes)
