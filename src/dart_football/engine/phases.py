from __future__ import annotations

from enum import Enum


class Phase(Enum):
    """Engine waits for the next human-entered outcome for the current phase."""

    PRE_GAME_COIN_TOSS = "pre_game_coin_toss"
    CHOOSE_KICK_OR_RECEIVE = "choose_kick_or_receive"
    KICKOFF_KICK = "kickoff_kick"
    KICKOFF_RUN_OR_SPOT = "kickoff_run_or_spot"
    KICKOFF_RUN_OUT_DART = "kickoff_run_out_dart"
    KICKOFF_RETURN_DART = "kickoff_return_dart"
    SCRIMMAGE_OFFENSE = "scrimmage_offense"
    SCRIMMAGE_DEFENSE = "scrimmage_defense"
    FOURTH_DOWN_DECISION = "fourth_down_decision"
    FIELD_GOAL_ATTEMPT = "field_goal_attempt"
    PUNT_ATTEMPT = "punt_attempt"
    PAT_OR_TWO_DECISION = "pat_or_two_decision"
    EXTRA_POINT_ATTEMPT = "extra_point_attempt"
    TWO_POINT_ATTEMPT = "two_point_attempt"
    SAFETY_SEQUENCE = "safety_sequence"
    ONSIDE_KICK = "onside_kick"
    OVERTIME_START = "overtime_start"
    GAME_OVER = "game_over"


def is_scrimmage_play_phase(phase: Phase | None) -> bool:
    """True when the ball is in a normal scrimmage series (down & distance apply)."""
    if phase is None:
        return False
    return phase in (
        Phase.SCRIMMAGE_OFFENSE,
        Phase.SCRIMMAGE_DEFENSE,
        Phase.FOURTH_DOWN_DECISION,
    )
