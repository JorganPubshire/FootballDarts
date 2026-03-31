from __future__ import annotations

from dataclasses import replace
from typing import Literal

from dart_football.display.formatting import format_possession_summary, yards_from_own_goal
from dart_football.engine.events import (
    CallTimeout,
    ConfirmSafetyKickoff,
    ChooseFieldGoalAfterGreen,
    ChooseKickoffKind,
    ChooseKickoffTouchbackOrRun,
    ChooseKickOrReceive,
    ChooseExtraPointOrTwo,
    CoinTossWinner,
    Event,
    ExtraPointOutcome,
    FieldGoalDefenseDart,
    FieldGoalFakeOffenseDart,
    FieldGoalOffenseDart,
    FieldGoalOutcome,
    FourthDownChoice,
    KickoffKick,
    KickoffReturnKick,
    KickoffRunOutKick,
    PuntKick,
    ScrimmageDefense,
    ScrimmageOffense,
    ScrimmageStripDart,
    TwoPointOutcome,
)
from dart_football.engine.phases import Phase
from dart_football.engine.state import DownAndDistance, FieldPosition, GameClock, GameState, TeamId
from dart_football.rules.schema import KickoffBand, RuleSet, ScrimmageYardBand


class TransitionOk:
    __slots__ = ("state", "phase", "effects_summary")

    def __init__(self, state: GameState, phase: Phase, effects_summary: str) -> None:
        self.state = state
        self.phase = phase
        self.effects_summary = effects_summary


class TransitionError:
    __slots__ = ("message", "allowed_events")

    def __init__(self, message: str, allowed_events: tuple[str, ...]) -> None:
        self.message = message
        self.allowed_events = allowed_events


def _other(team: TeamId) -> TeamId:
    return TeamId.GREEN if team is TeamId.RED else TeamId.RED


def _kickoff_tee_field(kicker: TeamId) -> FieldPosition:
    """Kickoff spotted at the kicker's 35-yard line (NFL-style)."""
    if kicker is TeamId.RED:
        return FieldPosition(35, 100)
    return FieldPosition(65, 0)


def _kickoff_tee_downs(kicker: TeamId) -> DownAndDistance:
    fp = _kickoff_tee_field(kicker)
    return DownAndDistance(1, 10, fp.scrimmage_line)


def _field_spot_from_own_yard(receiver: TeamId, own_yard: int) -> FieldPosition:
    if own_yard < 1 or own_yard > 99:
        raise ValueError("own_yard must be 1..99")
    if receiver is TeamId.RED:
        return FieldPosition(scrimmage_line=own_yard, goal_yard=100)
    return FieldPosition(scrimmage_line=100 - own_yard, goal_yard=0)


def _field_from_spot_band(receiver: TeamId, band: KickoffBand, segment: int) -> FieldPosition:
    """Kickoff/punt: fixed own yard, or wedge × multiplier."""
    if band.kind == "touchback":
        assert band.touchback_line is not None
        return _field_spot_from_own_yard(receiver, band.touchback_line)
    if band.kind == "field":
        assert band.field_yard_from_receiving_goal is not None
        return _field_spot_from_own_yard(receiver, band.field_yard_from_receiving_goal)
    if band.kind == "wedge_times":
        assert band.multiplier is not None
        own = min(99, max(1, segment * band.multiplier))
        return _field_spot_from_own_yard(receiver, own)
    if band.kind == "wedge_times_penalty":
        assert band.multiplier is not None and band.penalty_yards is not None
        raw = segment * band.multiplier - band.penalty_yards
        own = min(99, max(1, raw))
        return _field_spot_from_own_yard(receiver, own)
    raise ValueError(f"unknown spot band kind: {band.kind!r}")


def _kickoff_green_bull_field(kicker: TeamId) -> FieldPosition:
    """Receiving-team fumble; kicking team recovers at opponent's 35-yard line."""
    if kicker is TeamId.RED:
        return _field_spot_from_own_yard(kicker, 35)
    return _field_spot_from_own_yard(kicker, 65)


def _match_spot_band(bands: tuple[KickoffBand, ...], segment: int) -> KickoffBand | None:
    for b in bands:
        if segment in b.segments:
            return b
    return None


def _bump_clock(state: GameState, rules: RuleSet) -> GameClock:
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


def _advance_clock_for_play(state: GameState, rules: RuleSet) -> tuple[GameClock, GameState]:
    """Increment play counters unless this resolution follows a timeout (next snap not counted)."""
    if state.skip_next_play_clock_bump:
        return state.clock, replace(state, skip_next_play_clock_bump=False)
    return _bump_clock(state, rules), state


def _kickoff_resolve_state(state: GameState) -> GameState:
    """Kickoffs are not counted plays; still consume skip_next_play_clock_bump if set (timeout rule)."""
    if state.skip_next_play_clock_bump:
        return replace(state, skip_next_play_clock_bump=False)
    return state


def _call_timeout(state: GameState, phase: Phase, team: TeamId) -> TransitionOk | TransitionError:
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


def _match_scrimmage_yards(bands: tuple[ScrimmageYardBand, ...], segment: int) -> int | None:
    for b in bands:
        if segment in b.segments:
            return b.yards
    return None


def _yards_to_goal_line(field: FieldPosition) -> int:
    return abs(field.goal_yard - field.scrimmage_line)


def _advance_field(field: FieldPosition, net_toward_goal: int) -> FieldPosition:
    g = field.goal_yard
    s = field.scrimmage_line
    if g == 100:
        ns = s + net_toward_goal
    else:
        ns = s - net_toward_goal
    ns = max(0, min(100, ns))
    return FieldPosition(ns, g)


def _is_touchdown(field: FieldPosition) -> bool:
    if field.goal_yard == 100:
        return field.scrimmage_line >= 100
    return field.scrimmage_line <= 0


def _is_safety(field: FieldPosition) -> bool:
    """Offense is down in their own end zone (ball spotted on or past own goal)."""
    if field.goal_yard == 100:
        return field.scrimmage_line <= 0
    return field.scrimmage_line >= 100


def _safety_free_kick_tee_field(kicker: TeamId, rules: RuleSet) -> FieldPosition:
    y = rules.safety.free_kick_own_yard
    y = max(1, min(99, y))
    return _field_spot_from_own_yard(kicker, y)


def _setup_safety_free_kick(state: GameState, kicker: TeamId, receiver: TeamId, rules: RuleSet) -> GameState:
    fp = _safety_free_kick_tee_field(kicker, rules)
    downs = DownAndDistance(1, 10, fp.scrimmage_line)
    return replace(
        state,
        last_touchdown_team=None,
        kickoff_kicker=kicker,
        kickoff_receiver=receiver,
        offense=kicker,
        field=fp,
        downs=downs,
        declared_fg_attempt=False,
        declared_punt=False,
        declared_onside=False,
        kickoff_type_selected=False,
        scrimmage_pending_offense_yards=None,
        scrimmage_pending_offense_kind="none",
        scrimmage_pending_offense_eff_segment=None,
        kickoff_awaiting="none",
        kickoff_pending_touchback_line=None,
        fg_snap_field=None,
        fg_pending_outcome="none",
        fg_fake_first_down_line=None,
    )


def _maybe_first_score_ot_game_over(ok: TransitionOk, rules: RuleSet) -> TransitionOk:
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


def _maybe_regulation_to_overtime_or_final(prev_quarter: int, ok: TransitionOk, rules: RuleSet) -> TransitionOk:
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


def _post_process_transition_ok(prev_quarter: int, ok: TransitionOk, rules: RuleSet) -> TransitionOk:
    ok = _maybe_regulation_to_overtime_or_final(prev_quarter, ok, rules)
    ok = _maybe_first_score_ot_game_over(ok, rules)
    return ok


