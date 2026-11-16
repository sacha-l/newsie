from __future__ import annotations

from fastapi.testclient import TestClient

from newsie.web.app import app

client = TestClient(app)


def test_home_ok() -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "Newsie" in r.text
    assert "Sample data" in r.text


def test_run_approve_flow() -> None:
    r = client.post("/run")
    assert r.status_code == 200
    assert "Factual spine" in r.text or "Validation" in r.text
    r2 = client.post("/approve")
    assert r2.status_code == 200
    assert "Published" in r2.text or "published" in r2.text.lower()


def test_health() -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
