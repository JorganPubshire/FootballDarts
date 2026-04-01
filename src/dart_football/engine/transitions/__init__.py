"""Game state transitions (rules-driven phase machine)."""

from dart_football.engine.transitions.transition_core import transition
from dart_football.engine.transitions.types import TransitionError, TransitionOk

__all__ = ["transition", "TransitionError", "TransitionOk"]
