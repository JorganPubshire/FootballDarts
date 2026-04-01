"""Dispatch transitions by phase; per-phase logic lives in phase_handlers."""

from __future__ import annotations

from dart_football.engine.events import CallTimeout, Event
from dart_football.engine.phases import Phase
from dart_football.engine.state import GameState
from dart_football.engine.transitions.clock_and_timeouts import apply_timeout
from dart_football.engine.transitions.phase_handlers import (
    handle_after_touchdown_choice,
    handle_choose_kick_or_receive,
    handle_extra_point_attempt,
    handle_field_goal_defense,
    handle_field_goal_fake_offense,
    handle_field_goal_green_choice,
    handle_field_goal_offense_dart,
    handle_fourth_down_decision,
    handle_game_over,
    handle_kickoff_kick,
    handle_kickoff_return_dart,
    handle_kickoff_run_or_spot,
    handle_kickoff_run_out_dart,
    handle_onside_kick,
    handle_overtime_start,
    handle_pre_game_coin_toss,
    handle_punt_attempt,
    handle_safety_sequence,
    handle_scrimmage_defense,
    handle_scrimmage_offense,
    handle_scrimmage_strip_dart,
    handle_two_point_attempt,
)
from dart_football.engine.transitions.post_transition import post_process_transition_ok
from dart_football.engine.transitions.types import TransitionError, TransitionOk
from dart_football.rules.schema import RuleSet


def transition_core(
    state: GameState,
    phase: Phase,
    event: Event,
    rules: RuleSet,
) -> TransitionOk | TransitionError:
    if isinstance(event, CallTimeout):
        if phase in (Phase.PRE_GAME_COIN_TOSS, Phase.GAME_OVER):
            return TransitionError("cannot call timeout in this phase", ())
        return apply_timeout(state, phase, event.team)

    match phase:
        case Phase.PRE_GAME_COIN_TOSS:
            return handle_pre_game_coin_toss(state, event, rules)
        case Phase.CHOOSE_KICK_OR_RECEIVE:
            return handle_choose_kick_or_receive(state, event, rules)
        case Phase.KICKOFF_KICK:
            return handle_kickoff_kick(state, event, rules)
        case Phase.ONSIDE_KICK:
            return handle_onside_kick(state, event, rules)
        case Phase.KICKOFF_RUN_OR_SPOT:
            return handle_kickoff_run_or_spot(state, event, rules)
        case Phase.KICKOFF_RUN_OUT_DART:
            return handle_kickoff_run_out_dart(state, event, rules)
        case Phase.KICKOFF_RETURN_DART:
            return handle_kickoff_return_dart(state, event, rules)
        case Phase.AFTER_TOUCHDOWN_CHOICE:
            return handle_after_touchdown_choice(state, event, rules)
        case Phase.EXTRA_POINT_ATTEMPT:
            return handle_extra_point_attempt(state, event, rules)
        case Phase.TWO_POINT_ATTEMPT:
            return handle_two_point_attempt(state, event, rules)
        case Phase.FOURTH_DOWN_DECISION:
            return handle_fourth_down_decision(state, event, rules)
        case Phase.FIELD_GOAL_OFFENSE_DART:
            return handle_field_goal_offense_dart(state, event, rules)
        case Phase.FIELD_GOAL_GREEN_CHOICE:
            return handle_field_goal_green_choice(state, event, rules)
        case Phase.FIELD_GOAL_FAKE_OFFENSE:
            return handle_field_goal_fake_offense(state, event, rules)
        case Phase.FIELD_GOAL_DEFENSE:
            return handle_field_goal_defense(state, event, rules)
        case Phase.PUNT_ATTEMPT:
            return handle_punt_attempt(state, event, rules)
        case Phase.SCRIMMAGE_OFFENSE:
            return handle_scrimmage_offense(state, event, rules)
        case Phase.SCRIMMAGE_DEFENSE:
            return handle_scrimmage_defense(state, event, rules)
        case Phase.SCRIMMAGE_STRIP_DART:
            return handle_scrimmage_strip_dart(state, event, rules)
        case Phase.SAFETY_SEQUENCE:
            return handle_safety_sequence(state, event, rules)
        case Phase.OVERTIME_START:
            return handle_overtime_start(state, event, rules)
        case Phase.GAME_OVER:
            return handle_game_over(state, event, rules)
        case _:
            return TransitionError(f"unhandled phase {phase!r}", ())


def transition(
    state: GameState,
    phase: Phase,
    event: Event,
    rules: RuleSet,
) -> TransitionOk | TransitionError:
    prev_q = state.clock.quarter
    out = transition_core(state, phase, event, rules)
    if isinstance(out, TransitionOk):
        return post_process_transition_ok(prev_q, out, rules)
    return out
