"""Categories, the transactions search, and recurring payments.

Expected numbers come from plain loops over the true transactions of the synthetic statements, not from the code under test.
"""

import datetime as dt
from decimal import Decimal as D
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stmtai.api.app import Settings, create_app
from stmtai.api.categories import UNCATEGORISED, Rule, category_of, clean, first_rule
from stmtai.api.overview import Source, build_overview
from stmtai.api.recurring import clean_description, find_recurring
from stmtai.api.transactions import Filters
from stmtai.api.transactions import run as run_tx
from stmtai.query.data import make_row, primary_category, tags_of
from stmtai.schema import Label

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
REPORTS = Path(__file__).resolve().parent.parent / "reports"


def row(i, date, desc, debit=None, credit=None, balance="1000.00", sid="s1", name="a.pdf"):
    return make_row(sid, name, i, dt.date.fromisoformat(date), desc, None,
                    D(debit) if debit else None, D(credit) if credit else None, D(balance))


# ----------------------------------------------------------------------------- categories
def test_rules_ignore_case_and_the_oldest_match_wins():
    rules = [Rule(1, "pharmacy", "Health"), Rule(2, "APOLLO", "Shopping")]
    assert category_of("UPI/1/APOLLO PHARMACY", rules) == "Health"          # both match; rule 1 is older
    assert category_of("UPI/1/apollo store", rules) == "Shopping"
    assert category_of("UPI/1/SOMEONE ELSE", rules) == UNCATEGORISED         # never guessed
    assert first_rule("UPI/1/SOMEONE ELSE", rules) is None and category_of("x", []) == UNCATEGORISED


def test_rule_text_is_checked():
    assert clean("  APOLLO   PHARMACY ", " Health  ") == ("APOLLO PHARMACY", "Health")
    for bad in (("A", "Health"), ("x" * 41, "Health"), ("APOLLO", ""), ("APOLLO", "y" * 25), ("APOLLO", "uncategorised")):
        with pytest.raises(ValueError):
            clean(*bad)


def test_by_category_is_empty_without_rules_and_adds_up_with_them():
    rows = [row(0, "2025-04-01", "UPI/1/APOLLO PHARMACY", debit="10.10", balance="1"), row(1, "2025-04-02", "UPI/2/UNKNOWN", debit="0.20", balance="1"),
            row(2, "2025-04-03", "SALARY ACME", credit="500.00", balance="1")]
    counts = {"total": 1, "approved": 1, "awaiting": 0, "processing": 0, "failed": 0, "fields_to_review": 0}
    src = [Source("s1", "a.pdf", None, None, None, rows)]
    assert build_overview(src, counts)["by_category"] == []
    out = build_overview(src, counts, [Rule(1, "APOLLO", "Health")])
    assert out["by_category"] == [{"category": "Health", "debit": "10.10", "count": 1}, {"category": UNCATEGORISED, "debit": "0.20", "count": 1}]
    assert sum(D(c["debit"]) for c in out["by_category"]) == D(out["totals"]["debit"])


# ----------------------------------------------------------------------------- the search, as a pure function
ROWS = [row(0, "2025-04-01", "UPI/1/APOLLO PHARMACY", debit="100.00", balance="900.00"),
        row(1, "2025-04-02", "SALARY ACME LTD", credit="5000.00", balance="5900.00"),
        row(2, "2025-04-02", "UPI/2/IRCTC", debit="0.10", balance="5899.90"),
        row(3, "2025-04-02", "UPI/3/IRCTC", debit="0.20", balance="5899.70"),
        row(4, "2025-05-01", "ECS/EMI HOME LOAN LN1", debit="100.00", balance="5799.70"),
        row(0, "2025-04-09", "ATM WDL 55 PATNA", debit="2000.00", balance="10.00", sid="s2", name="b.pdf")]
RULES = [Rule(1, "IRCTC", "Travel"), Rule(2, "APOLLO", "Health")]


def ids(out):
    return [(r["statement_id"], r["row"]) for r in out["rows"]]


