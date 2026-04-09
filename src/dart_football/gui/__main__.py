"""Entry point for ``python -m dart_football.gui`` (graphical dashboard)."""

from __future__ import annotations

from dart_football.cli.session_startup import make_gui_arg_parser, session_from_cli_args
from dart_football.gui.serve import run_gui_server


def main(argv: list[str] | None = None) -> None:
    args = make_gui_arg_parser().parse_args(argv)
    session, _, _ = session_from_cli_args(args)
    run_gui_server(session)


if __name__ == "__main__":
    main()
