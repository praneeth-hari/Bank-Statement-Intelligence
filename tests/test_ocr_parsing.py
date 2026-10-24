"""OCR-path tests that need no OCR engine: tolerant parsing, deskew geometry, line grouping, scoring gaps."""

import datetime as dt
import math
from decimal import Decimal

import pytest

from stmtai.extract.digital import OCR, Word, group_lines
from stmtai.extract.models import ExtractedStatement, ExtractedTransaction, FieldValue
from stmtai.extract.ocr import OCRPage, estimate_skew, tokenize_page
from stmtai.extract.parse import looks_like_date, parse_date_tolerant, parse_money
from stmtai.extract.scoring import apply_suggestions, review_items, score


# ----------------------------------------------------------------------------- money
@pytest.mark.parametrize("text, value, suffix", [
    ("1,23,456.78", "123456.78", None),
    ("1,234.56 Dr", "1234.56", "dr"),
    ("247,105.25 Cr", "247105.25", "cr"),
])
def test_strict_money(text, value, suffix):
    m = parse_money(text)
    assert m.value == Decimal(value) and m.suffix == suffix and not m.repaired


@pytest.mark.parametrize("text, value, suffix", [
    ("1.84.243.76", "184243.76", None),   # commas read as periods
    ("5.650.54", "5650.54", None),
    ("178.59322", "178593.22", None),     # decimal point lost, a comma read as a period
    ("865054", "8650.54", None),          # every separator lost: the last two digits are paise
    ("13.810:00D", "13810.00", "dr"),     # colon for the decimal point, 'r' of the suffix lost
    ("2641086C", "26410.86", "cr"),
    ("1,O00.00", "1000.00", None),        # letter O for zero
])
def test_tolerant_money_recovers_ocr_damage(text, value, suffix):
    assert parse_money(text) is None, "strict mode must reject damaged text"
    m = parse_money(text, tolerant=True)
    assert m is not None
    assert m.value == Decimal(value) and m.suffix == suffix and m.repaired


@pytest.mark.parametrize("text", ["UPI/1234/ZOMATO", "Balance", "", "12", "AMOUNT"])
def test_tolerant_money_rejects_text(text):
    assert parse_money(text, tolerant=True) is None


# ----------------------------------------------------------------------------- dates
@pytest.mark.parametrize("text, expected, repaired", [
    ("03/04/2025", dt.date(2025, 4, 3), False),
    ("01 Jul 2026", dt.date(2026, 7, 1), False),
    ("01Jul2026", dt.date(2026, 7, 1), False),
    ("04-Nov-25", dt.date(2025, 11, 4), False),
    ("03042025", dt.date(2025, 4, 3), True),     # separators lost
    ("03:04:2025", dt.date(2025, 4, 3), True),   # slashes read as colons
    ("0BNoV25", dt.date(2025, 11, 8), True),     # B for 8, mixed-case month
    ("11-NOV25", dt.date(2025, 11, 11), True),
    ("12No-25", dt.date(2025, 11, 12), True),    # month truncated but unambiguous
])
def test_tolerant_dates(text, expected, repaired):
    parsed = parse_date_tolerant(text)
    assert parsed is not None and parsed.value == expected and parsed.repaired is repaired


@pytest.mark.parametrize("text", ["12Ju-25", "31/02/2025", "UPI/1234", "hello"])
def test_tolerant_dates_refuse_to_guess(text):
    assert parse_date_tolerant(text) is None  # 'Ju' is June or July; 31 Feb does not exist


def test_damaged_date_still_starts_a_row():
    assert looks_like_date("03:04:202")       # unparseable, but clearly a date cell
    assert not looks_like_date("SERVICES-SALARY")


# ----------------------------------------------------------------------------- geometry
def _quad(x, y, w, h, angle):
    c, s = math.cos(angle), math.sin(angle)
    pts = [(0, 0), (w, 0), (w, h), (0, h)]
    return [[x + px * c - py * s, y + px * s + py * c] for px, py in pts]


