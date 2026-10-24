"""LLM fallback tests. A fake Ollama server speaks the real HTTP protocol; the model's answers are scripted so each
test can make it right, wrong, or hostile, and check that the validators and the failure handling hold."""

import datetime as dt
import json
from pathlib import Path

import pytest

from fake_ollama import FakeOllama
from stmtai.extract.models import FieldValue
from stmtai.extract.pipeline import extract_pdf
from stmtai.extract.scoring import review_items, score
from stmtai.llm.client import LLMUnavailable, OllamaClient, from_spec
from stmtai.llm.fallback import FLAG, candidates, llm_fallback
from stmtai.llm.validate import check_date, check_description
from stmtai.schema import Label
from stmtai.synth.generate import build_dataset


@pytest.fixture(scope="module")
def pdf(tmp_path_factory):
    d = tmp_path_factory.mktemp("llmdata")
    build_dataset(d, per_layout=1, seed=941, scans=False)
    lp = sorted(d.glob("classic_grid*.json"))[0]
    label = Label.model_validate_json(lp.read_text(encoding="utf-8"))
    return d / f"{label.doc_id}.pdf"


def damaged(pdf: Path):
    """A raw extraction with two damaged descriptions and one unreadable date, as a poor scan would give."""
    raw = extract_pdf(pdf, scored=False)
    t = raw.transactions
    for row, text in ((2, "UPI/310045678901/RCTC"), (3, "UPI/290011223344/DECATHL.N")):
        t[row].fields["description"] = FieldValue(text=text, value=text, confidence=0.6, source="ocr")
    true_date = t[5].value("date")
    t[5].fields["date"] = FieldValue(text=f"{true_date.day:02d}-{true_date.strftime('%b')[:2]}-{true_date.year % 100:02d}",
                                     value=None, confidence=0.0, source="ocr")
    return raw, true_date


def model(answers_text=None, answers_date=None):
    """A scripted model: maps the text it is shown to the text it should answer; echoes anything else."""
    answers_text, answers_date = answers_text or {}, answers_date or {}

    def respond(system, user, schema):
        items = [json.loads(line) for line in user.splitlines()]
        if "dates" in system.split("\n")[0]:
            return {"items": [{"id": i["id"], "date": answers_date.get(i["text"], "")} for i in items]}
        return {"items": [{"id": i["id"], "text": answers_text.get(i["text"], i["text"])} for i in items]}
    return respond


GOOD_TEXT = {"UPI/310045678901/RCTC": "UPI/310045678901/IRCTC",
             "UPI/290011223344/DECATHL.N": "UPI/290011223344/DECATHLON"}


# ----------------------------------------------------------------------------- client
def test_check_passes_when_the_model_is_pulled():
    with FakeOllama() as srv:
        OllamaClient(host=srv.host, model="qwen2.5:3b").check()


def test_check_says_how_to_pull_a_missing_model():
    with FakeOllama(models=("llama3.2:3b",)) as srv:
        with pytest.raises(LLMUnavailable, match="ollama pull qwen2.5:3b"):
            OllamaClient(host=srv.host, model="qwen2.5:3b").check()


def test_unreachable_server_is_reported_not_raised_raw():
    with pytest.raises(LLMUnavailable, match="ollama serve"):
        OllamaClient(host="http://127.0.0.1:9", timeout=1).check()


def test_chat_json_sends_the_schema_and_asks_for_deterministic_output():
    with FakeOllama(model()) as srv:
        client = OllamaClient(host=srv.host)
        out = client.chat_json("sys", '{"id": 0, "text": "x"}', {"type": "object"})
        body = srv.requests[0]
    assert out == {"items": [{"id": 0, "text": "x"}]}
    assert body["format"] == {"type": "object"} and body["stream"] is False
    assert body["options"]["temperature"] == 0 and client.calls == 1


def test_a_reply_that_is_not_json_is_an_unavailable_error():
    with FakeOllama(raw_reply="Sure! Here is the answer") as srv:
        with pytest.raises(LLMUnavailable, match="not valid JSON"):
            OllamaClient(host=srv.host).chat_json("s", "u", {"type": "object"})