def _state_after_td(state: GameState, scoring: TeamId, rules: RuleSet) -> GameState:
    return replace(
        state,
        scores=state.scores.add(scoring, rules.scoring.touchdown),
        last_touchdown_team=scoring,
        offense=scoring,
        field=FieldPosition(50, 100),
        downs=DownAndDistance(1, 10, 50),
        kickoff_kicker=None,
        kickoff_receiver=None,
        kickoff_awaiting="none",
        kickoff_pending_touchback_line=None,
        scrimmage_pending_offense_yards=None,
        scrimmage_pending_offense_kind="none",
        scrimmage_pending_offense_eff_segment=None,
        declared_fg_attempt=False,
        declared_punt=False,
        fg_snap_field=None,
        fg_pending_outcome="none",
        fg_fake_first_down_line=None,
        safety_pending_kicker=None,
    )


def _setup_kickoff_after_score(state: GameState, scoring: TeamId, rules: RuleSet) -> GameState:
    other = _other(scoring)
    fp = _kickoff_tee_field(scoring)
    downs = _kickoff_tee_downs(scoring)
    return replace(
        state,
        last_touchdown_team=None,
        kickoff_kicker=scoring,
        kickoff_receiver=other,
        offense=scoring,
        field=fp,
        downs=downs,
        declared_fg_attempt=False,
        declared_punt=False,
        declared_onside=False,
        kickoff_type_selected=False,
        scrimmage_pending_offense_yards=None,
        scrimmage_pending_offense_kind="none",
        scrimmage_pending_offense_eff_segment=None,
        kickoff_awaiting="none",
        kickoff_pending_touchback_line=None,
        safety_pending_kicker=None,
        fg_snap_field=None,
        fg_pending_outcome="none",
        fg_fake_first_down_line=None,
    )


def _receiver_goal_line_field(receiver: TeamId) -> FieldPosition:
    """Receiving team's own goal line (run-out starting point)."""
    if receiver is TeamId.RED:
        return FieldPosition(0, 100)
    return FieldPosition(100, 0)


def _finish_kickoff_to_scrimmage(
    state: GameState,
    rules: RuleSet,
    receiver: TeamId,
    field: FieldPosition,
    summary: str,
) -> TransitionOk:
    st = _kickoff_resolve_state(state)
    downs = DownAndDistance(down=1, to_go=10, los_yard=field.scrimmage_line)
    s = replace(
        st,
        offense=receiver,
        field=field,
        downs=downs,
        clock=st.clock,
        kickoff_kicker=None,
        kickoff_receiver=None,
        kickoff_awaiting="none",
        kickoff_pending_touchback_line=None,
        scrimmage_pending_offense_yards=None,
        last_touchdown_team=None,
        declared_onside=False,
    )
    return TransitionOk(
        s,
        Phase.SCRIMMAGE_OFFENSE,
        f"{summary} — {format_possession_summary(s)}",
    )


def _finish_kickoff_return_touchdown(
    state: GameState,
    receiver: TeamId,
    rules: RuleSet,
    summary: str,
) -> TransitionOk:
    st = _kickoff_resolve_state(state)
    s2 = replace(
        st,
        kickoff_kicker=None,
        kickoff_receiver=None,
        kickoff_awaiting="none",
        kickoff_pending_touchback_line=None,
        declared_onside=False,
        scrimmage_pending_offense_yards=None,
    )
    s_td = _state_after_td(s2, receiver, rules)
    return TransitionOk(
        s_td,
        Phase.AFTER_TOUCHDOWN_CHOICE,
        f"{summary} — TD {receiver.value}! (+{rules.scoring.touchdown})",
    )


def _run_out_net_yards(event: KickoffRunOutKick, rules: RuleSet) -> int | None:
    """Return net return yards toward the goal, or None if receiving-team TD."""
    if event.bull == "green":
        return 50
    if event.bull == "red":
        return None
    seg = event.segment
    if seg < rules.kickoff.segment_min or seg > rules.kickoff.segment_max:
        raise ValueError("segment out of range")
    if 1 <= seg <= 12:
        return 25
    if 13 <= seg <= 20:
        return seg * 2
    raise ValueError("segment out of range")


def _return_dart_net_yards(event: KickoffReturnKick, rules: RuleSet) -> int | None:
    if event.bull == "green":
        return 50
    if event.bull == "red":
        return None
    seg = event.segment
    sc = rules.scrimmage
    if seg < sc.segment_min or seg > sc.segment_max:
        raise ValueError("segment out of range")
    if 1 <= seg <= 12:
        return 12
    if 13 <= seg <= 20:
        mult = 1
        if event.triple_ring:
            mult *= sc.triple_multiplier
        if event.double_ring:
            mult *= sc.double_multiplier
        return seg * mult
    raise ValueError("segment out of range")


def _apply_kickoff_dart(
    state: GameState,
    event: KickoffKick,
    rules: RuleSet,
    *,
    onside_attempt: bool,
) -> TransitionOk | TransitionError:
    """Resolve kick dart (regular or onside); may enter run/return follow-up before scrimmage."""
    kicker = state.kickoff_kicker
    receiver = state.kickoff_receiver
    assert kicker is not None and receiver is not None
    label = "Onside kick" if onside_attempt else "Kickoff"

    if event.bull == "green":
        st = _kickoff_resolve_state(state)
        field = _kickoff_green_bull_field(kicker)
        downs = DownAndDistance(down=1, to_go=10, los_yard=field.scrimmage_line)
        s = replace(
            st,
            offense=kicker,
            field=field,
            downs=downs,
            clock=st.clock,
            kickoff_kicker=None,
            kickoff_receiver=None,
            kickoff_awaiting="none",
            kickoff_pending_touchback_line=None,
            scrimmage_pending_offense_yards=None,
            last_touchdown_team=None,
            declared_onside=False,
        )
        return TransitionOk(
            s,
            Phase.SCRIMMAGE_OFFENSE,
            f"{label} green bull: receiving fumble — kicking team ball at opponent 35",
        )

    if event.bull == "red":
        st = _kickoff_resolve_state(state)
        s2 = replace(
            st,
            kickoff_kicker=None,
            kickoff_receiver=None,
            kickoff_awaiting="none",
            kickoff_pending_touchback_line=None,
            declared_onside=False,
        )
        s_td = _state_after_td(s2, kicker, rules)
        return TransitionOk(
            s_td,
            Phase.AFTER_TOUCHDOWN_CHOICE,
            f"{label} red bull: receiving fumble — touchdown {kicker.value} (+{rules.scoring.touchdown})",
        )

    seg = event.segment
    if seg < rules.kickoff.segment_min or seg > rules.kickoff.segment_max:
        return TransitionError(
            f"segment must be {rules.kickoff.segment_min}..{rules.kickoff.segment_max}",
            ("KickoffKick",),
        )
    band = _match_spot_band(rules.kickoff.bands, seg)
    if band is None:
        return TransitionError(f"no kickoff band for segment {seg}", ("KickoffKick",))

    if not onside_attempt and band.kind == "touchback" and band.allow_runout_choice:
        assert band.touchback_line is not None
        goal = _receiver_goal_line_field(receiver)
        downs = DownAndDistance(1, 10, goal.scrimmage_line)
        s = replace(
            state,
            offense=receiver,
            field=goal,
            downs=downs,
            kickoff_awaiting="run_or_spot",
            kickoff_pending_touchback_line=band.touchback_line,
            declared_onside=False,
        )
        return TransitionOk(
            s,
            Phase.KICKOFF_RUN_OR_SPOT,
            f"{label} wedge {seg} — take ball at own {band.touchback_line} or run out from goal line",
        )

    if not onside_attempt and band.kind == "wedge_times" and band.requires_return_dart:
        field = _field_from_spot_band(receiver, band, seg)
        downs = DownAndDistance(1, 10, field.scrimmage_line)
        s = replace(
            state,
            offense=receiver,
            field=field,
            downs=downs,
            kickoff_awaiting="return_dart",
            kickoff_pending_touchback_line=None,
            declared_onside=False,
        )
        return TransitionOk(
            s,
            Phase.KICKOFF_RETURN_DART,
            f"{label} wedge {seg} — return dart from kick spot ({format_possession_summary(s)})",
        )

    st = _kickoff_resolve_state(state)
    field = _field_from_spot_band(receiver, band, seg)
    downs = DownAndDistance(down=1, to_go=10, los_yard=field.scrimmage_line)
    s = replace(
        st,
        offense=receiver,
        field=field,
        downs=downs,
        clock=st.clock,
        kickoff_kicker=None,
        kickoff_receiver=None,
        kickoff_awaiting="none",
        kickoff_pending_touchback_line=None,
        scrimmage_pending_offense_yards=None,
        last_touchdown_team=None,
        declared_onside=False,
    )
    summary = f"{label} wedge {seg} → {format_possession_summary(s)}"
    return TransitionOk(s, Phase.SCRIMMAGE_OFFENSE, summary)


