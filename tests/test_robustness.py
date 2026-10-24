from pathlib import Path

from stmtai.robustness import render_markdown, run
from stmtai.synth.generate import build_dataset


def test_robustness_detects_most_injected_errors(tmp_path: Path):
    build_dataset(tmp_path, per_layout=2, seed=700, scans=False)
    result = run(tmp_path, errors_per_doc=2, seed=1)
    assert result.docs > 0 and result.injected > 0
    d = result.as_dict()
    assert d["row_detection"] >= 0.9, d
    assert d["field_detection"] >= 0.85, d
    assert d["review_load"] < 0.05, "review should stay a small share of all fields"


def test_clean_documents_flag_nothing(tmp_path: Path):
    build_dataset(tmp_path, per_layout=1, seed=701, scans=False)
    result = run(tmp_path, errors_per_doc=0, seed=1)
    assert result.injected == 0
    assert result.fields_flagged == 0
    assert result.fields_total > 0


def test_report_renders(tmp_path: Path):
    build_dataset(tmp_path, per_layout=1, seed=702, scans=False)
    text = render_markdown([run(tmp_path, 1, seed=2)])
    assert "Field detection" in text and "|" in text