def test_server_error_is_an_unavailable_error():
    with FakeOllama(chat_status=500) as srv:
        with pytest.raises(LLMUnavailable, match="500"):
            OllamaClient(host=srv.host).chat_json("s", "u", {"type": "object"})


def test_from_spec():
    assert from_spec("") is None and from_spec("off") is None and from_spec(None) is None
    assert from_spec("ollama:phi3.5").model == "phi3.5"
    assert from_spec("ollama").model == OllamaClient().model
    with pytest.raises(ValueError):
        from_spec("openai:gpt")


# ----------------------------------------------------------------------------- validators
@pytest.mark.parametrize("read, proposed, expected", [
    ("UPI/310045678901/RCTC", "UPI/310045678901/IRCTC", None),
    ("UPI/290011223344/KBALAHLUWALIA", "UPI/290011223344/IKBAL AHLUWALIA", None),
    ("UPI/310045678901/RCTC", "UPI/310045678901/RCTC", "no_change"),
    ("UPI/310045678901/ARJUNNAIR", "upi/310045678901/arjun nair", "no_change"),   # spacing and case are not corrections
    ("UPI/310045678901/RCTC", "UPI/310045678902/IRCTC", "changed_digits"),
    ("UPI/310045678901/RCTC", "UPI/31004567890/IRCTC", "changed_digits"),
    ("UPI/310045678901/RCTC", "310045678901/IRCTC", "lost_prefix"),
    ("UPI/310045678901/RCTC", "UPI/310045678901/AMAZON PRIME VIDEO", "too_many_edits"),
    ("UPI/310045678901/RCTC", "", "empty"),
    ("UPI/310045678901/RCTC", "UPI/310045678901/IRCTC\nand more", "malformed"),
    ("UPI/310045678901/RCTC", "x" * 200, "malformed"),
])
def test_check_description(read, proposed, expected):
    assert check_description(read, proposed) == expected


D = dt.date
PERIOD = (D(2026, 7, 1), D(2026, 7, 31))


@pytest.mark.parametrize("text, proposed, before, after, expected", [
    ("02-Ju-26", "2026-07-02", D(2026, 7, 1), D(2026, 7, 3), "ok"),
    ("17Jut2026", "2026-07-17", D(2026, 7, 16), D(2026, 7, 18), "ok"),
    ("14-Q07-2026", "2026-07-14", D(2026, 7, 13), D(2026, 7, 15), "ok"),
    ("02-Ju-26", "2026-07-05", D(2026, 7, 1), D(2026, 7, 8), "contradicts_text"),   # day 02 is visible, 05 is not
    ("02-Ju-26", "2026-06-02", D(2026, 7, 1), D(2026, 7, 3), "out_of_order"),
    ("02-Ju-26", "2026-07-02", D(2026, 7, 3), D(2026, 7, 4), "out_of_order"),
    ("02-Au-26", "2026-08-02", None, None, "outside_period"),
    ("02-Ju-26", "2026-03-02", None, None, "contradicts_text"),                     # 'Ju' is not March
    ("02-Ju-26", "not a date", None, None, "malformed"),
    ("02-Ju-26", "", None, None, "empty"),
])
def test_check_date(text, proposed, before, after, expected):
    d, reason = check_date(text, proposed, before, after, *PERIOD)
    assert (reason or "ok") == expected
    assert (d is not None) == (expected == "ok")


