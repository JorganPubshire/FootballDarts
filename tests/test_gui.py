"""Smoke tests for the local web GUI (Starlette app)."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from dart_football.cli.session_startup import build_game_session
from dart_football.engine.session import GameSession
from dart_football.gui.server import create_app


@pytest.fixture
def gui_client(rules_path: Path) -> TestClient:
    session, _, _ = build_game_session(["--rules", str(rules_path)])
    holder: dict[str, GameSession | None] = {"session": session}
    app = create_app(holder)
    return TestClient(app)


def test_api_state_ok(gui_client: TestClient) -> None:
    r = gui_client.get("/api/state")
    assert r.status_code == 200
    data = r.json()
    assert data["phase"] == "pre_game_coin_toss"
    assert "field_graphic" in data
    assert "los_yard" in data["field_graphic"]
    assert "actions" in data
    assert any(a["id"] == "coin_toss_darts" for a in data["actions"])
    assert any(a["id"] == "coin_toss_sim" for a in data["actions"])


def test_apply_coin_toss(gui_client: TestClient) -> None:
    r = gui_client.post(
        "/api/apply",
        json={"event": {"type": "CoinTossWinner", "winner": "red"}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True
    assert "ui" in body
    assert body["ui"]["phase"] != "pre_game_coin_toss"


def test_index_serves_html(gui_client: TestClient) -> None:
    r = gui_client.get("/")
    assert r.status_code == 200
    assert b"html" in r.content.lower()