def _effective_segment_bull(
    segment: int,
    bull: Literal["none", "green", "red"],
    rules: RuleSet,
) -> int:
    if bull == "green":
        return rules.scrimmage.bull_green_segment
    if bull == "red":
        return rules.scrimmage.bull_red_segment
    return segment


# Standard dartboard: clockwise from top; adjacent wedges alternate black/cream.
_WEDGE_ORDER_CLOCKWISE = (
    20,
    1,
    18,
    4,
    13,
    6,
    10,
    15,
    2,
    17,
    3,
    19,
    7,
    16,
    8,
    11,
    14,
    9,
    12,
    5,
)


def _wedge_board_color_parity(segment: int) -> int:
    return _WEDGE_ORDER_CLOCKWISE.index(segment) % 2


def _wedge_board_colors_match(offense_eff: int, defense_segment: int) -> bool:
    return _wedge_board_color_parity(offense_eff) == _wedge_board_color_parity(defense_segment)


def _defensive_touchdown_after_offense_yards(
    state: GameState, rules: RuleSet, off_yards: int, summary_prefix: str
) -> TransitionOk:
    new_clock, st = _advance_clock_for_play(state, rules)
    s_inter = replace(
        st,
        clock=new_clock,
        scrimmage_pending_offense_yards=None,
        scrimmage_pending_offense_kind="none",
        scrimmage_pending_offense_eff_segment=None,
    )
    scoring = _other(state.offense)
    s_td = _state_after_td(s_inter, scoring, rules)
    return TransitionOk(
        s_td,
        Phase.AFTER_TOUCHDOWN_CHOICE,
        f"{summary_prefix} — defensive TD {scoring.value}! (+{rules.scoring.touchdown})",
    )


def _no_gain_advance_down(
    state_after_clock: GameState,
    state_before_play: GameState,
    field: FieldPosition,
    summary: str,
) -> TransitionOk:
    down = state_before_play.downs.down + 1
    to_go = state_before_play.downs.to_go
    if down > 4:
        s_to = _turnover_on_downs_state(state_after_clock, field)
        return TransitionOk(
            s_to,
            Phase.SCRIMMAGE_OFFENSE,
            f"{summary} | turnover on downs",
        )
    downs = DownAndDistance(down, to_go, field.scrimmage_line)
    s_final = replace(state_after_clock, downs=downs, field=field)
    next_phase = Phase.FOURTH_DOWN_DECISION if down == 4 else Phase.SCRIMMAGE_OFFENSE
    return TransitionOk(s_final, next_phase, f"{summary} | down {down} & {to_go}")


def _finish_scrimmage_net_play(
    state_before: GameState,
    rules: RuleSet,
    s_inter: GameState,
    new_field: FieldPosition,
    off_yards: int,
    def_yards: int,
    net: int,
    dn: str,
) -> TransitionOk:
    if _is_touchdown(new_field):
        scoring = state_before.offense
        s_td = _state_after_td(s_inter, scoring, rules)
        return TransitionOk(
            s_td,
            Phase.AFTER_TOUCHDOWN_CHOICE,
            f"Play: off {off_yards} vs def {def_yards}{dn} → net {net} yds | TD {scoring.value}! (+{rules.scoring.touchdown})",
        )
    if _is_safety(new_field):
        defense_scored = _other(state_before.offense)
        s_safe = replace(
            s_inter,
            field=new_field,
            downs=DownAndDistance(1, min(10, _yards_to_goal_line(new_field)), new_field.scrimmage_line),
            scores=s_inter.scores.add(defense_scored, rules.scoring.safety),
            safety_pending_kicker=state_before.offense,
            scrimmage_pending_offense_yards=None,
            scrimmage_pending_offense_kind="none",
            scrimmage_pending_offense_eff_segment=None,
        )
        return TransitionOk(
            s_safe,
            Phase.SAFETY_SEQUENCE,
            f"Safety! {defense_scored.value} +{rules.scoring.safety} — confirm free kick when ready",
        )
    dist = _yards_to_goal_line(new_field)
    to_go_before = state_before.downs.to_go
    if net >= to_go_before:
        down = 1
        to_go = min(10, dist)
    else:
        down = state_before.downs.down + 1
        to_go = to_go_before - net
    if down > 4:
        s_to = _turnover_on_downs_state(s_inter, new_field)
        return TransitionOk(
            s_to,
            Phase.SCRIMMAGE_OFFENSE,
            f"Play: net {net} yds{dn} | turnover on downs",
        )
    downs = DownAndDistance(down, to_go, new_field.scrimmage_line)
    s_final = replace(s_inter, downs=downs)
    next_phase = Phase.FOURTH_DOWN_DECISION if down == 4 else Phase.SCRIMMAGE_OFFENSE
    return TransitionOk(
        s_final,
        next_phase,
        f"Play: off {off_yards} vs def {def_yards}{dn} → net {net} yds | down {down} & {to_go}",
    )


def _defense_ring_note(event: ScrimmageDefense) -> str:
    if event.bull != "none":
        return f" (def bull {event.bull})"
    parts: list[str] = []
    if event.double_ring:
        parts.append("D")
    if event.triple_ring:
        t = "T"
        if event.triple_inner is True:
            t += " in"
        elif event.triple_inner is False:
            t += " out"
        parts.append(t)
    if not parts:
        return ""
    return f" [{'/'.join(parts)} log]"


