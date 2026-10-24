"""The single-port setup used by the Docker image: UI at /, API under /api."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stmtai.api.app import Settings
from stmtai.api.site import create_site
from stmtai.synth.generate import build_dataset


@pytest.fixture()
def web(tmp_path):
    d = tmp_path / "web"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html><title>Statements</title><div id=root></div>", encoding="utf-8")
    (d / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    return d


def test_ui_and_api_share_one_port(tmp_path, web):
    client = TestClient(create_site(Settings(data_dir=tmp_path / "d", ocr_cache_dir=tmp_path / "c", ocr=False), web_dir=web))
    page = client.get("/")
    assert page.status_code == 200 and "<title>Statements</title>" in page.text
    assert client.get("/assets/app.js").text == "console.log(1)"
    health = client.get("/api/health").json()
    assert health["status"] == "ok" and health["ocr_enabled"] is False
    assert client.get("/api/statements").json() == []
    assert client.get("/health").status_code == 404   # the API lives only under /api


def test_the_whole_flow_works_through_the_api_prefix(tmp_path, web):
    d = tmp_path / "docs"
    build_dataset(d, per_layout=1, seed=940, scans=False)
    pdf = sorted(d.glob("classic_grid*.pdf"))[0]
    client = TestClient(create_site(Settings(data_dir=tmp_path / "d", ocr_cache_dir=tmp_path / "c", ocr=False), web_dir=web))
    with open(pdf, "rb") as f:
        sid = client.post("/api/statements", files={"file": (pdf.name, f, "application/pdf")}).json()["id"]
    detail = client.get(f"/api/statements/{sid}").json()
    assert detail["status"] == "ready" and detail["pages"][0]["image"].endswith("/pages/0.png")
    assert client.get(f"/api/statements/{sid}/pages/0.png").headers["content-type"] == "image/png"
    assert client.post(f"/api/statements/{sid}/approve").json()["approved"] is True
    answer = client.post("/api/query", json={"question": "How many debits?"}).json()
    assert answer["answered"] and answer["statements"] == [sid]


def test_a_missing_ui_is_a_clear_error(tmp_path):
    with pytest.raises(RuntimeError, match="npm run build"):
        create_site(Settings(data_dir=tmp_path / "d", ocr_cache_dir=tmp_path / "c"), web_dir=tmp_path / "nowhere")