# ----------------------------------------------------------------------------- the fallback
def test_a_good_model_gets_validated_suggestions_and_nothing_is_overwritten(pdf):
    raw, true_date = damaged(pdf)
    before = {(i, n): fv.value for i, t in enumerate(raw.transactions) for n, fv in t.fields.items()}
    iso = true_date.isoformat()
    with FakeOllama(model(GOOD_TEXT, {f"{true_date.day:02d}-{true_date.strftime('%b')[:2]}-{true_date.year % 100:02d}": iso})) as srv:
        llm_fallback(raw, OllamaClient(host=srv.host))
    d2, d3 = raw.transactions[2].fields["description"], raw.transactions[3].fields["description"]
    assert d2.suggestion == "UPI/310045678901/IRCTC" and d3.suggestion == "UPI/290011223344/DECATHLON"
    assert FLAG in d2.flags and FLAG in d3.flags
    date = raw.transactions[5].fields["date"]
    assert date.suggestion == true_date and isinstance(date.suggestion, dt.date) and FLAG in date.flags
    assert before == {(i, n): fv.value for i, t in enumerate(raw.transactions) for n, fv in t.fields.items()}
    llm = raw.meta["llm"]
    assert llm["status"] == "ok" and llm["proposed"] == 3 and llm["rejected"] == {} and llm["calls"] == 2


def test_the_model_is_only_asked_about_cells_that_need_it(pdf):
    raw, _ = damaged(pdf)
    with FakeOllama(model()) as srv:
        llm_fallback(raw, OllamaClient(host=srv.host))
        asked = [json.loads(line) for req in srv.requests for line in req["messages"][1]["content"].splitlines()]
    # the two damaged descriptions and the unreadable date, plus whatever else the scorer genuinely flagged
    assert len(asked) == raw.meta["llm"]["asked"]
    assert all("balance" not in str(a) for a in asked)
    assert {"UPI/310045678901/RCTC", "UPI/290011223344/DECATHL.N"} <= {a.get("text") for a in asked}


def test_money_cells_and_cells_with_an_arithmetic_suggestion_are_never_candidates(pdf):
    raw = extract_pdf(pdf, scored=False)
    t = raw.transactions[4]
    t.fields["balance"] = FieldValue(text="x", value=t.value("balance") + 1000, confidence=0.5, source="ocr")
    cells = candidates(raw)
    assert all(name in ("description", "date", "value_date") for _, name in cells)
    scored = score(raw.model_copy(deep=True))
    for row, name in cells:
        assert scored.transactions[row].fields[name].suggestion is None


def test_a_model_that_changes_digits_or_invents_dates_is_ignored_and_counted(pdf):
    raw, true_date = damaged(pdf)
    date_text = f"{true_date.day:02d}-{true_date.strftime('%b')[:2]}-{true_date.year % 100:02d}"
    hostile = {"UPI/310045678901/RCTC": "UPI/310045678999/IRCTC",                  # digits changed
               "UPI/290011223344/DECATHL.N": "UPI/290011223344/SOMETHING ENTIRELY ELSE"}
    with FakeOllama(model(hostile, {date_text: "1999-01-01"})) as srv:
        llm_fallback(raw, OllamaClient(host=srv.host))
    assert all(fv.suggestion is None for t in raw.transactions for fv in t.fields.values())
    assert raw.meta["llm"]["proposed"] == 0
    assert raw.meta["llm"]["rejected"] == {"changed_digits": 1, "too_many_edits": 1, "contradicts_text": 1}


def test_a_model_that_skips_items_leaves_them_unanswered(pdf):
    raw, _ = damaged(pdf)
    with FakeOllama(lambda s, u, sc: {"items": []}) as srv:
        llm_fallback(raw, OllamaClient(host=srv.host))
    assert raw.meta["llm"]["unanswered"] == raw.meta["llm"]["asked"] > 0 and raw.meta["llm"]["proposed"] == 0


@pytest.mark.parametrize("server", [dict(models=("other:1b",)), dict(chat_status=500), dict(raw_reply="not json")])
def test_if_the_model_fails_extraction_carries_on_exactly_as_before(pdf, server):
    raw, _ = damaged(pdf)
    plain = score(raw.model_copy(deep=True)).meta["summary"]
    with FakeOllama(model(GOOD_TEXT), **server) as srv:
        client = OllamaClient(host=srv.host)
        try:
            client.check()
        except LLMUnavailable as exc:
            raw.meta["llm"] = {"status": "unavailable", "error": str(exc)}
        else:
            llm_fallback(raw, client)
    assert raw.meta["llm"]["status"] == "unavailable" and raw.meta["llm"].get("error")
    assert all(fv.suggestion is None for t in raw.transactions for fv in t.fields.values())
    assert score(raw).meta["summary"] == plain


