"""API tests. Run against a real SQLite file in a temp dir, a real PDF and the real pipeline - nothing mocked
except the OCR engine, which is replaced by a replay of the digital twin's text."""

import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from replay import ReplayBackend
from stmtai.api.app import Settings, create_app
from stmtai.api.service import coerce_value
from stmtai.extract.pipeline import extract_pdf
from stmtai.feedback import summarize
from stmtai.schema import Label
from stmtai.synth.generate import build_dataset


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    d = tmp_path_factory.mktemp("apidata")
    build_dataset(d, per_layout=1, seed=930, scans=True)
    return d


def _doc(data: Path, layout="classic_grid"):
    lp = sorted(data.glob(f"{layout}*.json"))[0]
    label = Label.model_validate_json(lp.read_text(encoding="utf-8"))
    return label, data / f"{label.doc_id}.pdf", data / f"{label.doc_id}__scan_light.pdf"


def make_client(tmp_path, **kw):
    cfg = Settings(data_dir=tmp_path / "api", ocr_cache_dir=tmp_path / "cache", **kw)
    app = create_app(cfg)
    return TestClient(app), app.state.store


def seed_broken(client, store, pdf: Path, mutate):
    """Register a statement whose raw extraction has a deliberate error, as if the extractor had misread it."""
    sid = store.create(pdf.name)
    shutil.copy(pdf, store.pdf_path(sid))
    raw = extract_pdf(pdf, scored=False)
    mutate(raw)
    store.set_ready(sid, raw)
    return sid


def upload(client, pdf: Path):
    with open(pdf, "rb") as f:
        r = client.post("/statements", files={"file": (pdf.name, f, "application/pdf")})
    return r


# ----------------------------------------------------------------------------- upload and read
def test_health_and_rejects_non_pdf(tmp_path):
    client, _ = make_client(tmp_path)
    assert client.get("/health").json()["status"] == "ok"
    r = client.post("/statements", files={"file": ("x.pdf", b"not a pdf at all", "application/pdf")})
    assert r.status_code == 415


def test_upload_extracts_and_serializes(tmp_path, data):
    label, pdf, _ = _doc(data)
    client, _ = make_client(tmp_path)
    r = upload(client, pdf)
    assert r.status_code == 202
    sid = r.json()["id"]
    body = client.get(f"/statements/{sid}").json()
    assert body["status"] == "ready" and len(body["transactions"]) == len(label.statement.transactions)
    first = body["transactions"][0]["fields"]
    assert first["date"]["value"] == label.statement.transactions[0].date.isoformat()
    assert Decimal(first["balance"]["value"]) == label.statement.transactions[0].balance
    assert body["pages"][0]["width"] > 0 and body["pages"][0]["image"].endswith("/pages/0.png")
    assert body["summary"]["reconciles"] is True and body["summary"]["fields_to_review"] == 0
    assert client.get(f"/statements/{sid}/review").json()["count"] == 0
    assert [s["id"] for s in client.get("/statements").json()] == [sid]


def test_page_image_is_a_png(tmp_path, data):
    _, pdf, _ = _doc(data)
    client, _ = make_client(tmp_path)
    sid = upload(client, pdf).json()["id"]
    r = client.get(f"/statements/{sid}/pages/0.png?dpi=60")
    assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get(f"/statements/{sid}/pages/99.png").status_code == 404


def test_oversized_upload_is_refused(tmp_path, data):
    _, pdf, _ = _doc(data)
    client, _ = make_client(tmp_path, max_upload_mb=0)
    assert upload(client, pdf).status_code == 413
    assert client.get("/statements").json() == []  # nothing half-stored


def test_api_key_is_enforced_when_configured(tmp_path, data):
    _, pdf, _ = _doc(data)
    client, _ = make_client(tmp_path, api_key="s3cret")
    assert client.get("/health").status_code == 200
    assert client.get("/statements").status_code == 401
    assert client.get("/statements", headers={"X-API-Key": "s3cret"}).status_code == 200


# ----------------------------------------------------------------------------- scans
def test_scan_goes_through_ocr(tmp_path, data):
    label, digital, scan = _doc(data)
    client, _ = make_client(tmp_path, ocr_backend=ReplayBackend(digital))
    body = client.get(f"/statements/{upload(client, scan).json()['id']}").json()
    assert body["status"] == "ready" and body["meta"]["ocr_engine"] == "replay"
    assert len(body["transactions"]) == len(label.statement.transactions)