def test_each_filter_matches_a_plain_loop():
    def go(**kw):
        return run_tx(ROWS, RULES, Filters(**kw), 100, 0)
    assert go(q="irctc")["matched"] == 2 and go(q="  ") ["matched"] == 6
    assert go(date_from=dt.date(2025, 4, 2), date_to=dt.date(2025, 4, 9))["matched"] == 4
    assert go(min_amount=D("100"), max_amount=D("2000"))["matched"] == 3          # compares the amount, debit or credit
    assert go(type="upi")["matched"] == 3 and go(type="atm")["matched"] == 1
    assert go(direction="credit")["matched"] == 1 and go(direction="debit")["matched"] == 5
    assert go(statement_id="s2")["matched"] == 1
    assert go(category="travel")["matched"] == 2 and go(category=UNCATEGORISED)["matched"] == 3
    assert go(q="upi", direction="debit", category="Health")["matched"] == 1      # filters combine


def test_totals_are_exact_not_netted_and_facets_ignore_the_filter():
    out = run_tx(ROWS, RULES, Filters(q="irctc"), 100, 0)
    assert out["totals"] == {"debit": "0.30", "credit": "0.00", "debits": 2, "credits": 0}   # 0.1 + 0.2, exactly
    both = run_tx(ROWS, RULES, Filters(), 100, 0)
    assert both["totals"]["debit"] == "2200.30" and both["totals"]["credit"] == "5000.00"
    assert any("not netted" in n for n in both["notes"])
    assert [s["id"] for s in out["facets"]["statements"]] == ["s1", "s2"] and out["facets"]["categories"] == ["Health", "Travel", UNCATEGORISED]
    assert "atm" in out["facets"]["types"]


def test_sorting_is_stable_and_paging_covers_every_row_once():
    by_date = run_tx(ROWS, RULES, Filters(sort="date", order="desc"), 100, 0)
    assert [r["date"] for r in by_date["rows"]] == sorted((r["date"] for r in by_date["rows"]), reverse=True)
    same_day = [r["row"] for r in by_date["rows"] if r["date"] == "2025-04-02"]
    assert same_day == [1, 2, 3]                                                  # rows of one day stay in statement order
    by_amount = run_tx(ROWS, RULES, Filters(sort="amount", order="asc"), 100, 0)
    amounts = [D(r["debit"] or r["credit"]) for r in by_amount["rows"]]
    assert amounts == sorted(amounts)
    pages = [ids(run_tx(ROWS, RULES, Filters(), 2, off)) for off in (0, 2, 4)]
    assert sum(pages, []) == ids(run_tx(ROWS, RULES, Filters(), 100, 0)) and len(set(sum(pages, []))) == 6


def test_no_rows_is_an_honest_empty_result():
    out = run_tx([], [], Filters(), 100, 0)
    assert out["has_data"] is False and out["matched"] == 0 and out["rows"] == [] and out["totals"]["debit"] == "0.00"


# ----------------------------------------------------------------------------- recurring, as a pure function
def months(desc, amounts, day=5, start=(2025, 1), credit=False):
    out = []
    y, m = start
    for i, a in enumerate(amounts):
        out.append(row(i, f"{y}-{m:02d}-{day:02d}", desc.format(i), credit=a if credit else None, debit=None if credit else a))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def test_payee_is_the_description_without_its_numbers():
    assert clean_description("UPI/973530608279/AIRTEL PAYMENTS") == "UPI AIRTEL PAYMENTS"
    assert clean_description("ECS/EMI HOME LOAN LN21819600") == "ECS EMI HOME LOAN"
    assert clean_description("NEFT-N724238849696532-ORBITAL SOFTWARE PVT LTD-SALARY") == "NEFT ORBITAL SOFTWARE PVT LTD SALARY"


def test_a_monthly_payment_is_found_with_its_amounts_and_day():
    rows = months("ECS/EMI HOME LOAN LN{}77", ["15540.00"] * 4) + months("UPI/1{}/AIRTEL PAYMENTS", ["499.00", "499.00", "502.00", "505.00"], day=9)
    out = find_recurring(rows)
    emi, airtel = out["items"]                       # four months each; the larger total sorts first
    assert (emi["label"], emi["rail"], emi["direction"], emi["months"], emi["count"]) == ("EMI HOME LOAN", "ECS", "debit", 4, 4)
    assert (emi["amount_kind"], emi["low"], emi["total"], emi["day_of_month"]) == ("same", "15540.00", "62160.00", 5)
    assert (airtel["amount_kind"], airtel["low"], airtel["high"], airtel["day_of_month"]) == ("close", "499.00", "505.00", 9)
    assert find_recurring(months("UPI/1{}/VARIES", ["100.00", "300.00", "90.00"]))["items"][0]["amount_kind"] == "varies"


