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
class ChooseKickoffKind:
    """Kicker chooses a normal kickoff vs an onside attempt (before the kick dart)."""

    onside: bool


@dataclass(frozen=True)
class KickoffKick:
    """Kickoff dart. ``miss`` means outer label ring / surround (0 yards of kick travel)."""

    segment: int
    bull: Literal["none", "green", "red"] = "none"
    miss: bool = False


@dataclass(frozen=True)
class ChooseKickoffTouchbackOrRun:
    """After kick segments that allow it: ball at touchback line or run out from goal line."""

    take_touchback: bool


@dataclass(frozen=True)
class KickoffRunOutKick:
    """Run-out dart from the receiving goal line; doubles/triples ignored for numbered wedges."""

    segment: int
    bull: Literal["none", "green", "red"] = "none"
    miss: bool = False


@dataclass(frozen=True)
class KickoffReturnKick:
    """Mandatory return dart from the kick spot; 13–20 uses offense double/triple multipliers."""

    segment: int
    double_ring: bool = False
    triple_ring: bool = False
    # Optional; loaded sessions may still have inner/outer for display in summaries.
    triple_inner: bool | None = None
    bull: Literal["none", "green", "red"] = "none"
    miss: bool = False


@dataclass(frozen=True)
class ScrimmageOffense:
    """Offense dart; D/T rings multiply base yards. ``miss``: outer label ring — 0 offensive yards."""

    segment: int
    double_ring: bool = False
    triple_ring: bool = False
    # Optional legacy log detail; UI no longer distinguishes inner vs outer treble.
    triple_inner: bool | None = None
    bull: Literal["none", "green", "red"] = "none"
    miss: bool = False


@dataclass(frozen=True)
class ScrimmageDefense:
    """Defense dart; yardage ignores D/T (per rules)."""

    segment: int
    bull: Literal["none", "green", "red"] = "none"
    # Ignored for yardage; recorded for the session log.
    double_ring: bool = False
    triple_ring: bool = False
    triple_inner: bool | None = None  # legacy inner/outer treble log only
    miss: bool = False


@dataclass(frozen=True)
class ScrimmageStripDart:
    """After defense green bull vs offense numbered wedge: second dart for wedge-color strip rule."""

    segment: int


@dataclass(frozen=True)
class FourthDownChoice:
    """Fourth down: go for it, punt, or field goal (cannot punt on 1st — enforced by phase)."""

    kind: Literal["go", "punt", "field_goal"]


@dataclass(frozen=True)
class FieldGoalOutcome:
    """Legacy session format; new games use FieldGoalOffenseDart and related events."""

    kind: Literal["good", "miss", "blocked"]


@dataclass(frozen=True)
class FieldGoalOffenseDart:
    """Kicker's FG try dart: where it landed on the board. ``miss``: wide (outside scoring ring)."""

    zone: Literal["inner_triple", "outside_triples", "triple_ring", "green", "red"]
    segment: int
    miss: bool = False


@dataclass(frozen=True)
class ChooseFieldGoalAfterGreen:
    """After green bull on FG: real kick (then defense) vs fake (run, then defense)."""

    real_kick: bool


@dataclass(frozen=True)
class FieldGoalFakeOffenseDart:
    """Fake FG: yardage dart; wedge-number rules, no separate defense dart for offense."""

    segment: int
    double_ring: bool = False
    triple_ring: bool = False
    triple_inner: bool | None = None
    bull: Literal["none", "green", "red"] = "none"
    miss: bool = False


@dataclass(frozen=True)
class FieldGoalDefenseDart:
    """Defense during FG sequence; green/red can block; numbered usually no effect."""

    segment: int
    bull: Literal["none", "green", "red"] = "none"
    double_ring: bool = False
    triple_ring: bool = False
    triple_inner: bool | None = None
    miss: bool = False


@dataclass(frozen=True)
class PuntKick:
    segment: int
    bull: Literal["none", "green", "red"] = "none"
    miss: bool = False


@dataclass(frozen=True)
class ChooseExtraPointOrTwo:
    """After TD: attempt 1-pt kick or 2-pt conversion."""

    extra_point: bool


@dataclass(frozen=True)
class ExtraPointOutcome:
    """Extra point dart resolved to made or miss."""

    good: bool


@dataclass(frozen=True)
class TwoPointOutcome:
    """2PC dart resolved to good or no score."""

    good: bool


@dataclass(frozen=True)
class ConfirmSafetyKickoff:
    """After a safety is scored: proceed to the free kick (from the kicking team's own yard line)."""


@dataclass(frozen=True)
class CallTimeout:
    """Team uses one timeout for the current half. Does not count as a play.

    The next play that would advance the game play counter does not (e.g. preserve time at end of quarter).
    """

    team: TeamId


Event = (
    CoinTossWinner
    | ChooseKickOrReceive
    | ChooseKickoffKind
    | KickoffKick
    | ChooseKickoffTouchbackOrRun
    | KickoffRunOutKick
    | KickoffReturnKick
    | ScrimmageOffense
    | ScrimmageDefense
    | ScrimmageStripDart
    | FourthDownChoice
    | FieldGoalOutcome
    | FieldGoalOffenseDart
    | ChooseFieldGoalAfterGreen
    | FieldGoalFakeOffenseDart
    | FieldGoalDefenseDart
    | PuntKick
    | ChooseExtraPointOrTwo
    | ExtraPointOutcome
    | TwoPointOutcome
    | ConfirmSafetyKickoff
    | CallTimeout
)
