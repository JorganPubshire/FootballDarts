from __future__ import annotations

from enum import Enum


class Phase(Enum):
    """Engine waits for the next human-entered outcome for the current phase."""

    PRE_GAME_COIN_TOSS = "pre_game_coin_toss"
    CHOOSE_KICK_OR_RECEIVE = "choose_kick_or_receive"
    KICKOFF_KICK = "kickoff_kick"
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
