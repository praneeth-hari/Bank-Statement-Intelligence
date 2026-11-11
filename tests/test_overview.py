"""The dashboard and quality endpoints.

Expected dashboard numbers are computed here with plain loops over the true transactions of the synthetic
statements, not by the code under test. Quality numbers are checked against the committed evaluation reports.
"""

import datetime as dt
import json
from collections import defaultdict
from decimal import Decimal as D
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stmtai.api.app import Settings, create_app
from stmtai.api.overview import Source, build_overview
from stmtai.api.quality import load_quality
from stmtai.query.data import make_row, primary_category, tags_of
from stmtai.schema import Label
from stmtai.synth.generate import build_dataset

REPORTS = Path(__file__).resolve().parent.parent / "reports"
COUNTS = {"total": 1, "approved": 1, "awaiting": 0, "processing": 0, "failed": 0, "fields_to_review": 0}


def row(i, date, desc, debit=None, credit=None, balance="1000.00", sid="s1", name="a.pdf"):
    return make_row(sid, name, i, dt.date.fromisoformat(date), desc, None,
                    D(debit) if debit else None, D(credit) if credit else None, D(balance))


# ----------------------------------------------------------------------------- the pure function
def test_overview_numbers_and_ordering():
    rows = [row(0, "2025-04-03", "UPI/514627048281/HARSH CHAHAL", debit="5650.54", balance="100.00"),
            row(1, "2025-04-05", "SALARY ACME LTD", credit="50000.00", balance="50100.00"),
            row(2, "2025-05-01", "ECS/EMI HOME LOAN LN1", debit="23790.00", balance="26310.00"),
            row(3, "2025-05-02", "UPI/171822782489/IRCTC", debit="5650.54", balance="20659.46")]
    out = build_overview([Source("s1", "a.pdf", "Zephyr Bank", None, None, rows)], COUNTS)
    assert out["totals"] == {"debit": "35091.08", "credit": "50000.00", "transactions": 4, "debits": 3, "credits": 1}
    assert out["by_month"] == [{"month": "2025-04", "debit": "5650.54"}, {"month": "2025-05", "debit": "29440.54"}]
    assert [(t["type"], t["debit"], t["count"]) for t in out["by_type"]] == [("emi", "23790.00", 1), ("upi", "11301.08", 2)]
    assert [d["debit"] for d in out["largest_debits"]] == ["23790.00", "5650.54", "5650.54"]
    assert out["largest_debits"][1]["date"] < out["largest_debits"][2]["date"]   # a tie is broken by date, so the order is stable
    b = out["balances"][0]
    assert (b["first_balance"], b["last_balance"], b["bank"]) == ("100.00", "20659.46", "Zephyr Bank")
    assert (b["period_start"], b["period_end"]) == ("2025-04-03", "2025-05-02")   # no header period: falls back to the rows
    assert out["notes"] == []


def test_balances_are_listed_per_statement_never_added_and_totals_say_so():
    a = [row(0, "2025-04-01", "UPI/1/X", debit="10.00", balance="90.00", sid="a", name="a.pdf")]
    b = [row(0, "2025-04-01", "UPI/2/Y", debit="20.00", balance="480.00", sid="b", name="b.pdf")]
    out = build_overview([Source("a", "a.pdf", None, None, None, a), Source("b", "b.pdf", None, None, None, b)], COUNTS)
    assert [x["last_balance"] for x in out["balances"]] == ["90.00", "480.00"]
    assert out["totals"]["debit"] == "30.00" and "different accounts" in out["notes"][0]


def test_amounts_stay_exact_decimals():
    rows = [row(i, "2025-04-01", "UPI/1/X", debit="0.10") for i in range(3)] + [row(3, "2025-04-02", "UPI/1/X", debit="0.20")]
    out = build_overview([Source("s1", "a.pdf", None, None, None, rows)], COUNTS)
    assert out["totals"]["debit"] == "0.50"   # 0.1 + 0.1 + 0.1 + 0.2 in floating point is 0.5000000000000001


def test_nothing_approved_gives_an_honest_empty_overview():
    out = build_overview([], {**COUNTS, "approved": 0, "awaiting": 2})
    assert out["has_data"] is False and out["totals"]["transactions"] == 0 and out["by_month"] == [] and out["balances"] == []


# ----------------------------------------------------------------------------- the endpoint
@pytest.fixture(scope="module")
def data(tmp_path_factory):
    d = tmp_path_factory.mktemp("overviewdata")
    build_dataset(d, per_layout=2, seed=950, scans=False)
    return d


def upload_all(client, data, n):
    out = []
    for lp in sorted(data.glob("classic_grid*.json"))[:n]:
        label = Label.model_validate_json(lp.read_text(encoding="utf-8"))
        with open(data / f"{label.doc_id}.pdf", "rb") as f:
            sid = client.post("/statements", files={"file": (f"{label.doc_id}.pdf", f, "application/pdf")}).json()["id"]
        out.append((sid, label))
    return out


def make_client(tmp_path, **kw):
    return TestClient(create_app(Settings(data_dir=tmp_path / "api", ocr_cache_dir=tmp_path / "cache", reports_dir=REPORTS, **kw)))