def test_unreachable_ollama_during_the_run_is_recorded(pdf):
    raw, _ = damaged(pdf)
    llm_fallback(raw, OllamaClient(host="http://127.0.0.1:9", timeout=1))
    assert raw.meta["llm"]["status"] == "unavailable" and "ollama serve" in raw.meta["llm"]["error"]


def test_max_cells_and_batch_size_bound_the_work(pdf):
    raw, _ = damaged(pdf)
    with FakeOllama(model()) as srv:
        llm_fallback(raw, OllamaClient(host=srv.host), batch_size=1, max_cells=2)
        assert len(srv.requests) == 2 and raw.meta["llm"]["asked"] == 2


def test_the_scorer_keeps_llm_suggestions(pdf):
    raw, _ = damaged(pdf)
    with FakeOllama(model(GOOD_TEXT)) as srv:
        llm_fallback(raw, OllamaClient(host=srv.host))
    scored = score(raw)
    fv = scored.transactions[2].fields["description"]
    assert fv.suggestion == "UPI/310045678901/IRCTC" and fv.value == "UPI/310045678901/RCTC" and FLAG in fv.flags


# ----------------------------------------------------------------------------- the evaluation
def test_evaluation_scores_fixed_broke_and_blocked(pdf, tmp_path):
    from stmtai.llm.evaluate import evaluate_doc, render, summarize

    label_path = next(Path(pdf).parent.glob(f"{Path(pdf).stem}.json"))
    label = Label.model_validate_json(label_path.read_text(encoding="utf-8"))
    ext = extract_pdf(pdf)
    truth_desc = label.statement.transactions[2].description
    # row 2 read wrongly (one letter dropped); the model restores it, and also tries to corrupt a correct cell
    fv = ext.transactions[2].fields["description"]
    fv.value = fv.text = truth_desc[:-1]
    fv.confidence = 0.6
    slip = ext.transactions[4].fields["description"]      # a plausible-looking wrong edit: passes the checks
    slip.confidence = 0.6
    digits = ext.transactions[6].fields["description"]    # the model touches a digit: blocked by the checks
    digits.confidence = 0.6
    digits.value = digits.text = "UPI/310045678901/ZEPTO"
    answers = {truth_desc[:-1]: truth_desc, str(slip.value): str(slip.value)[:-1] + "Z",
               "UPI/310045678901/ZEPTO": "UPI/310045678902/ZEPTO"}
    with FakeOllama(model(answers)) as srv:
        client = OllamaClient(host=srv.host, cache_dir=tmp_path / "cache")
        doc = evaluate_doc(label, ext, client, [], batch_size=6)
        summary = summarize([doc])
        report = render(summary, "fake", "scan_medium", client, {})
    c = summary["fields"]["description"]
    assert c["fixed"] == 1 and c["broke"] == 1            # the checks are not magic: a one-letter slip gets through
    assert c["blocked"] == 1 and c["blocked_would_have_broken"] == 0  # row 6 was not read right in truth, so nothing to break
    assert "Net effect: 1 cells fixed, 1 correct cells put at risk" in report
    # the same run again is served from the cache
    with FakeOllama(model(answers)) as srv:
        client2 = OllamaClient(host=srv.host, cache_dir=tmp_path / "cache")
        evaluate_doc(label, ext, client2, [], batch_size=6)
        assert client2.cache_hits >= 1 and not srv.requests


# ----------------------------------------------------------------------------- through the API
def _low_confidence_ocr(digital):
    from replay import ReplayBackend
    backend = ReplayBackend(digital)
    backend.pages = [[(poly, text, 0.6 if text.startswith("UPI/") else conf) for poly, text, conf in segs]
                     for segs in backend.pages]
    return backend


