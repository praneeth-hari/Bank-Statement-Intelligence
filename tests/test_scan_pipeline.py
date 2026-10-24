"""Scan-path tests that need no OCR engine: a replay backend feeds the pipeline text from the digital twin."""

from pathlib import Path

import pytest

from stmtai.calibrate import sweep
from stmtai.evaluate import Label, evaluate_pair, values_equal
from stmtai.extract.ocr import ocr_pdf
from stmtai.extract.pipeline import extract_pdf
from stmtai.extract.scanned import extract_scan
from stmtai.extract.scoring import REVIEW_THRESHOLDS, REVIEW_THRESHOLD, review_items, score, threshold_for
from stmtai.extract.text import digit_runs, reference_matches, snap_prefix
from replay import ReplayBackend
from stmtai.synth.generate import build_dataset


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    d = tmp_path_factory.mktemp("scan")
    build_dataset(d, per_layout=1, seed=910, scans=True)
    return d


def _first(dataset: Path, layout: str = "classic_grid"):
    label_path = sorted(dataset.glob(f"{layout}*.json"))[0]
    label = Label.model_validate_json(label_path.read_text(encoding="utf-8"))
    return label, dataset / f"{label.doc_id}.pdf", dataset / f"{label.doc_id}__scan_light.pdf"


@pytest.mark.parametrize("layout", ["classic_grid", "modern_zebra", "drcr_single_amount", "wrapped_two_date"])
def test_scan_pipeline_with_clean_text_is_exact(dataset, layout):
    label, digital, scan = _first(dataset, layout)
    ext = extract_scan(scan, backend=ReplayBackend(digital))
    ev = evaluate_pair(label, ext, "scan_light")
    assert ev.matched_rows == ev.truth_rows == ev.got_rows
    assert ev.row_correct.get("balance") == ev.row_total["balance"]
    assert ext.meta["ocr_engine"] == "replay"


def test_pipeline_falls_back_to_ocr_for_scans_only(dataset):
    label, digital, scan = _first(dataset)
    backend = ReplayBackend(digital)
    ext = extract_pdf(scan, ocr_backend=backend, cache_dir=None)
    assert ext.meta.get("ocr_engine") == "replay" and backend.calls >= 1
    assert "ocr_engine" not in extract_pdf(digital, ocr_backend=ReplayBackend(digital)).meta


def test_ocr_results_are_cached(dataset, tmp_path):
    _, digital, scan = _first(dataset)
    first = ReplayBackend(digital)
    ocr_pdf(scan, first, cache_dir=tmp_path)
    second = ReplayBackend(digital)
    ocr_pdf(scan, second, cache_dir=tmp_path)
    assert first.calls >= 1 and second.calls == 0, "second run must come from the cache"


def test_damaged_digits_are_flagged_not_trusted(dataset):
    label, digital, scan = _first(dataset)
    ext_clean = extract_scan(scan, backend=ReplayBackend(digital))

    def mangle(t):  # drop a digit from long money cells that end in .xx
        return t[:-4] + t[-3:] if t.count(",") >= 2 and t[-3] == "." else t

    ext = score(extract_scan(scan, backend=ReplayBackend(digital, mangle)))
    wrong = [i for i, (a, b) in enumerate(zip(ext_clean.transactions, ext.transactions))
             if a.value("balance") != b.value("balance") or a.value("debit") != b.value("debit")]
    assert wrong, "the mangling must actually damage some amounts"
    flagged_rows = {r for r, *_ in review_items(ext) if r is not None}
    assert flagged_rows & set(wrong), "a damaged amount must reach the review queue"


# ----------------------------------------------------------------------------- text knowledge
@pytest.mark.parametrize("text, expected", [
    ("UP/123456789012 Swiggy", "UPI/123456789012 Swiggy"),
    ("UPV 123456789012", "UPI/123456789012"),
    ("IMP5/1234567890123", "IMPS/1234567890123"),
])
def test_snap_prefix_restores_rail(text, expected):
    fixed, used = snap_prefix(text)
    assert fixed == expected and used


@pytest.mark.parametrize("text", ["UPI/123456789012 ok", "UPPER 123456789012x", "Upstate Bank", "UP 12345"])
def test_snap_prefix_leaves_other_text_alone(text):
    fixed, used = snap_prefix(text)
    assert fixed == text and used is None


def test_reference_cross_check():
    assert digit_runs("UPI/123456789012/foo") == ["123456789012"]
    assert reference_matches("UPI/123456789012/foo", "123456789012")
    assert not reference_matches("UPI/123456789012/foo", "123456789013")
    assert not reference_matches("UPI/123456789012", "12345")


# ----------------------------------------------------------------------------- thresholds and calibration
def test_description_uses_its_own_threshold():
    assert threshold_for("description") == REVIEW_THRESHOLDS["description"] < REVIEW_THRESHOLD
    assert threshold_for("balance") == REVIEW_THRESHOLD


def test_sweep_trades_load_for_recall():
    pairs = [("description", 0.5, False), ("description", 0.85, False), ("description", 0.95, True),
             ("description", 0.99, True), ("balance", 0.1, False)]
    rows = {r["threshold"]: r for r in sweep(pairs, "description", (0.6, 0.9, 1.0))}
    assert rows[0.6]["review_load"] == 0.25 and rows[0.6]["error_recall"] == 0.5
    assert rows[0.9]["error_recall"] == 1.0 and rows[0.9]["review_load"] == 0.5
    assert rows[1.0]["review_load"] == 1.0


def test_values_equal_is_used_for_dates():
    import datetime as dt
    assert values_equal("date", dt.date(2025, 1, 2), dt.date(2025, 1, 2))
