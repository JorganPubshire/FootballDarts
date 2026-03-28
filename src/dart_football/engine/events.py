from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from dart_football.engine.state import TeamId


@dataclass(frozen=True)
class CoinTossWinner:
    winner: TeamId


@dataclass(frozen=True)
class ChooseKickOrReceive:
    """Winner's choice for the opening kickoff."""

    kick: bool
    """If True, winner kicks; if False, winner receives."""


@dataclass(frozen=True)
class KickoffKick:
    segment: int
    bull: Literal["none", "green", "red"] = "none"


@dataclass(frozen=True)
class ScrimmageOffense:
    """Offense dart; D/T rings multiply base yards from rules (PDF order TODO)."""

    segment: int
    double_ring: bool = False
    triple_ring: bool = False
    # If triple_ring: True = inner treble, False = outer treble (log / future rules).
    triple_inner: bool | None = None
    bull: Literal["none", "green", "red"] = "none"


@dataclass(frozen=True)
class ScrimmageDefense:
    """Defense dart; yardage ignores D/T (per rules)."""

    segment: int
    bull: Literal["none", "green", "red"] = "none"
    # Ignored for yardage; recorded for the session log.
    double_ring: bool = False
    triple_ring: bool = False
    triple_inner: bool | None = None


@dataclass(frozen=True)
class FourthDownChoice:
    """Fourth down: go for it, punt, or field goal (cannot punt on 1st — enforced by phase)."""

    kind: Literal["go", "punt", "field_goal"]


@dataclass(frozen=True)
class FieldGoalOutcome:
    kind: Literal["good", "miss", "blocked"]


@dataclass(frozen=True)
class PuntKick:
    segment: int
    bull: Literal["none", "green", "red"] = "none"


@dataclass(frozen=True)
class ChoosePatOrTwo:
    """After TD: attempt 1-pt kick or 2-pt conversion."""

    extra_point: bool


@dataclass(frozen=True)
class ExtraPointOutcome:
    """PAT dart resolved to made or miss (PDF detail TODO)."""

    good: bool


@dataclass(frozen=True)
class TwoPointOutcome:
    """2PC dart resolved to good or no score."""

    good: bool


@dataclass(frozen=True)
class CallTimeout:
    """Team uses one timeout for the current half. Does not count as a play or advance the clock."""

    team: TeamId


Event = (
    CoinTossWinner
    | ChooseKickOrReceive
    | KickoffKick
    | ScrimmageOffense
    | ScrimmageDefense
    | FourthDownChoice
    | FieldGoalOutcome
    | PuntKick
    | ChoosePatOrTwo
    | ExtraPointOutcome
    | TwoPointOutcome
    | CallTimeout
)
