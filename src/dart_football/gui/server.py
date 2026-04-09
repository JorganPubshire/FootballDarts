"""Starlette app: API + static dashboard."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from dart_football.engine.event_codec import event_from_dict
from dart_football.engine.events import CallTimeout
from dart_football.engine.session import GameSession
from dart_football.engine.state import TeamId
from dart_football.engine.transitions import TransitionError
from dart_football.gui.ui_state import build_ui_payload


def _json_response(data: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status)


def create_app(session_holder: dict[str, GameSession | None]) -> Starlette:
    static_dir = Path(__file__).resolve().parent / "static"

    async def api_state(request: Request) -> Response:
        s = session_holder.get("session")
        if s is None:
            return _json_response({"error": "no session"}, status=500)
        return _json_response(build_ui_payload(s))

    async def api_apply(request: Request) -> Response:
        s = session_holder.get("session")
        if s is None:
            return _json_response({"error": "no session"}, status=500)
        try:
            body = await request.json()
        except Exception:
            return _json_response({"error": "invalid JSON"}, status=400)
        if not isinstance(body, dict) or "event" not in body:
            return _json_response({"error": "expected {event: ...}"}, status=400)
        try:
            ev = event_from_dict(body["event"])
        except (KeyError, ValueError, TypeError) as e:
            return _json_response({"error": f"bad event: {e}"}, status=400)
        state_before, _ = s.current_state_phase()
        q_before = state_before.clock.quarter
        out = s.apply(ev, source="gui")
        if isinstance(out, TransitionError):
            return _json_response({"ok": False, "error": out.message}, status=400)
        state_after, _ = s.current_state_phase()
        halftime = q_before == 2 and state_after.clock.quarter == 3
        return _json_response(
            {
                "ok": True,
                "effects_summary": out.effects_summary,
                "halftime_prompt": halftime,
                "ui": build_ui_payload(s),
            }
        )

    async def api_meta(request: Request) -> Response:
        s = session_holder.get("session")
        if s is None:
            return _json_response({"error": "no session"}, status=500)
        try:
            body = await request.json()
        except Exception:
            return _json_response({"error": "invalid JSON"}, status=400)
        action = body.get("action") if isinstance(body, dict) else None
        state_before, phase = s.current_state_phase()
        q_before = state_before.clock.quarter

        if action == "undo":
            if s.undo():
                return _json_response({"ok": True, "ui": build_ui_payload(s)})
            return _json_response({"ok": False, "error": "nothing to undo"}, status=400)

        if action == "history":
            lines = [
                {"seq": r.seq, "summary": r.effects_summary, "phase_after": r.phase_after.value}
                for r in s.records
            ]
            return _json_response({"ok": True, "history": lines})

        if action == "save":
            path = body.get("path") if isinstance(body, dict) else None
            if not path or not str(path).strip():
                return _json_response({"ok": False, "error": "missing path"}, status=400)
            try:
                s.save(str(path).strip())
                return _json_response({"ok": True, "path": str(path).strip()})
            except OSError as e:
                return _json_response({"ok": False, "error": str(e)}, status=400)

        if action == "timeout":
            team_s = body.get("team") if isinstance(body, dict) else None
            if team_s not in ("red", "green"):
                return _json_response({"ok": False, "error": "team must be red or green"}, status=400)
            team = TeamId.RED if team_s == "red" else TeamId.GREEN
            out = s.apply(CallTimeout(team), source="gui")
            if isinstance(out, TransitionError):
                return _json_response({"ok": False, "error": out.message}, status=400)
            state_after, _ = s.current_state_phase()
            halftime = q_before == 2 and state_after.clock.quarter == 3
            return _json_response(
                {
                    "ok": True,
                    "effects_summary": out.effects_summary,
                    "halftime_prompt": halftime,
                    "ui": build_ui_payload(s),
                }
            )

        if action == "quit":
            return _json_response({"ok": True, "quit": True})

        return _json_response({"error": "unknown action"}, status=400)

    async def index(request: Request) -> Response:
        index_path = static_dir / "index.html"
        if not index_path.is_file():
            return Response("GUI static files missing", status_code=500)
        return FileResponse(
            index_path,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "Pragma": "no-cache",
            },
        )

    routes = [
        Route("/api/state", api_state, methods=["GET"]),
        Route("/api/apply", api_apply, methods=["POST"]),
        Route("/api/meta", api_meta, methods=["POST"]),
        Route("/", index),
        Mount("/static", app=StaticFiles(directory=str(static_dir)), name="static"),
    ]
    return Starlette(routes=routes)