def test_skew_is_estimated_and_removed():
    angle = math.radians(2.5)
    # three columns of text on six rows, rotated as one page around the image centre
    segments = []
    cx, cy = 1000, 1400
    for row in range(6):
        for col, (x, w, text) in enumerate([(200, 300, "01/04/2025"), (700, 500, "UPI/1234/ZOMATO"),
                                            (1500, 220, "1,234.56")]):
            y = 600 + row * 40
            # rotate the box's origin about the page centre, and the box itself by the same angle
            dx, dy = x - cx, y - cy
            ox = cx + dx * math.cos(angle) - dy * math.sin(angle)
            oy = cy + dx * math.sin(angle) + dy * math.cos(angle)
            segments.append((_quad(ox, oy, w, 30, angle), text, 0.9))
    page = OCRPage(2000, 2800, 200, segments)
    assert math.degrees(estimate_skew(segments)) == pytest.approx(2.5, abs=0.05)

    tokens, skew = tokenize_page(page)
    assert skew == pytest.approx(2.5, abs=0.05)
    words = [Word(t.x0, t.y0, t.x1, t.y1, t.text, 0, t.conf, t.display) for t in tokens]
    lines = group_lines(words, OCR)
    assert len(lines) == 6, "after deskew each row is one line again"
    dates = [w for w in words if w.text == "01/04/2025"]
    assert max(d.x0 for d in dates) - min(d.x0 for d in dates) < 1.0, "the date column is vertical again"


def test_merged_suffix_is_split_into_its_own_word():
    page = OCRPage(1000, 1000, 72, [([[100, 100], [300, 100], [300, 120], [100, 120]], "5,373.14Dr", 0.9)])
    tokens, _ = tokenize_page(page)
    assert [t.text for t in tokens] == ["5,373.14", "Dr"]
    assert tokens[0].x1 <= tokens[1].x0


# ----------------------------------------------------------------------------- scoring across gaps
def _fv(value, conf=0.85):
    return FieldValue(text=str(value), value=value, confidence=conf, source="ocr")


def _statement(rows, opening="1000.00", closing=None):
    header = {"opening_balance": _fv(Decimal(opening))}
    if closing is not None:
        header["closing_balance"] = _fv(Decimal(closing))
    txns = []
    for kind, amount, balance in rows:
        fields = {"date": _fv(dt.date(2025, 4, 1))}
        if amount is not None:
            fields[kind] = _fv(Decimal(amount))
        elif kind:
            fields[kind] = FieldValue(text="??", value=None, confidence=0.0, source="ocr")
        fields["balance"] = _fv(Decimal(balance)) if balance is not None else FieldValue(
            text="??", value=None, confidence=0.0, source="ocr")
        txns.append(ExtractedTransaction(fields=fields))
    return ExtractedStatement(header=header, transactions=txns)


def test_chain_verification_lifts_low_ocr_confidence():
    ext = score(_statement([("debit", "100.00", "900.00"), ("credit", "50.00", "950.00")], closing="950.00"))
    flagged = {(r, f) for r, f, _, _ in review_items(ext)}
    assert not any(f in ("debit", "credit", "balance") for _, f in flagged)
    assert all(f == "date" for _, f in flagged), "dates are not covered by the chain"


def test_unreadable_amount_gets_a_verified_suggestion():
    ext = score(_statement([("debit", None, "900.00"), ("credit", "50.00", "950.00")], closing="950.00"))
    fv = ext.transactions[0].fields["debit"]
    assert fv.value is None and fv.suggestion == Decimal("100.00")
    assert "suggestion_verified" in fv.flags
    fixed = apply_suggestions(ext)
    assert fixed.transactions[0].value("debit") == Decimal("100.00")
    assert ext.transactions[0].value("debit") is None, "the original is never modified"


def test_unreadable_balance_is_bridged_and_corroborated():
    ext = score(_statement([("debit", "100.00", None), ("credit", "50.00", "950.00")], closing="950.00"))
    fv = ext.transactions[0].fields["balance"]
    assert fv.suggestion == Decimal("900.00") and "suggestion_verified" in fv.flags
    assert "chain_verified" in ext.transactions[1].fields["credit"].flags


def test_amount_on_the_wrong_side_is_moved():
    # OCR put a credit in the debit column; the balances say it was a credit
    ext = score(_statement([("debit", "100.00", "1100.00"), ("debit", "10.00", "1090.00")], closing="1090.00"))
    row = ext.transactions[0]
    assert row.fields["credit"].suggestion == Decimal("100.00")
    assert "suggest_clear" in row.fields["debit"].flags
    fixed = apply_suggestions(ext).transactions[0]
    assert fixed.value("credit") == Decimal("100.00") and fixed.value("debit") is None
