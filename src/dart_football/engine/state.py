from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TeamId(Enum):
    RED = "red"
    GREEN = "green"


@dataclass(frozen=True)
class Scoreboard:
    red: int = 0
    green: int = 0

    def add(self, team: TeamId, points: int) -> Scoreboard:
        if team is TeamId.RED:
            return Scoreboard(self.red + points, self.green)
        return Scoreboard(self.red, self.green + points)


@dataclass(frozen=True)
class FieldPosition:
    """Ball on a 0..100 line; offense moves toward `goal_yard` (0 or 100)."""

    scrimmage_line: int
    goal_yard: int

    def __post_init__(self) -> None:
        if self.scrimmage_line not in range(0, 101):
            raise ValueError("scrimmage_line must be 0..100")
        if self.goal_yard not in (0, 100):
            raise ValueError("goal_yard must be 0 or 100")


@dataclass(frozen=True)
class DownAndDistance:
    down: int
    to_go: int
    los_yard: int

    def __post_init__(self) -> None:
        if self.down not in range(1, 5):
            raise ValueError("down must be 1..4")
        if self.to_go < 0:
            raise ValueError("to_go must be non-negative")
        if self.los_yard not in range(0, 101):
            raise ValueError("los_yard must be 0..100")


@dataclass(frozen=True)
class GameClock:
    quarter: int
    plays_in_quarter: int
    total_plays: int

    def __post_init__(self) -> None:
        if self.quarter < 1:
            raise ValueError("quarter must be >= 1")
        if self.plays_in_quarter < 0 or self.total_plays < 0:
            raise ValueError("play counts must be non-negative")


@dataclass(frozen=True)
class Timeouts:
    red_q1_q2: int
    red_q3_q4: int
    green_q1_q2: int
    green_q3_q4: int

    def __post_init__(self) -> None:
        for n in (self.red_q1_q2, self.red_q3_q4, self.green_q1_q2, self.green_q3_q4):
            if n < 0:
                raise ValueError("timeouts must be non-negative")


@dataclass(frozen=True)
class GameState:
    scores: Scoreboard
    offense: TeamId
    field: FieldPosition
    downs: DownAndDistance
    clock: GameClock
    timeouts: Timeouts
    coin_toss_winner: TeamId | None = None
    kickoff_kicker: TeamId | None = None
    kickoff_receiver: TeamId | None = None
    declared_fg_attempt: bool = False
    declared_punt: bool = False
    declared_onside: bool = False
    last_play_of_period: bool = False
    scrimmage_pending_offense_yards: int | None = None
    last_touchdown_team: TeamId | None = None

    @staticmethod
    def new_game(
        timeouts_per_half: int = 3,
        starting_quarter: int = 1,
    ) -> GameState:
        mid = FieldPosition(50, 100)
        downs = DownAndDistance(1, 10, 50)
        clock = GameClock(starting_quarter, 0, 0)
        to = Timeouts(
            timeouts_per_half,
            timeouts_per_half,
            timeouts_per_half,
            timeouts_per_half,
        )
        return GameState(
            scores=Scoreboard(),
            offense=TeamId.RED,
            field=mid,
            downs=downs,
            clock=clock,
            timeouts=to,
        )