def _round_up_to_10(yards: int) -> int:
    return ((yards + 9) // 10) * 10


def _sixty_yard_fg_line_ok(state: GameState) -> bool:
    """60-yard field goals only from own 40 to 49."""
    dist = _yards_to_goal_line(state.field)
    if _round_up_to_10(dist) != 60:
        return True
    own = yards_from_own_goal(state.offense, state.field)
    return 40 <= own <= 49


def _field_after_missed_field_goal(state: GameState, rules: RuleSet) -> GameState:
    """Missed/blocked FG — opponent takes over at previous line of scrimmage +10 yards."""
    opp = _other(state.offense)
    fp = state.field
    s, g = fp.scrimmage_line, fp.goal_yard
    dy = rules.field_goal.miss_spot_offset_yards
    if g == 100:
        new_line = min(99, s + dy)
    else:
        new_line = max(1, s - dy)
    new_goal = 100 if opp is TeamId.RED else 0
    nf = FieldPosition(new_line, new_goal)
    dist = _yards_to_goal_line(nf)
    downs = DownAndDistance(1, min(10, dist), new_line)
    return replace(
        state,
        offense=opp,
        field=nf,
        downs=downs,
        declared_fg_attempt=False,
        declared_punt=False,
        scrimmage_pending_offense_yards=None,
        scrimmage_pending_offense_kind="none",
        scrimmage_pending_offense_eff_segment=None,
        fg_snap_field=None,
        fg_pending_outcome="none",
        fg_fake_first_down_line=None,
        safety_pending_kicker=None,
    )


def _fg_clear_sequence_fields() -> dict:
    return {
        "fg_snap_field": None,
        "fg_pending_outcome": "none",
        "fg_fake_first_down_line": None,
        "declared_fg_attempt": False,
        "safety_pending_kicker": None,
    }


def _team_fg_board_parity(team: TeamId) -> int:
    return 0 if team is TeamId.RED else 1


def _first_down_line_yard(field: FieldPosition, downs: DownAndDistance) -> int:
    s, g = field.scrimmage_line, field.goal_yard
    t = downs.to_go
    if g == 100:
        return min(100, s + t)
    return max(0, s - t)


def _fake_fg_defense_green_field(field: FieldPosition, first_down_line: int) -> FieldPosition:
    g = field.goal_yard
    if g == 100:
        one_short = max(0, first_down_line - 1)
        own_eleven = 11
        s_new = min(one_short, own_eleven)
    else:
        one_short = min(100, first_down_line + 1)
        own_eleven = 89
        s_new = max(one_short, own_eleven)
    return FieldPosition(s_new, g)


def _field_goal_fake_yards(event: FieldGoalFakeOffenseDart, rules: RuleSet) -> int | None:
    sc = rules.scrimmage
    eff = event.segment if event.bull == "none" else _effective_segment_bull(event.segment, event.bull, rules)
    if eff < sc.segment_min or eff > sc.segment_max:
        return None
    if not sc.use_wedge_number_yards:
        return None
    if event.bull == "red":
        return 0
    if event.bull == "green":
        return eff
    mult = 1
    if event.triple_ring:
        mult *= sc.triple_multiplier
    if event.double_ring:
        mult *= sc.double_multiplier
    return eff * mult


def _defensive_takeover_at_spot(state: GameState, spot: FieldPosition) -> GameState:
    """Previous defense is now on offense at spot.scrimmage_line; goal flips for the new drive."""
    new_off = _other(state.offense)
    new_goal = 100 if spot.goal_yard == 0 else 0
    nf = FieldPosition(spot.scrimmage_line, new_goal)
    dist = _yards_to_goal_line(nf)
    downs = DownAndDistance(1, min(10, dist), nf.scrimmage_line)
    return replace(
        state,
        offense=new_off,
        field=nf,
        downs=downs,
        scrimmage_pending_offense_yards=None,
        scrimmage_pending_offense_kind="none",
        scrimmage_pending_offense_eff_segment=None,
        declared_fg_attempt=False,
        declared_punt=False,
        safety_pending_kicker=None,
    )


def _turnover_on_downs_state(state: GameState, field: FieldPosition) -> GameState:
    return _defensive_takeover_at_spot(state, field)


def _transition_core(
    state: GameState,
    phase: Phase,
    event: Event,
    rules: RuleSet,
) -> TransitionOk | TransitionError:
    if isinstance(event, CallTimeout):
        if phase in (Phase.PRE_GAME_COIN_TOSS, Phase.GAME_OVER):
            return TransitionError("cannot call timeout in this phase", ())
        return _call_timeout(state, phase, event.team)

    if phase is Phase.PRE_GAME_COIN_TOSS:
        if not isinstance(event, CoinTossWinner):
            return TransitionError("expected coin toss winner", ("CoinTossWinner",))
        s = replace(state, coin_toss_winner=event.winner)
        return TransitionOk(
            s,
            Phase.CHOOSE_KICK_OR_RECEIVE,
            f"Coin toss winner: {event.winner.value}",
        )

    if phase is Phase.CHOOSE_KICK_OR_RECEIVE:
        if state.coin_toss_winner is None:
            return TransitionError("internal: missing coin_toss_winner", ())
        if not isinstance(event, ChooseKickOrReceive):
            return TransitionError("expected kick/receive choice", ("ChooseKickOrReceive",))
        w = state.coin_toss_winner
        loser = _other(w)
        if event.kick:
            kicker, receiver = w, loser
        else:
            kicker, receiver = loser, w
        fp = _kickoff_tee_field(kicker)
        downs = _kickoff_tee_downs(kicker)
        s = replace(
            state,
            kickoff_kicker=kicker,
            kickoff_receiver=receiver,
            offense=kicker,
            field=fp,
            downs=downs,
            kickoff_type_selected=False,
            declared_onside=False,
        )
        return TransitionOk(
            s,
            Phase.KICKOFF_KICK,
            f"Kickoff: {kicker.value} kicks, {receiver.value} receives",
        )

    if phase is Phase.KICKOFF_KICK:
        if state.kickoff_kicker is None or state.kickoff_receiver is None:
            return TransitionError("internal: kickoff teams not set", ())
        if not state.kickoff_type_selected:
            if not isinstance(event, ChooseKickoffKind):
                return TransitionError(
                    "kicker must choose regular kickoff or onside kick first",
                    ("ChooseKickoffKind",),
                )
            if event.onside:
                s = replace(state, kickoff_type_selected=True, declared_onside=True)
                return TransitionOk(
                    s,
                    Phase.ONSIDE_KICK,
                    "Onside kick — kicker throws next",
                )
            s = replace(state, kickoff_type_selected=True, declared_onside=False)
            return TransitionOk(s, Phase.KICKOFF_KICK, "Regular kickoff — kicker throws next")
        if isinstance(event, ChooseKickoffKind):
            return TransitionError("kickoff type already chosen", ("KickoffKick",))
        if not isinstance(event, KickoffKick):
            return TransitionError("expected kickoff segment", ("KickoffKick",))
        out = _apply_kickoff_dart(state, event, rules, onside_attempt=False)
        if isinstance(out, TransitionError):
            return out
        return out

    if phase is Phase.ONSIDE_KICK:
        if state.kickoff_kicker is None or state.kickoff_receiver is None:
            return TransitionError("internal: kickoff teams not set", ())
        if not isinstance(event, KickoffKick):
            return TransitionError("expected onside kick dart", ("KickoffKick",))
        out = _apply_kickoff_dart(state, event, rules, onside_attempt=True)
        if isinstance(out, TransitionError):
            return out
        return out

    if phase is Phase.KICKOFF_RUN_OR_SPOT:
        if state.kickoff_awaiting != "run_or_spot" or state.kickoff_receiver is None:
            return TransitionError("internal: not awaiting touchback vs run-out choice", ())
        if not isinstance(event, ChooseKickoffTouchbackOrRun):
            return TransitionError(
                "choose touchback at the listed yard line or run out from the goal line",
                ("ChooseKickoffTouchbackOrRun",),
            )
        recv = state.kickoff_receiver
        if state.offense != recv:
            return TransitionError("internal: offense should be receiving team", ())
        line = state.kickoff_pending_touchback_line
        if line is None:
            return TransitionError("internal: missing touchback yard line", ())
        if event.take_touchback:
            field = _field_spot_from_own_yard(recv, line)
            return _finish_kickoff_to_scrimmage(state, rules, recv, field, f"Touchback — ball at own {line}")
        goal = _receiver_goal_line_field(recv)
        downs = DownAndDistance(1, 10, goal.scrimmage_line)
        s = replace(
            state,
            field=goal,
            downs=downs,
            kickoff_awaiting="run_out_dart",
        )
        return TransitionOk(
            s,
            Phase.KICKOFF_RUN_OUT_DART,
            "Run out from goal line — receiving team throws the run-out dart",
        )

    if phase is Phase.KICKOFF_RUN_OUT_DART:
        if state.kickoff_awaiting != "run_out_dart" or state.kickoff_receiver is None:
            return TransitionError("internal: not awaiting run-out dart", ())
        if not isinstance(event, KickoffRunOutKick):
            return TransitionError("expected run-out dart", ("KickoffRunOutKick",))
        recv = state.kickoff_receiver
        if state.offense != recv:
            return TransitionError("internal: offense should be receiving team", ())
        try:
            net = _run_out_net_yards(event, rules)
        except ValueError:
            return TransitionError(
                f"run-out wedge must be {rules.kickoff.segment_min}..{rules.kickoff.segment_max}",
                ("KickoffRunOutKick",),
            )
        if net is None:
            return _finish_kickoff_return_touchdown(
                state,
                recv,
                rules,
                "Run-out red bull — kick return touchdown",
            )
        nf = _advance_field(state.field, net)
        if _is_touchdown(nf):
            s_mid = replace(state, field=nf)
            return _finish_kickoff_return_touchdown(
                s_mid,
                recv,
                rules,
                f"Run-out +{net} yd — end zone",
            )
        return _finish_kickoff_to_scrimmage(state, rules, recv, nf, f"Run-out +{net} yd")

    if phase is Phase.KICKOFF_RETURN_DART:
        if state.kickoff_awaiting != "return_dart" or state.kickoff_receiver is None:
            return TransitionError("internal: not awaiting return dart", ())
        if not isinstance(event, KickoffReturnKick):
            return TransitionError("expected return dart", ("KickoffReturnKick",))
        recv = state.kickoff_receiver
        if state.offense != recv:
            return TransitionError("internal: offense should be receiving team", ())
        try:
            net = _return_dart_net_yards(event, rules)
        except ValueError:
            return TransitionError(
                f"return wedge must be {rules.scrimmage.segment_min}..{rules.scrimmage.segment_max}",
                ("KickoffReturnKick",),
            )
        if net is None:
            return _finish_kickoff_return_touchdown(
                state,
                recv,
                rules,
                "Return red bull — kick return touchdown",
            )
        nf = _advance_field(state.field, net)
        if _is_touchdown(nf):
            s_mid = replace(state, field=nf)
            return _finish_kickoff_return_touchdown(
                s_mid,
                recv,
                rules,
                f"Return +{net} yd — end zone",
            )
        return _finish_kickoff_to_scrimmage(state, rules, recv, nf, f"Return +{net} yd")

    if phase is Phase.AFTER_TOUCHDOWN_CHOICE:
        if not isinstance(event, ChooseExtraPointOrTwo):
            return TransitionError(
                "expected extra point or two-point choice",
                ("ChooseExtraPointOrTwo",),
            )
        if state.last_touchdown_team is None:
            return TransitionError("internal: missing last_touchdown_team", ())
        if event.extra_point:
            return TransitionOk(state, Phase.EXTRA_POINT_ATTEMPT, "Extra point attempt")
        return TransitionOk(state, Phase.TWO_POINT_ATTEMPT, "Two-point attempt")

    if phase is Phase.EXTRA_POINT_ATTEMPT:
        if not isinstance(event, ExtraPointOutcome):
            return TransitionError("expected extra point outcome", ("ExtraPointOutcome",))
        if state.last_touchdown_team is None:
            return TransitionError("internal: missing last_touchdown_team", ())
        scoring = state.last_touchdown_team
        s2 = state
        summary = "Extra point no good"
        if event.good:
            s2 = replace(s2, scores=s2.scores.add(scoring, rules.scoring.extra_point))
            summary = f"Extra point good (+{rules.scoring.extra_point})"
        if rules.after_touchdown.extra_point_attempt_advances_game_clock:
            nc, st = _advance_clock_for_play(s2, rules)
            s2 = replace(st, clock=nc)
        s3 = _setup_kickoff_after_score(s2, scoring, rules)
        return TransitionOk(s3, Phase.KICKOFF_KICK, f"{summary} — kickoff next")

    if phase is Phase.TWO_POINT_ATTEMPT:
        if not isinstance(event, TwoPointOutcome):
            return TransitionError("expected two-point outcome", ("TwoPointOutcome",))
        if state.last_touchdown_team is None:
            return TransitionError("internal: missing last_touchdown_team", ())
        scoring = state.last_touchdown_team
        s2 = state
        summary = "Two-point try no good"
        if event.good:
            s2 = replace(s2, scores=s2.scores.add(scoring, rules.scoring.two_point))
            summary = f"Two-point good (+{rules.scoring.two_point})"
        nc, st = _advance_clock_for_play(s2, rules)
        s2 = replace(st, clock=nc)
        s3 = _setup_kickoff_after_score(s2, scoring, rules)
        return TransitionOk(s3, Phase.KICKOFF_KICK, f"{summary} — kickoff next")

    if phase is Phase.FOURTH_DOWN_DECISION:
        if not isinstance(event, FourthDownChoice):
            return TransitionError("expected fourth-down choice", ("FourthDownChoice",))
        if event.kind == "go":
            return TransitionOk(state, Phase.SCRIMMAGE_OFFENSE, "Going for it on 4th down")
        if event.kind == "punt":
            return TransitionOk(
                replace(state, declared_punt=True),
                Phase.PUNT_ATTEMPT,
                "Punt attempt",
            )
        if event.kind == "field_goal":
            dist = _yards_to_goal_line(state.field)
            if dist > rules.field_goal.max_distance_yards:
                return TransitionError(
                    f"field goal out of range ({dist} yd; max {rules.field_goal.max_distance_yards} yd)",
                    ("FourthDownChoice",),
                )
            if not _sixty_yard_fg_line_ok(state):
                return TransitionError(
                    "60-yard field goals only from your own 40 to 49 yard line",
                    ("FourthDownChoice",),
                )
            snap = state.field
            return TransitionOk(
                replace(
                    state,
                    declared_fg_attempt=True,
                    fg_snap_field=snap,
                    fg_pending_outcome="none",
                    fg_fake_first_down_line=None,
                ),
                Phase.FIELD_GOAL_OFFENSE_DART,
                "Field goal attempt",
            )
        return TransitionError("invalid fourth down kind", ())

    def _fg_kick_range_err(st: GameState) -> TransitionError | None:
        dist = _yards_to_goal_line(st.field)
        if dist > rules.field_goal.max_distance_yards:
            return TransitionError(
                f"FG distance {dist} yd exceeds max {rules.field_goal.max_distance_yards}",
                ("FieldGoalOffenseDart", "ChooseFieldGoalAfterGreen"),
            )
        if not _sixty_yard_fg_line_ok(st):
            return TransitionError(
                "60-yard field goals only from your own 40 to 49 yard line",
                ("FieldGoalOffenseDart", "ChooseFieldGoalAfterGreen"),
            )
        return None

    if phase is Phase.FIELD_GOAL_OFFENSE_DART:
        if not state.declared_fg_attempt:
            return TransitionError("internal: field goal not declared", ())
        snap = state.fg_snap_field if state.fg_snap_field is not None else state.field
        st0 = replace(state, field=snap, fg_snap_field=snap)

        if isinstance(event, FieldGoalOutcome):
            scoring = st0.offense
            dist = _yards_to_goal_line(st0.field)
            if event.kind == "good" and dist > rules.field_goal.max_distance_yards:
                return TransitionError(
                    f"FG distance {dist} yd exceeds max {rules.field_goal.max_distance_yards}",
                    ("FieldGoalOutcome",),
                )
            if event.kind == "good":
                if not _sixty_yard_fg_line_ok(st0):
                    return TransitionError(
                        "60-yard field goals only from your own 40 to 49 yard line",
                        ("FieldGoalOutcome",),
                    )
                s2 = replace(
                    st0,
                    scores=st0.scores.add(scoring, rules.scoring.field_goal),
                    **_fg_clear_sequence_fields(),
                )
                nc, st = _advance_clock_for_play(s2, rules)
                s2 = replace(st, clock=nc)
                s3 = _setup_kickoff_after_score(s2, scoring, rules)
                return TransitionOk(
                    s3,
                    Phase.KICKOFF_KICK,
                    f"Field goal good (+{rules.scoring.field_goal}) — kickoff next",
                )
            s_to = _field_after_missed_field_goal(
                replace(st0, **_fg_clear_sequence_fields()),
                rules,
            )
            nc, st = _advance_clock_for_play(s_to, rules)
            s_to = replace(st, clock=nc)
            return TransitionOk(
                s_to,
                Phase.SCRIMMAGE_OFFENSE,
                f"Field goal {event.kind} — opponent ball at previous LOS +{rules.field_goal.miss_spot_offset_yards} yd",
            )

        if not isinstance(event, FieldGoalOffenseDart):
            return TransitionError(
                "expected field goal offense dart (or legacy outcome)",
                ("FieldGoalOffenseDart", "FieldGoalOutcome"),
            )
        sc = rules.scrimmage
        eff = event.segment
        if eff < sc.segment_min or eff > sc.segment_max:
            return TransitionError(
                f"segment must be {sc.segment_min}..{sc.segment_max}",
                ("FieldGoalOffenseDart",),
            )
        z = event.zone
        if z == "red":
            new_clock, st = _advance_clock_for_play(st0, rules)
            scoring = st0.offense
            s2 = replace(st, clock=new_clock, **_fg_clear_sequence_fields())
            s_td = _state_after_td(s2, scoring, rules)
            return TransitionOk(
                s_td,
                Phase.AFTER_TOUCHDOWN_CHOICE,
                f"Field goal try — red bull: TD {scoring.value}! (+{rules.scoring.touchdown})",
            )
        if z == "green":
            return TransitionOk(
                replace(st0, fg_snap_field=snap),
                Phase.FIELD_GOAL_GREEN_CHOICE,
                "Green bull — choose real field goal or fake",
            )
        re = _fg_kick_range_err(st0)
        if re is not None:
            return re
        if z == "inner_triple":
            return TransitionOk(
                replace(st0, fg_snap_field=snap, fg_pending_outcome="good"),
                Phase.FIELD_GOAL_DEFENSE,
                "FG inside triple ring — would be good; defense may block",
            )
        if z == "outside_triples":
            return TransitionOk(
                replace(st0, fg_snap_field=snap, fg_pending_outcome="miss"),
                Phase.FIELD_GOAL_DEFENSE,
                "FG outside triple ring — would miss; defense may block",
            )
        if z == "triple_ring":
            same = _wedge_board_color_parity(eff) == _team_fg_board_parity(st0.offense)
            pending = "good" if same else "miss"
            return TransitionOk(
                replace(st0, fg_snap_field=snap, fg_pending_outcome=pending),
                Phase.FIELD_GOAL_DEFENSE,
                f"FG on triple ring — would be {'good' if same else 'miss'}; defense may block",
            )
        return TransitionError("internal: unknown FG zone", ())

    if phase is Phase.FIELD_GOAL_GREEN_CHOICE:
        if not isinstance(event, ChooseFieldGoalAfterGreen):
            return TransitionError("expected real kick vs fake choice", ("ChooseFieldGoalAfterGreen",))
        snap = state.fg_snap_field
        if snap is None:
            return TransitionError("internal: missing FG snap", ())
        st0 = replace(state, field=snap)
        if event.real_kick:
            re = _fg_kick_range_err(st0)
            if re is not None:
                return re
            return TransitionOk(
                replace(st0, fg_pending_outcome="good"),
                Phase.FIELD_GOAL_DEFENSE,
                "Real field goal — defense may block",
            )
        return TransitionOk(
            replace(st0, fg_pending_outcome="none", fg_fake_first_down_line=None),
            Phase.FIELD_GOAL_FAKE_OFFENSE,
            "Fake field goal — offense yardage dart (no defense on this throw)",
        )

    if phase is Phase.FIELD_GOAL_FAKE_OFFENSE:
        if not isinstance(event, FieldGoalFakeOffenseDart):
            return TransitionError("expected fake FG offense dart", ("FieldGoalFakeOffenseDart",))
        snap = state.fg_snap_field
        if snap is None:
            return TransitionError("internal: missing FG snap", ())
        yds = _field_goal_fake_yards(event, rules)
        if yds is None:
            return TransitionError(
                "fake FG uses wedge-number scrimmage rules (segment range / settings)",
                ("FieldGoalFakeOffenseDart",),
            )
        new_field = _advance_field(snap, yds)
        dist = _yards_to_goal_line(new_field)
        to_go = min(10, dist)
        downs = DownAndDistance(1, to_go, new_field.scrimmage_line)
        fd_line = _first_down_line_yard(new_field, downs)
        return TransitionOk(
            replace(
                state,
                field=new_field,
                downs=downs,
                fg_pending_outcome="fake_resolved",
                fg_fake_first_down_line=fd_line,
            ),
            Phase.FIELD_GOAL_DEFENSE,
            f"Fake FG +{yds} yds — 1st & {to_go}; defense may affect spot",
        )

    if phase is Phase.FIELD_GOAL_DEFENSE:
        if not isinstance(event, FieldGoalDefenseDart):
            return TransitionError("expected field goal defense dart", ("FieldGoalDefenseDart",))
        sc = rules.scrimmage
        eff = event.segment if event.bull == "none" else _effective_segment_bull(event.segment, event.bull, rules)
        if eff < sc.segment_min or eff > sc.segment_max:
            return TransitionError(
                f"segment must be {sc.segment_min}..{sc.segment_max}",
                ("FieldGoalDefenseDart",),
            )
        pending = state.fg_pending_outcome
        snap = state.fg_snap_field
        if snap is None:
            return TransitionError("internal: missing FG snap", ())
        kicker = state.offense

        def _blocked_at_snap_plus_10() -> TransitionOk:
            new_clock, st = _advance_clock_for_play(state, rules)
            s_inter = replace(st, clock=new_clock, **_fg_clear_sequence_fields())
            stk = replace(s_inter, field=snap, offense=kicker)
            s_to = _field_after_missed_field_goal(stk, rules)
            return TransitionOk(
                s_to,
                Phase.SCRIMMAGE_OFFENSE,
                f"FG blocked (green bull) — opponent at LOS +{rules.field_goal.miss_spot_offset_yards} yd | "
                f"{format_possession_summary(s_to)}",
            )

        if event.bull == "green":
            if pending == "fake_resolved":
                fd = state.fg_fake_first_down_line
                if fd is None:
                    return TransitionError("internal: missing fake FG first-down line", ())
                new_clock, st = _advance_clock_for_play(state, rules)
                short_field = _fake_fg_defense_green_field(state.field, fd)
                dist = _yards_to_goal_line(short_field)
                to_go = min(10, dist)
                downs = DownAndDistance(1, to_go, short_field.scrimmage_line)
                s_fin = replace(
                    st,
                    clock=new_clock,
                    **_fg_clear_sequence_fields(),
                    field=short_field,
                    downs=downs,
                    offense=kicker,
                )
                return TransitionOk(
                    s_fin,
                    Phase.SCRIMMAGE_OFFENSE,
                    "Fake FG — defense green bull: 1 yd short of sticks or own 11, whichever is worse toward goal",
                )
            return _blocked_at_snap_plus_10()

        if event.bull == "red":
            new_clock, st = _advance_clock_for_play(state, rules)
            s_inter = replace(st, clock=new_clock, **_fg_clear_sequence_fields())
            if pending == "fake_resolved":
                dist = _yards_to_goal_line(snap)
                downs = DownAndDistance(1, min(10, dist), snap.scrimmage_line)
                s_fin = replace(s_inter, field=snap, downs=downs, offense=kicker)
                return TransitionOk(
                    s_fin,
                    Phase.SCRIMMAGE_OFFENSE,
                    "Fake FG — defense red bull: ball at the line of scrimmage (no gain from snap)",
                )
            scoring = _other(kicker)
            s_td = _state_after_td(s_inter, scoring, rules)
            return TransitionOk(
                s_td,
                Phase.AFTER_TOUCHDOWN_CHOICE,
                f"FG blocked (red bull) — defensive TD {scoring.value}! (+{rules.scoring.touchdown})",
            )

        new_clock, st = _advance_clock_for_play(state, rules)
        s_base = replace(st, clock=new_clock, **_fg_clear_sequence_fields())

        if pending == "good":
            s2 = replace(s_base, scores=s_base.scores.add(kicker, rules.scoring.field_goal))
            s3 = _setup_kickoff_after_score(s2, kicker, rules)
            return TransitionOk(
                s3,
                Phase.KICKOFF_KICK,
                f"Field goal good (+{rules.scoring.field_goal}) — kickoff next",
            )
        if pending == "miss":
            stk = replace(s_base, field=snap, offense=kicker)
            s_to = _field_after_missed_field_goal(stk, rules)
            return TransitionOk(
                s_to,
                Phase.SCRIMMAGE_OFFENSE,
                f"Field goal no good — opponent at LOS +{rules.field_goal.miss_spot_offset_yards} yd",
            )
        if pending == "fake_resolved":
            s_fin = replace(s_base, offense=kicker)
            return TransitionOk(
                s_fin,
                Phase.SCRIMMAGE_OFFENSE,
                "Fake FG — defense dart had no effect on spot",
            )
        return TransitionError("internal: bad FG pending state", ())

    if phase is Phase.PUNT_ATTEMPT:
        if not isinstance(event, PuntKick):
            return TransitionError("expected punt segment", ("PuntKick",))
        pr = rules.punt
        eff = event.segment
        if eff < pr.segment_min or eff > pr.segment_max:
            return TransitionError(
                f"punt segment must be {pr.segment_min}..{pr.segment_max}",
                ("PuntKick",),
            )
        if event.bull == "green":
            new_clock, st = _advance_clock_for_play(state, rules)
            s_inter = replace(
                st,
                clock=new_clock,
                declared_punt=False,
                scrimmage_pending_offense_yards=None,
                scrimmage_pending_offense_kind="none",
                scrimmage_pending_offense_eff_segment=None,
            )
            return _no_gain_advance_down(
                s_inter,
                state,
                state.field,
                "Fake punt — no gain at LOS",
            )
        if event.bull == "red":
            new_clock, st = _advance_clock_for_play(state, rules)
            s_inter = replace(
                st,
                clock=new_clock,
                declared_punt=False,
                scrimmage_pending_offense_yards=None,
                scrimmage_pending_offense_kind="none",
                scrimmage_pending_offense_eff_segment=None,
            )
            s_to = _defensive_takeover_at_spot(s_inter, state.field)
            return TransitionOk(
                s_to,
                Phase.SCRIMMAGE_OFFENSE,
                f"Blocked punt — turnover at LOS | {format_possession_summary(s_to)}",
            )
        band = _match_spot_band(pr.bands, eff)
        if band is None:
            return TransitionError(f"no punt band for segment {eff}", ("PuntKick",))
        receiver = _other(state.offense)
        field = _field_from_spot_band(receiver, band, eff)
        dist = _yards_to_goal_line(field)
        downs = DownAndDistance(1, min(10, dist), field.scrimmage_line)
        new_clock, st = _advance_clock_for_play(state, rules)
        s = replace(
            st,
            offense=receiver,
            field=field,
            downs=downs,
            clock=new_clock,
            declared_punt=False,
            scrimmage_pending_offense_yards=None,
        )
        return TransitionOk(
            s,
            Phase.SCRIMMAGE_OFFENSE,
            f"Punt — {format_possession_summary(s)}",
        )

    if phase is Phase.SCRIMMAGE_OFFENSE:
        if isinstance(event, FourthDownChoice):
            if event.kind == "go":
                return TransitionError(
                    "choose offense play and throw a scrimmage dart, or punt / field goal",
                    ("ScrimmageOffense", "FourthDownChoice"),
                )
            if event.kind == "punt":
                if state.downs.down < 2:
                    return TransitionError("cannot punt on first down", ("FourthDownChoice",))
                return TransitionOk(
                    replace(state, declared_punt=True),
                    Phase.PUNT_ATTEMPT,
                    "Punt attempt",
                )
            if event.kind == "field_goal":
                if state.downs.down not in (3, 4) and not state.last_play_of_period:
                    return TransitionError(
                        "field goals only on 3rd or 4th down (unless last play of half or game)",
                        ("FourthDownChoice",),
                    )
                dist = _yards_to_goal_line(state.field)
                if dist > rules.field_goal.max_distance_yards:
                    return TransitionError(
                        f"field goal out of range ({dist} yd; max {rules.field_goal.max_distance_yards} yd)",
                        ("FourthDownChoice",),
                    )
                if not _sixty_yard_fg_line_ok(state):
                    return TransitionError(
                        "60-yard field goals only from your own 40 to 49 yard line",
                        ("FourthDownChoice",),
                    )
                snap = state.field
                return TransitionOk(
                    replace(
                        state,
                        declared_fg_attempt=True,
                        fg_snap_field=snap,
                        fg_pending_outcome="none",
                        fg_fake_first_down_line=None,
                    ),
                    Phase.FIELD_GOAL_OFFENSE_DART,
                    "Field goal attempt",
                )
        if not isinstance(event, ScrimmageOffense):
            return TransitionError(
                "expected scrimmage offense dart, punt, or field goal",
                ("ScrimmageOffense", "FourthDownChoice"),
            )
        sc = rules.scrimmage
        eff = event.segment if event.bull == "none" else _effective_segment_bull(event.segment, event.bull, rules)
        if eff < sc.segment_min or eff > sc.segment_max:
            return TransitionError(
                f"segment must be {sc.segment_min}..{sc.segment_max}",
                ("ScrimmageOffense",),
            )
        if not sc.use_wedge_number_yards:
            if event.bull == "red":
                new_clock, st = _advance_clock_for_play(state, rules)
                s_base = replace(st, clock=new_clock)
                s_to = _defensive_takeover_at_spot(s_base, s_base.field)
                return TransitionOk(
                    s_to,
                    Phase.SCRIMMAGE_OFFENSE,
                    f"Offense red bull — turnover | {format_possession_summary(s_to)}",
                )
            base = _match_scrimmage_yards(sc.offense_yards, eff)
            if base is None:
                return TransitionError(
                    f"no offense yard band for segment {eff}",
                    ("ScrimmageOffense",),
                )
            mult = 1
            if event.bull == "none":
                if event.triple_ring:
                    mult *= sc.triple_multiplier
                if event.double_ring:
                    mult *= sc.double_multiplier
            off_yards = base * mult
            s = replace(state, scrimmage_pending_offense_yards=off_yards)
        else:
            if event.bull == "red":
                kind_s = "red"
                off_yards = 0
            elif event.bull == "green":
                kind_s = "green"
                off_yards = eff
            else:
                kind_s = "wedge"
                mult = 1
                if event.triple_ring:
                    mult *= sc.triple_multiplier
                if event.double_ring:
                    mult *= sc.double_multiplier
                off_yards = eff * mult
            s = replace(
                state,
                scrimmage_pending_offense_yards=off_yards,
                scrimmage_pending_offense_kind=kind_s,
                scrimmage_pending_offense_eff_segment=eff,
            )
        ring = []
        if event.bull != "none":
            ring.append(f"bull {event.bull}")
        else:
            if event.double_ring:
                ring.append("D")
            if event.triple_ring:
                t = "T"
                if event.triple_inner is True:
                    t += " in"
                elif event.triple_inner is False:
                    t += " out"
                ring.append(t)
        ring_s = f" [{'/'.join(ring)}]" if ring else ""
        return TransitionOk(
            s,
            Phase.SCRIMMAGE_DEFENSE,
            f"Offense dart seg {eff}{ring_s} → {off_yards} yds (await defense)",
        )

    if phase is Phase.SCRIMMAGE_DEFENSE:
        if state.scrimmage_pending_offense_yards is None:
            return TransitionError("internal: missing pending offense yards", ())
        if not isinstance(event, ScrimmageDefense):
            return TransitionError("expected scrimmage defense dart", ("ScrimmageDefense",))
        sc = rules.scrimmage
        off_yards = state.scrimmage_pending_offense_yards
        kind = state.scrimmage_pending_offense_kind
        eff = event.segment if event.bull == "none" else _effective_segment_bull(event.segment, event.bull, rules)
        if eff < sc.segment_min or eff > sc.segment_max:
            return TransitionError(
                f"segment must be {sc.segment_min}..{sc.segment_max}",
                ("ScrimmageDefense",),
            )

        if not sc.use_wedge_number_yards or kind == "none":
            if sc.use_wedge_number_yards and event.bull == "red":
                hypo = _advance_field(state.field, off_yards)
                new_clock, st = _advance_clock_for_play(state, rules)
                s_inter = replace(
                    st,
                    clock=new_clock,
                    scrimmage_pending_offense_yards=None,
                    scrimmage_pending_offense_kind="none",
                    scrimmage_pending_offense_eff_segment=None,
                )
                if _is_touchdown(hypo):
                    scoring = state.offense
                    s_td = _state_after_td(s_inter, scoring, rules)
                    return TransitionOk(
                        s_td,
                        Phase.AFTER_TOUCHDOWN_CHOICE,
                        f"Play: off {off_yards} yds | def red bull moot — TD {scoring.value}! (+{rules.scoring.touchdown})",
                    )
                s_to = _defensive_takeover_at_spot(s_inter, hypo)
                return TransitionOk(
                    s_to,
                    Phase.SCRIMMAGE_OFFENSE,
                    f"Play: off {off_yards} yds | defense red bull — turnover | {format_possession_summary(s_to)}",
                )
            if sc.use_wedge_number_yards and event.bull == "green":
                def_yards = 0
            elif sc.use_wedge_number_yards:
                def_yards = eff
            else:
                def_yards = _match_scrimmage_yards(sc.defense_yards, eff)
                if def_yards is None:
                    return TransitionError(
                        f"no defense yard band for segment {eff}",
                        ("ScrimmageDefense",),
                    )
            raw_net = off_yards - def_yards
            net = max(raw_net, -sc.max_loss_yards)
            new_field = _advance_field(state.field, net)
            new_clock, st = _advance_clock_for_play(state, rules)
            s_inter = replace(
                st,
                field=new_field,
                clock=new_clock,
                scrimmage_pending_offense_yards=None,
                scrimmage_pending_offense_kind="none",
                scrimmage_pending_offense_eff_segment=None,
            )
            dn = _defense_ring_note(event)
            return _finish_scrimmage_net_play(state, rules, s_inter, new_field, off_yards, def_yards, net, dn)

        if kind == "wedge":
            if event.bull == "green":
                return TransitionOk(
                    replace(state),
                    Phase.SCRIMMAGE_STRIP_DART,
                    "Defense green bull — throw a numbered wedge dart (strip). Same board wedge color as offense wedge: "
                    "full offensive yards then turnover (or offensive TD); else turnover at LOS.",
                )
            if event.bull == "red":
                return _defensive_touchdown_after_offense_yards(
                    state,
                    rules,
                    off_yards,
                    f"Play: off {off_yards} yds | def red bull",
                )
            def_yards = eff
            raw_net = off_yards - def_yards
            net = max(raw_net, -sc.max_loss_yards)
            new_field = _advance_field(state.field, net)
            new_clock, st = _advance_clock_for_play(state, rules)
            s_inter = replace(
                st,
                field=new_field,
                clock=new_clock,
                scrimmage_pending_offense_yards=None,
                scrimmage_pending_offense_kind="none",
                scrimmage_pending_offense_eff_segment=None,
            )
            dn = _defense_ring_note(event)
            return _finish_scrimmage_net_play(state, rules, s_inter, new_field, off_yards, def_yards, net, dn)

        if kind == "green":
            if event.bull == "red":
                new_clock, st = _advance_clock_for_play(state, rules)
                s_inter = replace(
                    st,
                    clock=new_clock,
                    scrimmage_pending_offense_yards=None,
                    scrimmage_pending_offense_kind="none",
                    scrimmage_pending_offense_eff_segment=None,
                )
                s_to = _defensive_takeover_at_spot(s_inter, state.field)
                return TransitionOk(
                    s_to,
                    Phase.SCRIMMAGE_OFFENSE,
                    f"Play: off {off_yards} yds (off green) | def red bull — turnover at LOS | "
                    f"{format_possession_summary(s_to)}",
                )
            new_clock, st = _advance_clock_for_play(state, rules)
            s_inter = replace(
                st,
                clock=new_clock,
                scrimmage_pending_offense_yards=None,
                scrimmage_pending_offense_kind="none",
                scrimmage_pending_offense_eff_segment=None,
            )
            if event.bull == "green":
                summ = f"Play: off {off_yards} yds (off green) | def green — no gain at LOS"
            else:
                summ = f"Play: off {off_yards} yds (off green) | def wedge — no effect, no gain"
            return _no_gain_advance_down(s_inter, state, state.field, summ)

        if event.bull == "red":
            new_clock, st = _advance_clock_for_play(state, rules)
            s_inter = replace(
                st,
                clock=new_clock,
                scrimmage_pending_offense_yards=None,
                scrimmage_pending_offense_kind="none",
                scrimmage_pending_offense_eff_segment=None,
            )
            return _no_gain_advance_down(
                s_inter,
                state,
                state.field,
                "Play: offense red bull | def red — no gain at LOS",
            )
        new_clock, st = _advance_clock_for_play(state, rules)
        s_inter = replace(
            st,
            clock=new_clock,
            scrimmage_pending_offense_yards=None,
            scrimmage_pending_offense_kind="none",
            scrimmage_pending_offense_eff_segment=None,
        )
        return _no_gain_advance_down(
            s_inter,
            state,
            state.field,
            "Play: offense red bull | def dart — no effect, no gain",
        )

    if phase is Phase.SCRIMMAGE_STRIP_DART:
        if state.scrimmage_pending_offense_kind != "wedge":
            return TransitionError("strip dart only after defense green vs offense numbered wedge", ())
        if state.scrimmage_pending_offense_yards is None or state.scrimmage_pending_offense_eff_segment is None:
            return TransitionError("internal: missing strip context", ())
        if not isinstance(event, ScrimmageStripDart):
            return TransitionError("expected strip wedge dart", ("ScrimmageStripDart",))
        sc = rules.scrimmage
        seg = event.segment
        if seg < sc.segment_min or seg > sc.segment_max:
            return TransitionError(
                f"segment must be {sc.segment_min}..{sc.segment_max}",
                ("ScrimmageStripDart",),
            )
        off_eff = state.scrimmage_pending_offense_eff_segment
        off_yards = state.scrimmage_pending_offense_yards
        new_clock, st = _advance_clock_for_play(state, rules)
        pending_clear = {
            "scrimmage_pending_offense_yards": None,
            "scrimmage_pending_offense_kind": "none",
            "scrimmage_pending_offense_eff_segment": None,
        }
        if _wedge_board_colors_match(off_eff, seg):
            hypo = _advance_field(state.field, off_yards)
            s_inter = replace(st, clock=new_clock, field=hypo, **pending_clear)
            if _is_touchdown(hypo):
                scoring = state.offense
                s_td = _state_after_td(s_inter, scoring, rules)
                return TransitionOk(
                    s_td,
                    Phase.AFTER_TOUCHDOWN_CHOICE,
                    f"Strip match — offense gains {off_yards} yds | TD {scoring.value}! (+{rules.scoring.touchdown})",
                )
            s_to = _defensive_takeover_at_spot(s_inter, hypo)
            return TransitionOk(
                s_to,
                Phase.SCRIMMAGE_OFFENSE,
                f"Strip match — offense gains {off_yards} yds then turnover | {format_possession_summary(s_to)}",
            )
        s_inter = replace(st, clock=new_clock, **pending_clear)
        s_to = _defensive_takeover_at_spot(s_inter, state.field)
        return TransitionOk(
            s_to,
            Phase.SCRIMMAGE_OFFENSE,
            f"Strip no color match — turnover at LOS | {format_possession_summary(s_to)}",
        )

    if phase is Phase.SAFETY_SEQUENCE:
        if not isinstance(event, ConfirmSafetyKickoff):
            return TransitionError(
                "expected confirm safety free kick",
                ("ConfirmSafetyKickoff",),
            )
        if state.safety_pending_kicker is None:
            return TransitionError("internal: no pending safety kicker", ())
        k = state.safety_pending_kicker
        recv = _other(k)
        s2 = replace(state, safety_pending_kicker=None)
        s3 = _setup_safety_free_kick(s2, k, recv, rules)
        return TransitionOk(
            s3,
            Phase.KICKOFF_KICK,
            "Safety free kick — kicker chooses regular or onside, then throw",
        )

    if phase is Phase.OVERTIME_START:
        if not isinstance(event, CoinTossWinner):
            return TransitionError(
                "expected overtime coin toss winner",
                ("CoinTossWinner",),
            )
        s = replace(state, coin_toss_winner=event.winner)
        return TransitionOk(
            s,
            Phase.CHOOSE_KICK_OR_RECEIVE,
            f"Overtime: {event.winner.value} won the toss — kick or receive",
        )

    if phase is Phase.GAME_OVER:
        return TransitionError("game over", ())

    return TransitionError(f"unhandled phase {phase!r}", ())


def transition(
    state: GameState,
    phase: Phase,
    event: Event,
    rules: RuleSet,
) -> TransitionOk | TransitionError:
    prev_q = state.clock.quarter
    out = _transition_core(state, phase, event, rules)
    if isinstance(out, TransitionOk):
        return _post_process_transition_ok(prev_q, out, rules)
    return out
