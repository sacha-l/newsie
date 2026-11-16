from __future__ import annotations

from fastapi.testclient import TestClient

from newsie.web.app import app

client = TestClient(app)


def test_home_ok() -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "Newsie" in r.text
    assert "Sources today" in r.text
    assert "Sample edition" in r.text


def test_run_approve_flow() -> None:
    r = client.post("/run")
    assert r.status_code == 200
    assert "Sources today" in r.text
    assert "category-head" in r.text or "How outlets differ" in r.text
    r2 = client.post("/approve")
    assert r2.status_code == 200
    assert "Published" in r2.text or "published" in r2.text.lower()


def test_run_html_has_flip_card() -> None:
    r = client.post("/run")
    assert r.status_code == 200
    assert 'class="flip-toggle"' in r.text
    assert "Flip for sources" in r.text
    assert ">Sources<" in r.text
    assert "What the opinion means" in r.text
    assert "How it differs" in r.text


def test_static_assets_served_by_app() -> None:
    css = client.get("/static/styles.css")
    assert css.status_code == 200
    assert "rotateY(180deg)" in css.text
    script = client.get("/static/flip.js")
    assert script.status_code == 200
    assert "aria-pressed" in script.text


def test_health() -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