def test_salary_credits_repeat_too_and_directions_stay_apart():
    out = find_recurring(months("NEFT-N{}-ACME-SALARY", ["50000.00"] * 3, credit=True) + months("NEFT-N{}-ACME-SALARY", ["10.00"] * 3, day=20))
    assert sorted((i["direction"], i["total"]) for i in out["items"]) == [("credit", "150000.00"), ("debit", "30.00")]


def test_what_is_not_a_pattern_is_left_out():
    two_months = months("UPI/1{}/NETFLIX", ["199.00"] * 2)
    daily = [row(i, f"2025-0{1 + i // 3}-{1 + i % 3:02d}", "UPI/1/ZOMATO", debit="100.00") for i in range(9)]   # three a month
    out = find_recurring(two_months + daily + months("UPI/1{}/SPOTIFY", ["119.00"] * 3))
    assert [i["label"] for i in out["items"]] == ["SPOTIFY"]


def test_months_without_a_statement_are_not_counted_against_a_payment():
    gaps = [row(0, "2025-04-05", "UPI/1/JIO", debit="99.00"), row(1, "2025-08-05", "UPI/2/JIO", debit="99.00"), row(2, "2025-11-05", "UPI/3/JIO", debit="99.00")]
    assert find_recurring([r for r in gaps])["items"][0]["months"] == 3


def test_too_little_data_says_so_instead_of_guessing():
    out = find_recurring(months("UPI/1{}/NETFLIX", ["199.00"] * 2))
    assert out["items"] == [] and "At least 3 are needed" in out["reason"] and out["months_covered"] == 2
    assert find_recurring([])["has_data"] is False


# ----------------------------------------------------------------------------- the endpoints on the real samples
@pytest.fixture()
def client(tmp_path):
    c = TestClient(create_app(Settings(data_dir=tmp_path / "api", ocr_cache_dir=tmp_path / "cache", samples_dir=SAMPLES, reports_dir=REPORTS)))
    c.post("/samples")
    return c


@pytest.fixture(scope="module")
def truth():
    out = []
    for p in sorted(SAMPLES.glob("*.json")):
        label = Label.model_validate_json(p.read_text(encoding="utf-8"))
        if (SAMPLES / f"{label.doc_id}.pdf").exists():
            out += [(label.doc_id, t) for t in label.statement.transactions]
    return out


def test_search_matches_loops_over_the_true_transactions(client, truth):
    n = len(truth)
    assert client.get("/transactions?limit=500").json()["matched"] == n
    upi = [t for _, t in truth if "upi" in t.description.casefold()]
    out = client.get("/transactions", params={"q": "UPI", "limit": 500}).json()
    assert out["matched"] == len(upi) and D(out["totals"]["debit"]) == sum((t.debit for t in upi if t.debit), D(0))
    ranged = [t for _, t in truth if dt.date(2025, 4, 1) <= t.date <= dt.date(2025, 8, 31) and D("1000") <= (t.debit or t.credit) <= D("6000")]
    out = client.get("/transactions", params={"date_from": "2025-04-01", "date_to": "2025-08-31", "min_amount": "1000", "max_amount": "6000", "limit": 500}).json()
    assert out["matched"] == len(ranged)
    credits = [t for _, t in truth if t.credit is not None]
    assert client.get("/transactions", params={"direction": "credit"}).json()["matched"] == len(credits)
    paged = [r for off in range(0, n, 40) for r in client.get("/transactions", params={"limit": 40, "offset": off}).json()["rows"]]
    assert len(paged) == n and len({(r["statement_id"], r["row"]) for r in paged}) == n


