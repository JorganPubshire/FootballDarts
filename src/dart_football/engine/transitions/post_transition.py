from __future__ import annotations

from dataclasses import replace

from dart_football.engine.phases import Phase
from dart_football.engine.transitions.types import TransitionOk
from dart_football.rules.schema import RuleSet


def maybe_first_score_overtime_game_over(ok: TransitionOk, rules: RuleSet) -> TransitionOk:
    st = ok.state
    if st.overtime_period <= 0:
        return ok
    if rules.overtime.template != "first_score":
        return ok
    if ok.phase != Phase.KICKOFF_KICK:
        return ok
    if st.scores.red == st.scores.green:
        return ok
    return TransitionOk(st, Phase.GAME_OVER, f"{ok.effects_summary} | Game over (overtime)")


def maybe_regulation_to_overtime_or_final(
    prev_quarter: int, ok: TransitionOk, rules: RuleSet
) -> TransitionOk:
    st = ok.state
    if st.overtime_period > 0:
        return ok
    qc = rules.structure.quarters
    if prev_quarter != qc or st.clock.quarter != qc + 1:
        return ok
    if st.scores.red != st.scores.green:
        return TransitionOk(st, Phase.GAME_OVER, f"{ok.effects_summary} | Game over (regulation)")
    if not rules.overtime.enabled:
        return TransitionOk(st, Phase.GAME_OVER, f"{ok.effects_summary} | Game over (tie)")
    s_ot = replace(st, overtime_period=1, coin_toss_winner=None)
    return TransitionOk(s_ot, Phase.OVERTIME_START, f"{ok.effects_summary} | Overtime — coin toss")


def post_process_transition_ok(prev_quarter: int, ok: TransitionOk, rules: RuleSet) -> TransitionOk:
    ok = maybe_regulation_to_overtime_or_final(prev_quarter, ok, rules)
    ok = maybe_first_score_overtime_game_over(ok, rules)
    return ok
