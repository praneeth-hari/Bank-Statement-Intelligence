from decimal import Decimal

import pytest

from stmtai.evaluate import align, evaluate_dataset, evaluate_pair, summarize
from stmtai.extract.digital import NotDigitalError, extract_digital
from stmtai.extract.models import ExtractedTransaction, FieldValue, to_statement
from stmtai.extract.pipeline import extract_pdf
from stmtai.extract.scoring import review_items, score
from stmtai.reconcile import reconcile
from stmtai.schema import Label
from stmtai.synth.generate import build_dataset
from stmtai.synth.layouts import LAYOUTS, render
from stmtai.synth.scan import make_scan
from stmtai.synth.transactions import generate_statement


def _label(layout, st, seed) -> Label:
    return Label(doc_id=f"t_{layout.name}_{seed}", layout=layout.name, seed=seed,
                 fields_present=list(layout.fields), statement=st)


def _extract(layout, seed, tmp_path, months=2):
    st = generate_statement(seed, layout.bank, months=months)
    pdf = tmp_path / f"{layout.name}_{seed}.pdf"
    render(layout.name, st, pdf)
    return st, extract_digital(pdf)


# ----------------------------------------------------------------------------- extraction
@pytest.mark.parametrize("seed", [3, 9, 14])
@pytest.mark.parametrize("layout", LAYOUTS, ids=lambda l: l.name)
def test_digital_extraction_is_exact(layout, seed, tmp_path):
    st, ext = _extract(layout, seed, tmp_path, months=1 + seed % 3)
    ev = evaluate_pair(_label(layout, st, seed), score(ext))
    assert ev.examples == []
    assert ev.exact
    assert ev.matched_rows == len(st.transactions)
    assert to_statement(ext).transactions[0].balance == st.transactions[0].balance


@pytest.mark.parametrize("layout", LAYOUTS, ids=lambda l: l.name)
def test_extracted_fields_carry_bounding_boxes(layout, tmp_path):
    st, ext = _extract(layout, 5, tmp_path, months=1)
    for t in ext.transactions:
        for name, fv in t.fields.items():
            assert fv.bbox is not None, name
            assert fv.bbox.x1 > fv.bbox.x0 and fv.bbox.y1 > fv.bbox.y0


def test_scans_are_rejected_by_the_digital_path(tmp_path):
    layout = LAYOUTS[0]
    st = generate_statement(4, layout.bank, months=1)
    digital, scan = tmp_path / "d.pdf", tmp_path / "s.pdf"
    render(layout.name, st, digital)
    make_scan(digital, scan, "light", seed=1)
    with pytest.raises(NotDigitalError):
        extract_digital(scan)
    with pytest.raises(NotDigitalError):
        extract_pdf(scan, ocr=False)  # with OCR disabled the pipeline refuses rather than guessing


# ----------------------------------------------------------------------------- scoring
@pytest.mark.parametrize("layout", LAYOUTS, ids=lambda l: l.name)
def test_clean_statement_is_not_flagged(layout, tmp_path):
    _, ext = _extract(layout, 6, tmp_path)
    score(ext)
    assert review_items(ext) == []
    assert ext.meta["summary"]["reconciles"] is True
    assert ext.issues == []


def _first_row_with(ext, field, start):
    return next(i for i in range(start, len(ext.transactions)) if ext.transactions[i].value(field) is not None)


def test_wrong_amount_is_localized_to_that_row_amount(tmp_path):
    layout = LAYOUTS[1]
    _, ext = _extract(layout, 7, tmp_path)
    k = _first_row_with(ext, "debit", 10)
    ext.transactions[k].fields["debit"].value += Decimal("100.00")
    score(ext)
    flagged = {(r, f) for r, f, _, _ in review_items(ext)}
    assert (k, "debit") in flagged
    assert (k, "balance") not in flagged
    assert {r for r, _ in flagged} == {k}


def test_wrong_balance_is_localized_without_blaming_the_next_row(tmp_path):
    layout = LAYOUTS[2]
    _, ext = _extract(layout, 8, tmp_path)
    k = 12
    ext.transactions[k].fields["balance"].value += Decimal("50.00")
    score(ext)
    flagged = {(r, f) for r, f, _, _ in review_items(ext)}
    assert (k, "balance") in flagged
    assert not any(r == k + 1 for r, _ in flagged), "row after a bad balance is explained by it"
    assert {r for r, _ in flagged} <= {k}


def _corrupt_last_amount(ext):
    last = len(ext.transactions) - 1
    t = ext.transactions[last]
    name = "debit" if t.value("debit") is not None else "credit"
    true_value = t.fields[name].value
    t.fields[name].value += Decimal("10.00")
    return last, name, true_value


def test_error_in_last_row_is_resolved_by_the_closing_balance(tmp_path):
    _, ext = _extract(LAYOUTS[0], 9, tmp_path)
    last, name, true_value = _corrupt_last_amount(ext)
    score(ext)
    flagged = {(r, f) for r, f, _, _ in review_items(ext) if r == last}
    assert flagged == {(last, name)}, "closing balance agrees with the row balance, so the amount is wrong"
    fv = ext.transactions[last].fields[name]
    assert fv.suggestion == true_value and "suggestion_verified" in fv.flags