def test_rules_drive_category_filter_and_the_dashboard_split(client, truth):
    assert client.get("/overview").json()["by_category"] == []                     # no rules yet, nothing pretended
    assert client.post("/categories", json={"pattern": "apollo", "category": "Health"}).status_code == 201
    assert client.post("/categories", json={"pattern": "PHARMEASY", "category": "Health"}).status_code == 201
    health = [t for _, t in truth if any(w in t.description.casefold() for w in ("apollo", "pharmeasy"))]
    got = client.get("/transactions", params={"category": "Health", "limit": 500}).json()
    assert got["matched"] == len(health) and {r["category"] for r in got["rows"]} == {"Health"}
    ov = client.get("/overview").json()
    spent = {c["category"]: D(c["debit"]) for c in ov["by_category"]}
    assert spent["Health"] == sum((t.debit for t in health if t.debit), D(0))
    assert sum(spent.values()) == D(ov["totals"]["debit"])                          # every debit lands in exactly one slice
    assert UNCATEGORISED in spent
    cats = client.get("/categories").json()
    assert [r["matches"] for r in cats["rules"]] == [sum(1 for _, t in truth if "apollo" in t.description.casefold()),
                                                     sum(1 for _, t in truth if "pharmeasy" in t.description.casefold())]
    assert cats["coverage"] == {"total": len(truth), "categorised": len(health)}
    assert all(s["pattern"] not in ("APOLLO", "PHARMEASY") and s["matches"] > 0 for s in cats["suggestions"])   # offered only if useful and new


def test_a_suggestion_counts_only_what_is_not_already_categorised(client, truth):
    sugg = {s["pattern"]: s["matches"] for s in client.get("/categories").json()["suggestions"]}
    assert sugg["APOLLO"] == sum(1 for _, t in truth if "apollo" in t.description.casefold())
    client.post("/categories", json={"pattern": "APOLLO", "category": "Health"})
    after = {s["pattern"]: s["matches"] for s in client.get("/categories").json()["suggestions"]}
    assert "APOLLO" not in after
    assert after.get("PHARMACY", 0) == sum(1 for _, t in truth if "pharmacy" in t.description.casefold() and "apollo" not in t.description.casefold())


def test_rule_endpoints_validate_and_delete(client):
    assert client.post("/categories", json={"pattern": "A", "category": "X"}).status_code == 422
    assert client.post("/categories", json={"pattern": "NETFLIX", "category": "uncategorised"}).status_code == 422
    rid = client.post("/categories", json={"pattern": "NETFLIX", "category": "Fun"}).json()["id"]
    assert client.post("/categories", json={"pattern": "netflix", "category": "Other"}).status_code == 409
    assert client.delete(f"/categories/{rid}").status_code == 204
    assert client.delete(f"/categories/{rid}").status_code == 404
    assert client.get("/categories").json()["rules"] == []


def test_bad_search_input_is_refused(client):
    for params in ({"date_from": "yesterday"}, {"limit": 0}, {"limit": 501}, {"offset": -1}, {"min_amount": "-1"},
                   {"min_amount": "lots"}, {"direction": "sideways"}, {"sort": "colour"}):
        assert client.get("/transactions", params=params).status_code == 422, params


def test_only_approved_statements_are_searched(tmp_path):
    c = TestClient(create_app(Settings(data_dir=tmp_path / "api", ocr_cache_dir=tmp_path / "cache", samples_dir=SAMPLES)))
    with open(SAMPLES / "classic_grid_00.pdf", "rb") as f:
        sid = c.post("/statements", files={"file": ("a.pdf", f, "application/pdf")}).json()["id"]
    assert c.get("/transactions").json()["has_data"] is False
    c.post(f"/statements/{sid}/approve")
    assert c.get("/transactions").json()["matched"] > 0


def test_recurring_on_the_samples_finds_the_loan_emi(client, truth):
    out = client.get("/recurring").json()
    emi_rows = [t for _, t in truth if t.description.startswith("ECS/EMI HOME LOAN")]
    assert out["has_data"] and out["months_covered"] >= 3 and "reason" not in out
    emi = next(i for i in out["items"] if i["label"] == "EMI HOME LOAN")
    assert emi["count"] == len(emi_rows) and emi["direction"] == "debit"
    assert D(emi["total"]) == sum((t.debit for t in emi_rows), D(0))
    assert emi["dates"] == sorted(t.date.isoformat() for t in emi_rows)


def test_new_endpoints_respect_the_api_key(tmp_path):
    c = TestClient(create_app(Settings(data_dir=tmp_path / "api", ocr_cache_dir=tmp_path / "cache", api_key="k")))
    for method, path in (("get", "/transactions"), ("get", "/categories"), ("get", "/recurring"), ("delete", "/categories/1")):
        assert getattr(c, method)(path).status_code == 401
    assert c.post("/categories", json={"pattern": "AB", "category": "X"}).status_code == 401
    assert c.get("/transactions", headers={"X-API-Key": "k"}).status_code == 200
