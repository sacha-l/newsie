from __future__ import annotations

from fastapi.testclient import TestClient

from newsie.web.app import app

client = TestClient(app)


def test_home_ok() -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "Newsie" in r.text
    assert "independent origins" in r.text
    assert "Sources today" in r.text
    assert "Past 30 days of sources" in r.text or "Sample edition" in r.text


def test_run_approve_flow() -> None:
    r = client.post("/run")
    assert r.status_code == 200
    assert "Sources today" in r.text
    assert "category-head" in r.text or "How outlets differ" in r.text
    r2 = client.post("/approve")
    assert r2.status_code == 200
    assert "Published" in r2.text or "published" in r2.text.lower()


def test_run_html_scans_then_lists_articles() -> None:
    r = client.post("/run")
    assert r.status_code == 200
    assert "At a glance" in r.text
    assert "All articles" in r.text
    assert "Only one origin" in r.text
    assert 'class="tip-box"' in r.text
    assert 'data-group="' in r.text
    glance = r.text.find("At a glance")
    articles = r.text.find("All articles")
    assert 0 <= glance < articles


def test_event_board_describes_the_collected_sample() -> None:
    page = client.get("/events")
    assert page.status_code == 200
    assert "collected sample" in page.text
    assert "What is known" in page.text


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
