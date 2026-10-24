import re
from decimal import Decimal

import numpy as np
import pymupdf
import pytest

from stmtai.reconcile import reconcile
from stmtai.schema import Label, Statement
from stmtai.synth.generate import build_dataset
from stmtai.synth.layouts import LAYOUTS, render
from stmtai.synth.scan import PARAMS, SEVERITIES, degrade, make_scan, rasterize
from stmtai.synth.transactions import BANKS, generate_statement

AMOUNT = re.compile(r"\d[\d,]*\.\d{2}")


@pytest.mark.parametrize("seed", range(1, 25))
def test_generated_statement_reconciles(seed):
    st = generate_statement(seed, BANKS[seed % 4], months=1 + seed % 3)
    assert st.transactions, "statement should not be empty"
    assert reconcile(st) == []
    assert all(t.balance >= 0 for t in st.transactions)
    assert st.closing_balance == st.transactions[-1].balance


def test_generation_is_deterministic():
    a = generate_statement(7, BANKS[0], months=2)
    b = generate_statement(7, BANKS[0], months=2)
    c = generate_statement(8, BANKS[0], months=2)
    assert a.model_dump_json() == b.model_dump_json()
    assert a.model_dump_json() != c.model_dump_json()


def test_reconcile_detects_tampering():
    st = generate_statement(3, BANKS[0], months=1)
    tampered = Statement.model_validate(st.model_dump())
    tampered.transactions[5].balance += Decimal("100.00")
    issues = reconcile(tampered)
    assert any(i.kind == "balance_mismatch" and i.row == 5 for i in issues)


def _lines(page: pymupdf.Page) -> list[set[str]]:
    """Group words into visual lines (top to bottom) and keep the amount tokens of each."""
    buckets: dict[int, set[str]] = {}
    for x0, y0, x1, y1, word, *_ in page.get_text("words"):
        if AMOUNT.fullmatch(word):
            buckets.setdefault(round(y0 / 3), set()).add(word)
    return [buckets[k] for k in sorted(buckets)]


@pytest.mark.parametrize("layout", LAYOUTS, ids=lambda l: l.name)
def test_digital_pdf_text_matches_ground_truth(layout, tmp_path):
    st = generate_statement(11, layout.bank, months=2)
    pdf = tmp_path / "doc.pdf"
    render(layout.name, st, pdf)

    with pymupdf.open(pdf) as doc:
        assert len(doc) >= 2, "two months of data should span multiple pages"
        lines = [line for page in doc for line in _lines(page)]
        all_text = " ".join(page.get_text() for page in doc)

    assert st.account_number in all_text
    assert st.ifsc in all_text
    assert st.account_holder in all_text

    # Every transaction must appear, in order, on a line holding both its amount and its balance.
    cursor = 0
    for i, t in enumerate(st.transactions):
        amount = layout.fmt(t.debit if t.debit is not None else t.credit)
        balance = layout.fmt(t.balance)
        while cursor < len(lines) and not (amount in lines[cursor] and balance in lines[cursor]):
            cursor += 1
        assert cursor < len(lines), f"transaction {i} not found in order in {layout.name}"
        cursor += 1


def test_wrapped_layout_has_carry_forward_rows(tmp_path):
    layout = next(l for l in LAYOUTS if l.name == "wrapped_two_date")
    st = generate_statement(12, layout.bank, months=2)
    pdf = tmp_path / "d.pdf"
    render(layout.name, st, pdf)
    with pymupdf.open(pdf) as doc:
        text = " ".join(p.get_text() for p in doc)
    assert "Balance Brought Forward" in text
    assert "Balance Carried Forward" in text
    assert "Opening Balance" in text and "Closing Balance" in text


@pytest.mark.parametrize("severity", SEVERITIES)
def test_scan_is_image_only_and_degraded(severity, tmp_path):
    layout = LAYOUTS[0]
    st = generate_statement(21, layout.bank, months=1)
    digital = tmp_path / "d.pdf"
    scan = tmp_path / f"s_{severity}.pdf"
    render(layout.name, st, digital)
    make_scan(digital, scan, severity, seed=5)

    with pymupdf.open(digital) as d, pymupdf.open(scan) as s:
        assert len(s) == len(d)
        for page in s:
            assert page.get_text().strip() == "", "scan must not carry a text layer"
            assert len(page.get_images()) == 1

    clean = rasterize(digital, PARAMS[severity].dpi)[0]
    noisy = degrade(clean, np.random.default_rng(1), severity)
    assert noisy.shape == clean.shape
    assert float(np.abs(noisy.astype(int) - clean.astype(int)).mean()) > 1.0


def test_scan_is_deterministic(tmp_path):
    layout = LAYOUTS[1]
    st = generate_statement(31, layout.bank, months=1)
    digital = tmp_path / "d.pdf"
    render(layout.name, st, digital)
    a = degrade(rasterize(digital, 100)[0], np.random.default_rng(9), "medium")
    b = degrade(rasterize(digital, 100)[0], np.random.default_rng(9), "medium")
    assert np.array_equal(a, b)


def test_build_dataset_writes_labels_that_round_trip(tmp_path):
    manifest = build_dataset(tmp_path, per_layout=2, seed=100, scans=True)
    assert len(manifest) == 2 * len(LAYOUTS)
    assert (tmp_path / "manifest.csv").exists()
    for row in manifest:
        label = Label.model_validate_json((tmp_path / f"{row['doc_id']}.json").read_text())
        assert label.layout == row["layout"]
        assert len(label.statement.transactions) == row["transactions"]
        assert reconcile(label.statement) == []
        assert (tmp_path / f"{row['doc_id']}.pdf").exists()
        for sev in filter(None, row["scans"].split("|")):
            assert (tmp_path / f"{row['doc_id']}__scan_{sev}.pdf").exists()