def test_overview_before_anything_is_approved(tmp_path, data):
    client = make_client(tmp_path)
    assert client.get("/overview").json()["has_data"] is False
    upload_all(client, data, 2)
    out = client.get("/overview").json()
    assert out["has_data"] is False and out["statements"]["total"] == 2 and out["statements"]["awaiting"] == 2
    assert out["statements"]["approved"] == 0


def test_overview_matches_plain_loops_over_the_true_transactions(tmp_path, data):
    client = make_client(tmp_path)
    pairs = upload_all(client, data, 2)
    for sid, _ in pairs:
        assert client.post(f"/statements/{sid}/approve").json()["approved"] is True
    out = client.get("/overview").json()
    txns = [(sid, label, t) for sid, label in pairs for t in label.statement.transactions]

    debit = sum((t.debit for _, _, t in txns if t.debit is not None), D(0))
    credit = sum((t.credit for _, _, t in txns if t.credit is not None), D(0))
    assert out["totals"]["debit"] == f"{debit:.2f}" and out["totals"]["credit"] == f"{credit:.2f}"
    assert out["totals"]["transactions"] == len(txns)
    assert out["totals"]["debits"] + out["totals"]["credits"] == len(txns)

    months = defaultdict(D)
    types = defaultdict(D)
    for _, _, t in txns:
        if t.debit is not None:
            months[t.date.strftime("%Y-%m")] += t.debit
            types[primary_category(tags_of(t.description))] += t.debit
    assert {m["month"]: m["debit"] for m in out["by_month"]} == {k: f"{v:.2f}" for k, v in sorted(months.items())}
    assert {t["type"]: t["debit"] for t in out["by_type"]} == {k: f"{v:.2f}" for k, v in types.items()}
    assert [t["debit"] for t in out["by_type"]] == sorted((t["debit"] for t in out["by_type"]), key=D, reverse=True)

    top = sorted((t.debit for _, _, t in txns if t.debit is not None), reverse=True)[:6]
    assert [D(d["debit"]) for d in out["largest_debits"]] == top

    assert len(out["balances"]) == 2
    for (sid, label), b in zip(pairs, sorted(out["balances"], key=lambda x: [p[0] for p in pairs].index(x["statement_id"]))):
        assert b["statement_id"] == sid
        assert b["first_balance"] == f"{label.statement.transactions[0].balance:.2f}"
        assert b["last_balance"] == f"{label.statement.transactions[-1].balance:.2f}"
        assert b["bank"].casefold() == label.statement.bank_name.casefold()   # printed in capitals; the UI changes the case, not the API
    assert any("different accounts" in n for n in out["notes"])


def test_only_approved_statements_count(tmp_path, data):
    client = make_client(tmp_path)
    (a, _), (b, label_b) = upload_all(client, data, 2)
    client.post(f"/statements/{b}/approve")
    out = client.get("/overview").json()
    assert out["statements"] == {"total": 2, "approved": 1, "awaiting": 1, "processing": 0, "failed": 0, "fields_to_review": 0}
    assert out["totals"]["transactions"] == len(label_b.statement.transactions)
    assert {x["statement_id"] for x in out["balances"]} == {b}


def test_overview_and_quality_respect_the_api_key(tmp_path):
    client = make_client(tmp_path, api_key="secret")
    for path in ("/overview", "/quality"):
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"X-API-Key": "secret"}).status_code == 200


# ----------------------------------------------------------------------------- quality
def test_quality_reads_the_saved_reports():
    q = load_quality(REPORTS)
    assert q["available"] and [c["id"] for c in q["conditions"]] == ["digital", "light", "medium", "heavy"]
    med = json.loads((REPORTS / "scan-medium" / "metrics.json").read_text())["overall"]["review"]
    m = q["headline"]
    assert (m["fields"], m["flagged"], m["wrong"], m["caught"]) == (
        med["fields_compared"], med["fields_flagged"], med["wrong_fields"], med["wrong_caught_by_flags"])
    assert (m["fields"], m["wrong"], m["caught"], m["missed"]) == (3337, 92, 68, 24)   # the figures the README states
    for c in q["conditions"]:
        o = c["outcomes"]
        assert sum(o.values()) == c["fields"] and min(o.values()) >= 0     # every field is in exactly one box
        assert o["flagged_wrong"] == c["caught"] and o["trusted_wrong"] == c["missed"]
    # the README says of the 24 misses 21 are descriptions, 2 account numbers and 1 the opening balance
    assert m["missed_by_field"] == {"description": 21, "account_number": 2, "opening_balance": 1}
    assert all(sum(c["missed_by_field"].values()) == c["missed"] for c in q["conditions"])
    digital = q["conditions"][0]
    assert digital["fields"] == 8078 and digital["flagged"] == 0 and digital["wrong"] == 0 and digital["error_recall"] is None
    assert len(q["names"]) == 5 and len(q["questions"]) == 3 and q["extras_source"]


def test_quality_with_no_reports_says_so_instead_of_inventing_numbers(tmp_path):
    q = load_quality(tmp_path)
    assert q["available"] is False and q["conditions"] == [] and q["headline"] is None and q["names"] == []


def test_quality_endpoint_includes_what_reviewers_did(tmp_path, data):
    client = make_client(tmp_path)
    body = client.get("/quality").json()
    assert body["available"] and body["reviewer"]["reviewed"] == 0 and "note" in body
