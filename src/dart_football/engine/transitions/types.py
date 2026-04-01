from __future__ import annotations

from dart_football.engine.phases import Phase
from dart_football.engine.state import GameState


class TransitionOk:
    __slots__ = ("state", "phase", "effects_summary")

    def __init__(self, state: GameState, phase: Phase, effects_summary: str) -> None:
        self.state = state
        self.phase = phase
        self.effects_summary = effects_summary


class TransitionError:
    __slots__ = ("message", "allowed_events")

    def __init__(self, message: str, allowed_events: tuple[str, ...]) -> None:
        self.message = message
        self.allowed_events = allowed_events
