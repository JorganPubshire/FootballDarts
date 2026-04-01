from __future__ import annotations

from dataclasses import replace

from dart_football.engine.phases import Phase
from dart_football.engine.state import GameClock, GameState, TeamId
from dart_football.engine.transitions.types import TransitionError, TransitionOk
from dart_football.rules.schema import RuleSet


def bump_clock_after_play(state: GameState, rules: RuleSet) -> GameClock:
    c = state.clock
    pq = rules.structure.plays_per_quarter
    plays_q = c.plays_in_quarter + 1
    quarter = c.quarter
    if pq > 0 and plays_q >= pq:
        plays_q = 0
        quarter = quarter + 1
    return GameClock(
        quarter=quarter,
        plays_in_quarter=plays_q,
        total_plays=c.total_plays + 1,
    )


def advance_clock_for_scrimmage_play(
    state: GameState, rules: RuleSet
) -> tuple[GameClock, GameState]:
    """Increment play counters unless this resolution follows a timeout (next snap not counted)."""
    if state.skip_next_play_clock_bump:
        return state.clock, replace(state, skip_next_play_clock_bump=False)
    return bump_clock_after_play(state, rules), state


def kickoff_resolve_timeout_state(state: GameState) -> GameState:
    """Kickoffs are not counted plays; still consume skip_next_play_clock_bump if set (timeout rule)."""
    if state.skip_next_play_clock_bump:
        return replace(state, skip_next_play_clock_bump=False)
    return state


def apply_timeout(state: GameState, phase: Phase, team: TeamId) -> TransitionOk | TransitionError:
    """Use one timeout for the current half (Q1–2 vs Q3+). Does not bump clock."""
    q = state.clock.quarter
    first_half = q <= 2
    t = state.timeouts
    if team is TeamId.RED:
        if first_half:
            if t.red_q1_q2 <= 0:
                return TransitionError("Red has no timeouts left in this half", ())
            nt = replace(t, red_q1_q2=t.red_q1_q2 - 1)
            left = nt.red_q1_q2
        else:
            if t.red_q3_q4 <= 0:
                return TransitionError("Red has no timeouts left in this half", ())
            nt = replace(t, red_q3_q4=t.red_q3_q4 - 1)
            left = nt.red_q3_q4
    else:
        if first_half:
            if t.green_q1_q2 <= 0:
                return TransitionError("Green has no timeouts left in this half", ())
            nt = replace(t, green_q1_q2=t.green_q1_q2 - 1)
            left = nt.green_q1_q2
        else:
            if t.green_q3_q4 <= 0:
                return TransitionError("Green has no timeouts left in this half", ())
            nt = replace(t, green_q3_q4=t.green_q3_q4 - 1)
            left = nt.green_q3_q4
    label = "Red" if team is TeamId.RED else "Green"
    half = "1st half" if first_half else "2nd half"
    s = replace(state, timeouts=nt, skip_next_play_clock_bump=True)
    return TransitionOk(
        s,
        phase,
        f"{label} timeout (no play counted; next play won't advance play counter; {left} left in {half})",
    )