@pytest.fixture(scope="module")
def scan_doc(tmp_path_factory):
    d = tmp_path_factory.mktemp("llmscan")
    build_dataset(d, per_layout=1, seed=951, scans=True)
    # the classic grid layout prints UPI descriptions as one token, so the replayed OCR can be made doubtful
    lp = sorted(d.glob("classic_grid*.json"))[0]
    label = Label.model_validate_json(lp.read_text(encoding="utf-8"))
    return d / f"{label.doc_id}.pdf", d / f"{label.doc_id}__scan_light.pdf"


def _client(tmp_path, digital, llm):
    from fastapi.testclient import TestClient
    from stmtai.api.app import Settings, create_app
    cfg = Settings(data_dir=tmp_path / "api", ocr_cache_dir=tmp_path / "cache", ocr_backend=_low_confidence_ocr(digital), llm=llm)
    return TestClient(create_app(cfg))


def _wrong_last_letter(system, user, schema):
    items = [json.loads(line) for line in user.splitlines()]
    return {"items": [{"id": i["id"], "text": i["text"][:-1] + "X" if i["text"][-1:].isalpha() else i["text"]} for i in items]}


def test_llm_suggestions_reach_the_review_screen_and_the_feedback_log(tmp_path, scan_doc):
    digital, scan = scan_doc
    with FakeOllama(_wrong_last_letter) as srv:
        client = _client(tmp_path, digital, OllamaClient(host=srv.host))
        assert client.get("/health").json()["llm"] == "ollama:qwen2.5:3b"
        with open(scan, "rb") as f:
            sid = client.post("/statements", files={"file": (scan.name, f, "application/pdf")}).json()["id"]
        detail = client.get(f"/statements/{sid}").json()
        assert detail["status"] == "ready" and detail["meta"]["llm"]["status"] == "ok"
        review = client.get(f"/statements/{sid}/review").json()
        llm_items = [i for i in review["items"] if "llm_suggested" in i["flags"]]
        assert llm_items, "model suggestions should be reviewable"
        assert all(i["group"] == "text" for i in llm_items)
        assert all(i["suggestion"] and "llm_suggested" in i["flags"] and not i["suggestion_verified"] for i in llm_items)
        assert any("language model" in r for r in llm_items[0]["reasons"])
        groups = {g["id"]: g for g in review["groups"]}
        assert groups["text"]["count"] >= len(llm_items) and groups["text"]["bulk"] is False
        assert client.post(f"/statements/{sid}/corrections/bulk", json={"group": "text"}).status_code == 422

        first, second = llm_items[0], llm_items[1]
        r = client.post(f"/statements/{sid}/corrections", json={"row": first["row"], "field": first["field"], "action": "accept_suggestion"})
        assert r.status_code == 201
        r = client.post(f"/statements/{sid}/corrections", json={"row": second["row"], "field": second["field"], "action": "confirm"})
        assert r.status_code == 201
    by_source = client.get("/feedback").json()["overall"]["suggestions_by_source"]
    assert by_source["llm"] == {"offered": 2, "accepted": 1, "accept_rate": 0.5}
    assert by_source["arithmetic"]["offered"] == 0


def test_an_unreachable_model_does_not_stop_extraction(tmp_path, scan_doc):
    digital, scan = scan_doc
    client = _client(tmp_path, digital, OllamaClient(host="http://127.0.0.1:9", timeout=1))
    with open(scan, "rb") as f:
        sid = client.post("/statements", files={"file": (scan.name, f, "application/pdf")}).json()["id"]
    detail = client.get(f"/statements/{sid}").json()
    assert detail["status"] == "ready" and detail["meta"]["llm"]["status"] == "unavailable"
    assert not [i for i in client.get(f"/statements/{sid}/review").json()["items"] if "llm_suggested" in i["flags"]]