def test_error_in_last_row_without_closing_balance_flags_both(tmp_path):
    _, ext = _extract(LAYOUTS[0], 9, tmp_path)
    del ext.header["closing_balance"]
    last, name, _ = _corrupt_last_amount(ext)
    score(ext)
    flagged = {(r, f) for r, f, _, _ in review_items(ext) if r == last}
    assert (last, "balance") in flagged and (last, name) in flagged


def test_two_separate_errors_are_both_found(tmp_path):
    layout = LAYOUTS[3]
    _, ext = _extract(layout, 10, tmp_path)
    a = _first_row_with(ext, "debit", 5)
    b = _first_row_with(ext, "debit", 30)
    ext.transactions[a].fields["debit"].value += Decimal("1.00")
    ext.transactions[b].fields["debit"].value += Decimal("1.00")
    score(ext)
    assert {r for r, _, _, _ in review_items(ext)} == {a, b}


# ----------------------------------------------------------------------------- evaluation (negative controls)
def test_dropped_row_lowers_recall_but_alignment_survives(tmp_path):
    layout = LAYOUTS[0]
    st, ext = _extract(layout, 11, tmp_path)
    del ext.transactions[20]
    ev = evaluate_pair(_label(layout, st, 11), score(ext))
    n = len(st.transactions)
    assert ev.truth_rows == n and ev.got_rows == n - 1
    assert ev.matched_rows == n - 1, "rows after the dropped one must still align"
    assert not ev.exact
    s = summarize([ev])["overall"]
    assert s["row_recall"] < 1.0 and s["row_precision"] == 1.0


def test_spurious_row_lowers_precision(tmp_path):
    layout = LAYOUTS[1]
    st, ext = _extract(layout, 12, tmp_path)
    ext.transactions.insert(5, ExtractedTransaction(fields={
        "date": FieldValue(text="x", value=st.transactions[5].date, confidence=0.99),
        "description": FieldValue(text="JUNK", value="JUNK", confidence=0.99),
        "debit": FieldValue(text="1.00", value=Decimal("1.00"), confidence=0.99),
        "balance": FieldValue(text="9.00", value=Decimal("9.00"), confidence=0.99),
    }))
    ev = evaluate_pair(_label(layout, st, 12), ext)
    s = summarize([ev])["overall"]
    assert s["row_recall"] == 1.0 and s["row_precision"] < 1.0


def test_wrong_description_is_counted_and_reported(tmp_path):
    layout = LAYOUTS[2]
    st, ext = _extract(layout, 13, tmp_path)
    ext.transactions[3].fields["description"].value = "SOMETHING ELSE"
    ev = evaluate_pair(_label(layout, st, 13), ext)
    s = summarize([ev])["overall"]
    assert s["per_field_accuracy"]["description"] < 1.0
    assert s["per_field_accuracy"]["balance"] == 1.0
    assert ev.examples and ev.examples[0]["field"] == "description"


def test_review_loop_catches_injected_amount_errors(tmp_path):
    layout = LAYOUTS[3]
    st, ext = _extract(layout, 15, tmp_path)
    for k in (4, 15, 33):
        name = "debit" if ext.transactions[k].value("debit") is not None else "credit"
        ext.transactions[k].fields[name].value += Decimal("7.00")
    ev = evaluate_pair(_label(layout, st, 15), score(ext))
    review = summarize([ev])["overall"]["review"]
    assert review["wrong_fields"] == 3
    assert review["error_recall"] == 1.0
    assert review["flag_precision"] == 1.0


def test_alignment_handles_insert_and_delete():
    layout = LAYOUTS[0]
    st = generate_statement(21, layout.bank, months=1)
    truth = st.transactions
    got = [ExtractedTransaction(fields={
        "date": FieldValue(text="", value=t.date), "description": FieldValue(text="", value=t.description),
        "debit": FieldValue(text="", value=t.debit), "credit": FieldValue(text="", value=t.credit),
        "balance": FieldValue(text="", value=t.balance)}) for t in truth]
    del got[2]   # drops truth row 2
    del got[10]  # the list already shifted, so this drops truth row 11
    dropped = {2, 11}
    pairs = align(truth, got)

    matched = {i: j for i, j in pairs if i is not None and j is not None}
    assert set(matched) == set(range(len(truth))) - dropped
    assert [i for i, j in pairs if j is None] == sorted(dropped)
    assert not [j for i, j in pairs if i is None], "no spurious rows were introduced"
    for i, j in matched.items():
        assert j == i - sum(1 for d in dropped if d < i)


def test_evaluate_dataset_end_to_end(tmp_path):
    build_dataset(tmp_path, per_layout=2, seed=500, scans=False)
    docs = evaluate_dataset(tmp_path, "digital")
    assert len(docs) == 2 * len(LAYOUTS)
    s = summarize(docs)
    assert s["overall"]["exact_match_docs"] == 1.0
    assert s["overall"]["reconcile_rate"] == 1.0
    assert s["failures"] == []
    for st in (d for d in docs):
        assert st.error == ""


def test_reconcile_on_extracted_statement_matches_ground_truth(tmp_path):
    layout = LAYOUTS[3]
    st, ext = _extract(layout, 17, tmp_path)
    assert reconcile(to_statement(ext)) == []
