import datetime as dt
from pathlib import Path

import pytest

from stmtai.benchmark import engine_tokens, export_from_cache, render, score_doc, score_engine
from stmtai.extract.ocr import CachedOnlyBackend, OCRUnavailableError, get_backend
from stmtai.synth.generate import build_dataset
from stmtai.schema import Label


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    d = tmp_path_factory.mktemp("bench")
    build_dataset(d, per_layout=1, seed=920, scans=False)
    return d


def _label(data: Path, layout="classic_grid") -> Label:
    return Label.model_validate_json(sorted(data.glob(f"{layout}*.json"))[0].read_text(encoding="utf-8"))


def _text_of(label: Label) -> str:
    lines = []
    for t in label.statement.transactions:
        lines += [t.date.strftime("%d/%m/%Y"), t.description, t.ref or ""]
        lines += [f"{v:,.2f}" for v in (t.debit, t.credit, t.balance) if v is not None]
    return "\n".join(lines)


def test_perfect_text_scores_full_recall(data):
    label = _label(data)
    r = score_doc(label, _text_of(label))
    assert r["amount_hit"] == r["amount_total"] > 0
    assert r["date_hit"] == r["date_total"]


def test_dropped_digit_lowers_recall_and_precision(data):
    label = _label(data)
    text = _text_of(label)
    broken = text.replace("0", "", 40)
    r = score_doc(label, broken)
    assert r["amount_hit"] < r["amount_total"]
    assert r["found_true"] < r["found_money"]


def test_month_name_dates_without_spaces_are_read(data):
    label = _label(data, "modern_zebra")
    text = "\n".join(t.date.strftime("%d%b%Y") for t in label.statement.transactions)
    r = score_doc(label, text)
    assert r["date_hit"] == r["date_total"]


def test_separators_do_not_matter_for_amount_matching():
    assert engine_tokens("1,23,456.78 and 123456.78")["amount"]["12345678"] == 2


def test_score_engine_and_render(data, tmp_path):
    label = _label(data)
    out = tmp_path / "eng"
    out.mkdir()
    (out / f"{label.doc_id}__scan_light.txt").write_text(_text_of(label), encoding="utf-8")
    r = score_engine(data, tmp_path, "eng", "scan_light")
    assert r and r["amount_recall"] == 1.0 and r["docs"] == 1
    assert score_engine(data, tmp_path, "eng", "scan_heavy") is None
    assert "| eng | light |" in render([r])


def test_cached_only_backend_refuses_to_run():
    be = get_backend("cached:unlimited-ocr")
    assert isinstance(be, CachedOnlyBackend) and be.name == "unlimited-ocr"
    with pytest.raises(OCRUnavailableError):
        be.read(None)


def test_unknown_backend_is_rejected():
    with pytest.raises(ValueError):
        get_backend("nope")