def test_llm_is_off_by_default(tmp_path, scan_doc):
    digital, scan = scan_doc
    client = _client(tmp_path, digital, None)
    assert client.get("/health").json()["llm"] is None
    with open(scan, "rb") as f:
        sid = client.post("/statements", files={"file": (scan.name, f, "application/pdf")}).json()["id"]
    meta = client.get(f"/statements/{sid}").json()["meta"]
    assert "llm" not in meta and "rules" in meta  # the deterministic rules run whether or not a model is configured


# ----------------------------------------------------------------------------- rules, tried before the model
from stmtai.llm.fallback import RULE_FLAG, apply_rules, suggest  # noqa: E402
from stmtai.llm.rules import date_rule, description_rule  # noqa: E402


@pytest.mark.parametrize("read, expected", [
    ("UPI/061778298363/P00JAPUROHIT", "UPI/061778298363/POOJAPUROHIT"),      # the letter O read as zero
    ("UPI/264726751204/B00KMYSHOW", "UPI/264726751204/BOOKMYSHOW"),
    ("UPI/848283661547/L0PA.KAR", "UPI/848283661547/LOPA KAR"),              # zero and a dot for a space
    ("UPI/965569816934/RELIANCE.SMART", "UPI/965569816934/RELIANCE SMART"),
    ("UPI/990020809379NIVAANTIWARI", "UPI/990020809379/NIVAANTIWARI"),       # the separator was lost
    ("UPI/123456789012/RAHUL123", None),                                     # digits at the end of a handle are real
    ("UPI/123456789012/R4HUL", None),                                        # 4 is not a look-alike we trust
    ("UPI/123456789012/IRCTC", None),
    ("POS ZOMATO MEERUT", None),
    ("NEFT-N123456789012345-ORBITAL SOFTWARE", None),
])
def test_description_rule(read, expected):
    assert description_rule(read) == expected


def test_description_rule_never_touches_the_reference_digits():
    for read in ("UPI/0610778298363/P00JAPUROHIT", "UPI/061778298363/B00K0"):
        out = description_rule(read)
        assert out is None or [r for r in __import__("re").findall(r"\d{10,}", out)] == [r for r in __import__("re").findall(r"\d{10,}", read)]


D2 = dt.date
@pytest.mark.parametrize("text, before, after, expected", [
    ("29-Ju-26", D2(2026, 7, 28), D2(2026, 7, 30), "2026-07-29"),            # Jun or Jul: the neighbours decide
    ("29-Jui-26", D2(2026, 7, 28), D2(2026, 7, 30), "2026-07-29"),
    ("17Jut2026", D2(2026, 7, 16), D2(2026, 7, 18), "2026-07-17"),
    ("30-Apr-26 UPV446512650192/VIDHISATHE", D2(2026, 4, 29), D2(2026, 5, 1), "2026-04-30"),  # swallowed the next column
    ("02-Ju-26", None, None, None),                                          # nothing to tell June from July
    ("31-Ju-26", D2(2026, 6, 30), D2(2026, 7, 31), "2026-07-31"),            # 31 June does not exist
    ("not a date", None, None, None),
])
def test_date_rule(text, before, after, expected):
    assert date_rule(text, before, after, D2(2026, 3, 1), D2(2026, 8, 31)) == expected


def test_rules_attach_suggestions_without_a_model_and_without_overwriting(pdf):
    raw, true_date = damaged(pdf)
    t = raw.transactions
    t[2].fields["description"] = FieldValue(text="UPI/310045678901/B00KMYSHOW", value="UPI/310045678901/B00KMYSHOW",
                                           confidence=0.6, source="ocr")
    t[5].fields["date"].text = f"{true_date.day:02d}-{true_date.strftime('%b')[:2]}-{true_date.year}"
    before = {(i, n): fv.value for i, tx in enumerate(t) for n, fv in tx.fields.items()}
    apply_rules(raw)
    d = t[2].fields["description"]
    assert d.suggestion == "UPI/310045678901/BOOKMYSHOW" and RULE_FLAG in d.flags and d.value == "UPI/310045678901/B00KMYSHOW"
    assert raw.meta["rules"]["proposed"] >= 1 and "llm" not in raw.meta
    assert before == {(i, n): fv.value for i, tx in enumerate(t) for n, fv in tx.fields.items()}


