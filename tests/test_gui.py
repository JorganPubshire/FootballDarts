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


def test_state_includes_correctable_dart_key(gui_client: TestClient) -> None:
    r = gui_client.get("/api/state")
    assert r.status_code == 200
    assert "correctable_dart" in r.json()


def test_meta_correct_dart_scrimmage(gui_client: TestClient) -> None:
    assert gui_client.post("/api/apply", json={"event": {"type": "CoinTossWinner", "winner": "red"}}).status_code == 200
    assert gui_client.post("/api/apply", json={"event": {"type": "ChooseKickOrReceive", "kick": True}}).status_code == 200
    assert gui_client.post("/api/apply", json={"event": {"type": "ChooseKickoffKind", "onside": False}}).status_code == 200
    r_k = gui_client.post(
        "/api/apply",
        json={"event": {"type": "KickoffKick", "segment": 10, "bull": "none", "miss": True}},
    )
    assert r_k.status_code == 200
    ui = r_k.json()["ui"]
    assert ui["phase"] == "scrimmage_offense"
    assert ui["correctable_dart"] is not None
    assert ui["correctable_dart"]["type"] == "KickoffKick"
    offense = {
        "type": "ScrimmageOffense",
        "segment": 5,
        "bull": "none",
        "double_ring": False,
        "triple_ring": False,
        "triple_inner": None,
        "miss": False,
    }
    r_o = gui_client.post("/api/apply", json={"event": offense})
    assert r_o.status_code == 200
    ui2 = r_o.json()["ui"]
    assert ui2["correctable_dart"] is not None
    assert ui2["correctable_dart"]["type"] == "ScrimmageOffense"
    fixed = dict(offense)
    fixed["segment"] = 6
    r_c = gui_client.post("/api/meta", json={"action": "correct_dart", "event": fixed})
    assert r_c.status_code == 200
    body = r_c.json()
    assert body.get("ok") is True
    assert body["ui"]["correctable_dart"] is not None
    assert body["ui"]["correctable_dart"]["event"]["segment"] == 6


def test_meta_correct_dart_rejects_wrong_event_type(gui_client: TestClient) -> None:
    assert gui_client.post("/api/apply", json={"event": {"type": "CoinTossWinner", "winner": "red"}}).status_code == 200
    assert gui_client.post("/api/apply", json={"event": {"type": "ChooseKickOrReceive", "kick": True}}).status_code == 200
    assert gui_client.post("/api/apply", json={"event": {"type": "ChooseKickoffKind", "onside": False}}).status_code == 200
    assert (
        gui_client.post(
            "/api/apply",
            json={"event": {"type": "KickoffKick", "segment": 10, "bull": "none", "miss": True}},
        ).status_code
        == 200
    )
    offense = {
        "type": "ScrimmageOffense",
        "segment": 5,
        "bull": "none",
        "double_ring": False,
        "triple_ring": False,
        "triple_inner": None,
        "miss": False,
    }
    assert gui_client.post("/api/apply", json={"event": offense}).status_code == 200
    r_c = gui_client.post(
        "/api/meta",
        json={
            "action": "correct_dart",
            "event": {"type": "KickoffKick", "segment": 3, "bull": "none", "miss": False},
        },
    )
    assert r_c.status_code == 400