def test_scan_with_ocr_disabled_fails_cleanly(tmp_path, data):
    _, _, scan = _doc(data)
    client, _ = make_client(tmp_path, ocr=False)
    sid = upload(client, scan).json()["id"]
    body = client.get(f"/statements/{sid}").json()
    assert body["status"] == "failed" and "NotDigitalError" in body["error"]
    assert client.get(f"/statements/{sid}/review").status_code == 409


# ----------------------------------------------------------------------------- the review loop
def _break_balance(raw):
    raw.transactions[5].fields["balance"].value += Decimal("10.00")


def _break_debit(raw):
    for t in raw.transactions[4:]:
        if t.value("debit") is not None:
            t.fields["debit"].value += Decimal("7.00")
            return


def test_a_wrong_balance_is_flagged_and_fixing_it_clears_the_queue(tmp_path, data):
    label, pdf, _ = _doc(data)
    client, store = make_client(tmp_path)
    sid = seed_broken(client, store, pdf, _break_balance)
    review = client.get(f"/statements/{sid}/review").json()
    assert review["count"] >= 1 and not review["reconciles"]
    keys = {i["key"] for i in review["items"]}
    assert "r5:balance" in keys
    item = next(i for i in review["items"] if i["key"] == "r5:balance")
    assert item["reasons"] and item["bbox"] is None or item["bbox"]["page"] == 0

    truth = label.statement.transactions[5].balance
    r = client.post(f"/statements/{sid}/corrections", json={"row": 5, "field": "balance", "action": "correct",
                                                             "value": f"{truth:,.2f}"})
    assert r.status_code == 201 and r.json()["remaining_to_review"] == 0 and r.json()["reconciles"] is True
    view = client.get(f"/statements/{sid}").json()
    fixed = view["transactions"][5]["fields"]["balance"]
    assert fixed["confidence"] == 1.0 and fixed["flags"] == ["human_corrected"] and Decimal(fixed["value"]) == truth


def test_accepting_a_suggestion_fixes_a_wrong_amount(tmp_path, data):
    label, pdf, _ = _doc(data)
    client, store = make_client(tmp_path)
    sid = seed_broken(client, store, pdf, _break_debit)
    items = client.get(f"/statements/{sid}/review").json()["items"]
    sug = next(i for i in items if i["suggestion"] is not None)
    r = client.post(f"/statements/{sid}/corrections", json={"row": sug["row"], "field": sug["field"],
                                                             "action": "accept_suggestion"})
    assert r.status_code == 201 and r.json()["remaining_to_review"] == 0
    truth = getattr(label.statement.transactions[sug["row"]], sug["field"])
    got = client.get(f"/statements/{sid}").json()["transactions"][sug["row"]]["fields"][sug["field"]]
    assert Decimal(got["value"]) == truth


def test_bad_input_is_rejected_with_a_message(tmp_path, data):
    _, pdf, _ = _doc(data)
    client, store = make_client(tmp_path)
    sid = seed_broken(client, store, pdf, _break_balance)
    post = lambda **b: client.post(f"/statements/{sid}/corrections", json=b)  # noqa: E731
    assert post(row=5, field="balance", action="correct", value="abc").status_code == 422
    assert post(row=0, field="date", action="correct", value="31/02/2025").status_code == 422
    assert post(row=5, field="balance", action="correct").status_code == 422
    assert post(row=0, field="balance", action="accept_suggestion").status_code == 422
    assert post(row=999, field="balance", action="confirm").status_code == 404
    assert client.get(f"/statements/{sid}/corrections").json() == []


def test_approval_needs_a_clean_queue_and_freezes_the_statement(tmp_path, data):
    label, pdf, _ = _doc(data)
    client, store = make_client(tmp_path)
    sid = seed_broken(client, store, pdf, _break_balance)
    blocked = client.post(f"/statements/{sid}/approve")
    assert blocked.status_code == 409 and blocked.json()["remaining_to_review"] >= 1
    truth = str(label.statement.transactions[5].balance)
    client.post(f"/statements/{sid}/corrections", json={"row": 5, "field": "balance", "action": "correct", "value": truth})
    assert client.post(f"/statements/{sid}/approve").json()["approved"] is True
    assert client.get("/statements").json()[0]["approved"] is True
    frozen = client.post(f"/statements/{sid}/corrections", json={"row": 0, "field": "description", "action": "confirm"})
    assert frozen.status_code == 409
    client.post(f"/statements/{sid}/reopen")
    assert client.post(f"/statements/{sid}/corrections",
                       json={"row": 0, "field": "description", "action": "confirm"}).status_code == 201