def test_the_model_is_not_asked_about_cells_a_rule_already_settled(pdf):
    raw, _ = damaged(pdf)
    raw.transactions[2].fields["description"] = FieldValue(text="UPI/310045678901/B00KMYSHOW",
                                                           value="UPI/310045678901/B00KMYSHOW", confidence=0.6, source="ocr")
    raw.transactions[4].fields["description"] = FieldValue(text="UPI/777788889999/RCTC", value="UPI/777788889999/RCTC",
                                                           confidence=0.6, source="ocr")
    with FakeOllama(model()) as srv:
        suggest(raw, OllamaClient(host=srv.host))
        asked = [json.loads(line)["text"] for req in srv.requests for line in req["messages"][1]["content"].splitlines()]
    assert "UPI/310045678901/B00KMYSHOW" not in asked      # a rule settled it
    assert "UPI/777788889999/RCTC" in asked                 # no rule applies, so the model is asked
    assert RULE_FLAG in raw.transactions[2].fields["description"].flags


def test_evaluation_can_score_the_rules_alone(pdf):
    from stmtai.llm.evaluate import evaluate_doc, render, summarize
    label = Label.model_validate_json(next(Path(pdf).parent.glob(f"{Path(pdf).stem}.json")).read_text(encoding="utf-8"))
    ext = extract_pdf(pdf)
    truth = label.statement.transactions[2].description
    fv = ext.transactions[2].fields["description"]
    fv.value = fv.text = "UPI/310045678901/B00KMYSHOW"
    fv.confidence = 0.6
    doc = evaluate_doc(label, ext, None, [], batch_size=6)
    assert doc["per_field"]["description"]["rule_proposed"] == 1
    report = render(summarize([doc]), "", "scan_medium", None, {})
    assert "rules only" in report and "Rules versus the model" in report


# ----------------------------------------------------------------------------- the dropped-letter probe
def test_probe_damages_names_and_scores_a_model(pdf):
    from stmtai.llm import probe

    data = Path(pdf).parent
    cases = probe.build_cases(data, n_damaged=8, n_clean=4, seed=3)
    damaged_cases = [c for c in cases if c["kind"] != "clean"]
    assert len(damaged_cases) == 8 and sum(c["kind"] == "clean" for c in cases) == 4
    assert all(c["read"] != c["truth"] and c["read"].rsplit("/", 1)[0] == c["truth"].rsplit("/", 1)[0] for c in damaged_cases)  # only the name is damaged
    assert all(c["read"] == c["truth"] for c in cases if c["kind"] == "clean")

    truth_of = {c["read"]: c["truth"] for c in cases}
    def perfect(system, user, schema):
        return {"items": [{"id": json.loads(l)["id"], "text": truth_of[json.loads(l)["text"]]} for l in user.splitlines()]}

    with FakeOllama(perfect) as srv:
        res = probe.run(OllamaClient(host=srv.host), cases)
    s = probe.summarize(res)
    assert s["fixed"] == 8 and s["wrong_suggestion"] == 0 and s["clean_changed"] == 0

    with FakeOllama(model()) as srv:   # a model that never changes anything
        s2 = probe.summarize(probe.run(OllamaClient(host=srv.host), cases))
    assert s2["fixed"] == 0 and s2["no_suggestion"] == 8
    assert "restored exactly" in probe.render(s, "fake", 1.0, 3)


# ----------------------------------------------------------------------------- the statement's own vocabulary
from stmtai.llm.vocab import Vocabulary, hints_for, vocab_rule  # noqa: E402

KNOWN = ["UPI/111111111111/IRCTC"] * 5 + ["UPI/222222222222/BLINKIT"] * 3 + ["UPI/333333333333/AMAZON PAY"] * 2 + ["UPI/444444444444/ARJUN NAIR"]


