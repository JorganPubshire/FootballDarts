"""Run the local Starlette + uvicorn server and open the dashboard in a browser."""

from __future__ import annotations

import threading
import webbrowser

import uvicorn

from dart_football.engine.session import GameSession


def run_gui_server(session: GameSession, *, host: str = "127.0.0.1", port: int = 8765) -> None:
    holder: dict[str, GameSession | None] = {"session": session}
    from dart_football.gui.server import create_app

    app = create_app(holder)
    url = f"http://{host}:{port}/"

    def _open() -> None:
        import time

        time.sleep(0.35)
        webbrowser.open(url)

    threading.Thread(target=_open, daemon=True).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")
