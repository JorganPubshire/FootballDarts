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
    SCRIMMAGE_STRIP_DART = "scrimmage_strip_dart"
    FOURTH_DOWN_DECISION = "fourth_down_decision"
    FIELD_GOAL_OFFENSE_DART = "field_goal_offense_dart"
    FIELD_GOAL_GREEN_CHOICE = "field_goal_green_choice"
    FIELD_GOAL_FAKE_OFFENSE = "field_goal_fake_offense"
    FIELD_GOAL_DEFENSE = "field_goal_defense"
    PUNT_ATTEMPT = "punt_attempt"
    AFTER_TOUCHDOWN_CHOICE = "after_touchdown_choice"
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
        Phase.SCRIMMAGE_STRIP_DART,
        Phase.FOURTH_DOWN_DECISION,
    )


# Saved sessions may use older phase string values.
_PHASE_VALUE_ALIASES: dict[str, Phase] = {
    "pat_or_two_decision": Phase.AFTER_TOUCHDOWN_CHOICE,
    "field_goal_attempt": Phase.FIELD_GOAL_OFFENSE_DART,
}


def phase_from_stored(value: str) -> Phase:
    p = _PHASE_VALUE_ALIASES.get(value)
    if p is not None:
        return p
    return Phase(value)