@pytest.mark.parametrize("read, expected", [
    ("UPI/555555555555/RCTC", "UPI/555555555555/IRCTC"),
    ("UPI/555555555555/BLIKIT", "UPI/555555555555/BLINKIT"),
    ("UPI/555555555555/AMAZON PY", "UPI/555555555555/AMAZON PAY"),
    ("UPI/555555555555/IRCTC", None),            # already printed that way elsewhere
    ("UPI/555555555555/ARJUN NAIK", None),      # a name seen once is not vocabulary: do not drag one person towards another
    ("UPI/555555555555/ZEPTO", None),
    ("POS ZOMATO MEERUT", None),
])
def test_vocab_rule(read, expected):
    assert vocab_rule(read, Vocabulary(KNOWN)) == expected


def test_vocab_rule_refuses_to_guess_between_equally_close_names():
    v = Vocabulary(["UPI/111111111111/CAFE ABC"] * 2 + ["UPI/222222222222/CAFE ABD"] * 2)
    assert vocab_rule("UPI/555555555555/CAFE ABE", v) is None            # one edit from each: a tie
    assert vocab_rule("UPI/555555555555/CAFE ABX", v) is None
    assert vocab_rule("UPI/555555555555/CAFE AB", v) is None


def test_hints_are_the_nearby_known_names():
    assert hints_for("UPI/555555555555/RCTC", Vocabulary(KNOWN)) == ["IRCTC"]


def test_names_from_approved_statements_become_vocabulary(pdf):
    raw, _ = damaged(pdf)   # row 2 reads UPI/310045678901/RCTC
    apply_rules(raw)
    assert raw.transactions[2].fields["description"].suggestion is None          # nothing to learn from yet
    raw2, _ = damaged(pdf)
    apply_rules(raw2, known=["UPI/111111111111/IRCTC"] * 3)
    d = raw2.transactions[2].fields["description"]
    assert d.suggestion == "UPI/310045678901/IRCTC" and RULE_FLAG in d.flags and d.value == "UPI/310045678901/RCTC"


def test_the_api_learns_names_from_approved_statements(tmp_path, scan_doc):
    from fastapi.testclient import TestClient
    from stmtai.api.app import Settings, create_app
    digital, scan = scan_doc
    cfg = Settings(data_dir=tmp_path / "api", ocr_cache_dir=tmp_path / "cache", ocr_backend=_low_confidence_ocr(digital), llm=None)
    client = TestClient(create_app(cfg))
    store = client.app.state.store
    assert store.approved_descriptions() == []
    with open(scan, "rb") as f:
        sid = client.post("/statements", files={"file": (scan.name, f, "application/pdf")}).json()["id"]
    assert store.approved_descriptions() == []                 # not approved, so not trusted
    store.approve(sid)
    names = store.approved_descriptions()
    assert names and all(isinstance(n, str) for n in names)
    assert store.approved_descriptions(exclude=sid) == []


def test_the_probe_reports_the_vocabulary_baselines(pdf):
    from stmtai.llm import probe
    cases = probe.build_cases(Path(pdf).parent, n_damaged=8, n_clean=4, seed=3)
    own, pooled = probe.vocabulary_only(cases), probe.vocabulary_only(cases, True)
    assert pooled["restored"] >= own["restored"] and pooled["clean_changed"] == 0


def test_probe_compares_the_model_with_the_vocabulary_rule(pdf):
    from stmtai.llm import probe
    cases = probe.build_cases(Path(pdf).parent, n_damaged=8, n_clean=4, seed=3)
    truth_of = {c["read"]: c["truth"] for c in cases}
    def perfect(system, user, schema):
        return {"items": [{"id": json.loads(l)["id"], "text": truth_of[json.loads(l)["text"]]} for l in user.splitlines()]}
    with FakeOllama(perfect) as srv:
        res = probe.run(OllamaClient(host=srv.host), cases)
    v = probe.versus_rule(res)
    assert v["only_rule"] == 0 and v["both"] + v["only_model"] == 8 and v["neither"] == 0
    assert "only the model" in probe.render(probe.summarize(res), "fake", 1.0, 1, None, False, v)