def test_undo_restores_the_queue(tmp_path, data):
    label, pdf, _ = _doc(data)
    client, store = make_client(tmp_path)
    sid = seed_broken(client, store, pdf, _break_balance)
    before = client.get(f"/statements/{sid}/review").json()["count"]
    truth = str(label.statement.transactions[5].balance)
    cid = client.post(f"/statements/{sid}/corrections",
                      json={"row": 5, "field": "balance", "action": "correct", "value": truth}).json()["id"]
    assert client.get(f"/statements/{sid}/review").json()["count"] == 0
    assert client.delete(f"/statements/{sid}/corrections/{cid}").status_code == 200
    assert client.get(f"/statements/{sid}/review").json()["count"] == before
    assert client.delete(f"/statements/{sid}/corrections/{cid}").status_code == 404


def test_export_reports_what_is_still_unreviewed(tmp_path, data):
    label, pdf, _ = _doc(data)
    client, store = make_client(tmp_path)
    sid = seed_broken(client, store, pdf, _break_balance)
    r = client.get(f"/statements/{sid}/export.csv")
    lines = r.text.strip().splitlines()
    assert len(lines) == len(label.statement.transactions) + 1
    assert lines[0].startswith("date,value_date,description,ref,debit,credit,balance,needs_review")
    assert int(r.headers["x-fields-needing-review"]) >= 1
    j = client.get(f"/statements/{sid}/export.json").json()
    assert j["fields_needing_review"] >= 1 and len(j["transactions"]) == len(label.statement.transactions)
    assert j["transactions"][5]["needs_review"] is True


def test_delete_removes_everything(tmp_path, data):
    _, pdf, _ = _doc(data)
    client, store = make_client(tmp_path)
    sid = upload(client, pdf).json()["id"]
    assert client.delete(f"/statements/{sid}").status_code == 204
    assert client.get(f"/statements/{sid}").status_code == 404
    assert not store.pdf_path(sid).exists()


# ----------------------------------------------------------------------------- feedback loop
def test_feedback_measures_flags_against_reviewer_behaviour(tmp_path, data):
    label, pdf, _ = _doc(data)
    client, store = make_client(tmp_path)
    sid = seed_broken(client, store, pdf, _break_balance)
    truth = str(label.statement.transactions[5].balance)
    c = lambda **b: client.post(f"/statements/{sid}/corrections", json=b)  # noqa: E731
    c(row=5, field="balance", action="correct", value=truth)          # flagged, really wrong
    c(row=2, field="description", action="confirm")                    # unflagged, fine
    c(row=3, field="description", action="correct", value="SOMETHING ELSE")  # unflagged, wrong: a missed error
    fb = client.get("/feedback").json()["overall"]
    assert fb["reviewed"] == 3 and fb["flagged_reviewed"] == 1 and fb["flagged_actually_wrong"] == 1
    assert fb["flag_precision"] == 1.0 and fb["unflagged_corrected"] == 1


def test_feedback_counts_only_the_latest_action_per_cell():
    base = dict(statement_id="a", row=1, field="balance", original_value="10.00", original_confidence=0.4,
                original_flags=[], was_flagged=True, had_suggestion=True)
    log = [{**base, "action": "correct", "new_value": "11.00"},
           {**base, "action": "accept_suggestion", "new_value": "12.00"}]
    fb = summarize(log)["overall"]
    assert fb["reviewed"] == 1 and fb["suggestions_accepted"] == 1 and fb["suggestion_accept_rate"] == 1.0
    assert summarize([])["overall"]["flag_precision"] is None


@pytest.mark.parametrize("field, text, expected", [
    ("balance", "1,23,456.7", Decimal("123456.70")),
    ("debit", "", None),
    ("date", "2025-04-03", __import__("datetime").date(2025, 4, 3)),
    ("date", "03/04/2025", __import__("datetime").date(2025, 4, 3)),
    ("description", "  UPI/123  ", "UPI/123"),
])
def test_coerce_value(field, text, expected):
    assert coerce_value(field, text) == expected


@pytest.mark.parametrize("field, text", [("balance", ""), ("balance", "x"), ("date", "yesterday")])
def test_coerce_value_rejects(field, text):
    with pytest.raises(ValueError):
        coerce_value(field, text)
