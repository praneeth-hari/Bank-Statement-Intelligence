"""The CSV download and the bundled samples."""

import csv
import datetime as dt
import io
from decimal import Decimal as D
from pathlib import Path

from fastapi.testclient import TestClient

from stmtai.api.app import Settings, create_app
from stmtai.api.transactions_export import COLUMNS, safe_text, transactions_csv
from stmtai.query.data import make_row
from stmtai.schema import Label

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def row(i, desc, debit=None, credit=None, balance="1000.00", sid="s1", name="a.pdf", ref=None):
    return make_row(sid, name, i, dt.date(2025, 4, 1 + i), desc, ref, D(debit) if debit else None, D(credit) if credit else None, D(balance))


def parse(text):
    return list(csv.DictReader(io.StringIO(text)))


def test_csv_columns_order_and_exact_money():
    rows = [row(0, "UPI/1/APOLLO PHARMACY", debit="0.10", balance="99.90"), row(1, "SALARY ACME", credit="50000", balance="50099.90")]
    out = parse(transactions_csv(rows))
    assert list(out[0].keys()) == COLUMNS
    assert [r["debit"] for r in out] == ["0.10", ""] and [r["credit"] for r in out] == ["", "50000.00"]
    assert [r["type"] for r in out] == ["upi", "salary"]
    assert [r["date"] for r in out] == ["2025-04-01", "2025-04-02"]


def test_csv_cannot_run_as_a_formula_in_a_spreadsheet():
    assert safe_text("=HYPERLINK(1)") == "'=HYPERLINK(1)" and safe_text("+1") == "'+1" and safe_text("@x") == "'@x"
    assert safe_text("UPI/1/X") == "UPI/1/X" and safe_text(None) == ""
    out = parse(transactions_csv([row(0, "-cmd|calc", debit="1.00", name="=x.pdf", ref="@r")]))[0]
    assert out["description"] == "'-cmd|calc" and out["statement"] == "'=x.pdf" and out["reference"] == "'@r"


def test_csv_quotes_commas_and_newlines_correctly():
    out = parse(transactions_csv([row(0, 'ACME, "PVT"\nLTD', debit="1.00")]))
    assert out[0]["description"] == 'ACME, "PVT"\nLTD'


def make_client(tmp_path, samples=SAMPLES, **kw):
    return TestClient(create_app(Settings(data_dir=tmp_path / "api", ocr_cache_dir=tmp_path / "cache", samples_dir=samples, **kw)))


def test_endpoint_refuses_when_nothing_is_approved(tmp_path):
    client = make_client(tmp_path)
    assert client.get("/transactions.csv").status_code == 409


def test_endpoint_matches_the_true_transactions(tmp_path):
    client = make_client(tmp_path)
    label = Label.model_validate_json((SAMPLES / "classic_grid_00.json").read_text(encoding="utf-8"))
    with open(SAMPLES / "classic_grid_00.pdf", "rb") as f:
        sid = client.post("/statements", files={"file": ("classic_grid_00.pdf", f, "application/pdf")}).json()["id"]
    assert client.get("/transactions.csv").status_code == 409          # uploaded but not approved: not exported
    assert client.post(f"/statements/{sid}/approve").json()["approved"] is True
    res = client.get("/transactions.csv")
    assert res.status_code == 200 and "attachment" in res.headers["content-disposition"]
    rows = parse(res.text)
    truth = label.statement.transactions
    assert len(rows) == len(truth)
    assert sum((D(r["debit"]) for r in rows if r["debit"]), D(0)) == sum((t.debit for t in truth if t.debit is not None), D(0))
    assert sum((D(r["credit"]) for r in rows if r["credit"]), D(0)) == sum((t.credit for t in truth if t.credit is not None), D(0))
    assert [r["balance"] for r in rows] == [f"{t.balance:.2f}" for t in truth]


def test_csv_respects_the_api_key(tmp_path):
    client = make_client(tmp_path, api_key="secret")
    assert client.get("/transactions.csv").status_code == 401
    assert client.post("/samples").status_code == 401


def test_samples_load_approve_and_do_not_duplicate(tmp_path):
    client = make_client(tmp_path)
    digital = sorted(p.name for p in SAMPLES.glob("*.pdf") if "__scan_" not in p.name)
    assert client.get("/health").json()["samples"] == len(digital) >= 3
    first = client.post("/samples").json()
    assert first["loaded"] == len(digital)
    assert {s["filename"] for s in first["statements"]} == set(digital)
    assert all(s["result"] == "approved" for s in first["statements"])      # generated statements, nothing left to review
    ov = client.get("/overview").json()
    assert ov["has_data"] and ov["statements"]["approved"] == len(digital)
    second = client.post("/samples").json()
    assert second["loaded"] == 0 and all(s["result"] == "already loaded" for s in second["statements"])
    assert client.get("/overview").json()["statements"]["total"] == len(digital)   # nothing doubled


def test_samples_missing_folder_is_reported_as_none(tmp_path):
    client = make_client(tmp_path, samples=tmp_path / "nope")
    assert client.get("/health").json()["samples"] == 0
    assert client.post("/samples").json() == {"statements": [], "loaded": 0}
