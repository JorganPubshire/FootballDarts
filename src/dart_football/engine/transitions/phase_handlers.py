"""Per-phase transition handlers (dispatched from transition_core)."""

from __future__ import annotations

from dataclasses import replace

from dart_football.display.formatting import format_possession_summary, opponent
from dart_football.engine.events import (
    ChooseExtraPointOrTwo,
    ChooseFieldGoalAfterGreen,
    ChooseKickoffKind,
    ChooseKickoffTouchbackOrRun,
    ChooseKickOrReceive,
    CoinTossWinner,
    ConfirmSafetyKickoff,
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
from dart_football.engine.state import DownAndDistance, GameState
from dart_football.engine.transitions.clock_and_timeouts import (
    advance_clock_for_scrimmage_play,
)
from dart_football.engine.transitions.field_geometry import (
    advance_field_position,
    defensive_takeover_at_spot,
    field_from_spot_band,
    field_spot_from_own_yard,
    is_touchdown_field,
    kickoff_tee_down_and_distance,
    kickoff_tee_field_position,
    match_scrimmage_yard_band,
    match_spot_band_for_segment,
    receiver_goal_line_field_position,
    yards_to_goal_line,
)
from dart_football.engine.transitions.field_goal_and_punt import (
    fake_field_goal_defense_green_field,
    fg_kick_range_error_or_none,
    field_after_missed_field_goal,
    field_goal_fake_yards_from_dart,
    field_goal_sequence_clear_fields,
    first_down_line_yard,
    sixty_yard_field_goal_line_ok,
    team_field_goal_board_parity,
)
from dart_football.engine.transitions.kickoff_resolution import (
    apply_kickoff_dart,
    finish_kickoff_return_touchdown,
    finish_kickoff_to_scrimmage,
    return_dart_net_yards,
    run_out_net_yards,
)
from dart_football.engine.transitions.scoring_setup import (
    setup_kickoff_after_score,
    setup_safety_free_kick,
    state_after_touchdown,
)
from dart_football.engine.transitions.scrimmage_resolution import (
    defense_ring_note,
    defensive_touchdown_after_offense_yards,
    effective_segment_with_bull,
    finish_scrimmage_net_play,
    no_gain_advance_down,
    wedge_board_color_parity,
    wedge_board_colors_match,
)
from dart_football.engine.transitions.types import TransitionError, TransitionOk
from dart_football.rules.schema import RuleSet


def handle_pre_game_coin_toss(
    state: GameState,
    event: Event,
    rules: RuleSet,
) -> TransitionOk | TransitionError:
    if not isinstance(event, CoinTossWinner):
        return TransitionError("expected coin toss winner", ("CoinTossWinner",))
    s = replace(state, coin_toss_winner=event.winner)
    return TransitionOk(
        s,
        Phase.CHOOSE_KICK_OR_RECEIVE,
        f"Coin toss winner: {event.winner.value}",
    )


def handle_choose_kick_or_receive(
    state: GameState,
    event: Event,
    rules: RuleSet,
) -> TransitionOk | TransitionError:
    if state.coin_toss_winner is None:
        return TransitionError("internal: missing coin_toss_winner", ())
    if not isinstance(event, ChooseKickOrReceive):
        return TransitionError("expected kick/receive choice", ("ChooseKickOrReceive",))
    w = state.coin_toss_winner
    loser = opponent(w)
    if event.kick:
        kicker, receiver = w, loser
    else:
        kicker, receiver = loser, w
    fp = kickoff_tee_field_position(kicker)
    downs = kickoff_tee_down_and_distance(kicker)
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


def handle_kickoff_kick(
    state: GameState,
    event: Event,
    rules: RuleSet,
) -> TransitionOk | TransitionError:
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
    out = apply_kickoff_dart(state, event, rules, onside_attempt=False)
    if isinstance(out, TransitionError):
        return out
    return out


def handle_onside_kick(
    state: GameState,
    event: Event,
    rules: RuleSet,
) -> TransitionOk | TransitionError:
    if state.kickoff_kicker is None or state.kickoff_receiver is None:
        return TransitionError("internal: kickoff teams not set", ())
    if not isinstance(event, KickoffKick):
        return TransitionError("expected onside kick dart", ("KickoffKick",))
    out = apply_kickoff_dart(state, event, rules, onside_attempt=True)
    if isinstance(out, TransitionError):
        return out
    return out


def handle_kickoff_run_or_spot(
    state: GameState,
    event: Event,
    rules: RuleSet,
) -> TransitionOk | TransitionError:
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
        field = field_spot_from_own_yard(recv, line)
        return finish_kickoff_to_scrimmage(
            state, rules, recv, field, f"Touchback — ball at own {line}"
        )
    goal = receiver_goal_line_field_position(recv)
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


def handle_kickoff_run_out_dart(
    state: GameState,
    event: Event,
    rules: RuleSet,
) -> TransitionOk | TransitionError:
    if state.kickoff_awaiting != "run_out_dart" or state.kickoff_receiver is None:
        return TransitionError("internal: not awaiting run-out dart", ())
    if not isinstance(event, KickoffRunOutKick):
        return TransitionError("expected run-out dart", ("KickoffRunOutKick",))
    recv = state.kickoff_receiver
    if state.offense != recv:
        return TransitionError("internal: offense should be receiving team", ())
    try:
        net = run_out_net_yards(event, rules)
    except ValueError:
        return TransitionError(
            f"run-out wedge must be {rules.kickoff.segment_min}..{rules.kickoff.segment_max}",
            ("KickoffRunOutKick",),
        )
    if net is None:
        return finish_kickoff_return_touchdown(
            state,
            recv,
            rules,
            "Run-out red bull — kick return touchdown",
        )
    nf = advance_field_position(state.field, net)
    if is_touchdown_field(nf):
        s_mid = replace(state, field=nf)
        return finish_kickoff_return_touchdown(
            s_mid,
            recv,
            rules,
            f"Run-out +{net} yd — end zone",
        )
    return finish_kickoff_to_scrimmage(state, rules, recv, nf, f"Run-out +{net} yd")


def handle_kickoff_return_dart(
    state: GameState,
    event: Event,
    rules: RuleSet,
) -> TransitionOk | TransitionError:
    if state.kickoff_awaiting != "return_dart" or state.kickoff_receiver is None:
        return TransitionError("internal: not awaiting return dart", ())
    if not isinstance(event, KickoffReturnKick):
        return TransitionError("expected return dart", ("KickoffReturnKick",))
    recv = state.kickoff_receiver
    if state.offense != recv:
        return TransitionError("internal: offense should be receiving team", ())
    try:
        net = return_dart_net_yards(event, rules)
    except ValueError:
        return TransitionError(
            f"return wedge must be {rules.scrimmage.segment_min}..{rules.scrimmage.segment_max}",
            ("KickoffReturnKick",),
        )
    if net is None:
        return finish_kickoff_return_touchdown(
            state,
            recv,
            rules,
            "Return red bull — kick return touchdown",
        )
    nf = advance_field_position(state.field, net)
    if is_touchdown_field(nf):
        s_mid = replace(state, field=nf)
        return finish_kickoff_return_touchdown(
            s_mid,
            recv,
            rules,
            f"Return +{net} yd — end zone",
        )
    return finish_kickoff_to_scrimmage(state, rules, recv, nf, f"Return +{net} yd")


def handle_after_touchdown_choice(
    state: GameState,
    event: Event,
    rules: RuleSet,
) -> TransitionOk | TransitionError:
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


def handle_extra_point_attempt(
    state: GameState,
    event: Event,
    rules: RuleSet,
) -> TransitionOk | TransitionError:
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
        nc, st = advance_clock_for_scrimmage_play(s2, rules)
        s2 = replace(st, clock=nc)
    s3 = setup_kickoff_after_score(s2, scoring, rules)
    return TransitionOk(s3, Phase.KICKOFF_KICK, f"{summary} — kickoff next")


def handle_two_point_attempt(
    state: GameState,
    event: Event,
    rules: RuleSet,
) -> TransitionOk | TransitionError:
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
    nc, st = advance_clock_for_scrimmage_play(s2, rules)
    s2 = replace(st, clock=nc)
    s3 = setup_kickoff_after_score(s2, scoring, rules)
    return TransitionOk(s3, Phase.KICKOFF_KICK, f"{summary} — kickoff next")


def handle_fourth_down_decision(
    state: GameState,
    event: Event,
    rules: RuleSet,
) -> TransitionOk | TransitionError:
    if isinstance(event, ScrimmageOffense):
        return handle_scrimmage_offense(state, event, rules)
    if not isinstance(event, FourthDownChoice):
        return TransitionError(
            "expected fourth-down choice or scrimmage offense dart",
            ("FourthDownChoice", "ScrimmageOffense"),
        )
    if event.kind == "go":
        return TransitionOk(state, Phase.SCRIMMAGE_OFFENSE, "Going for it on 4th down")
    if event.kind == "punt":
        return TransitionOk(
            replace(state, declared_punt=True),
            Phase.PUNT_ATTEMPT,
            "Punt attempt",
        )
    if event.kind == "field_goal":
        dist = yards_to_goal_line(state.field)
        if dist > rules.field_goal.max_distance_yards:
            return TransitionError(
                f"field goal out of range ({dist} yd; max {rules.field_goal.max_distance_yards} yd)",
                ("FourthDownChoice",),
            )
        if not sixty_yard_field_goal_line_ok(state):
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


def handle_field_goal_offense_dart(
    state: GameState,
    event: Event,
    rules: RuleSet,
) -> TransitionOk | TransitionError:
    if not state.declared_fg_attempt:
        return TransitionError("internal: field goal not declared", ())
    snap = state.fg_snap_field if state.fg_snap_field is not None else state.field
    st0 = replace(state, field=snap, fg_snap_field=snap)

    if isinstance(event, FieldGoalOutcome):
        scoring = st0.offense
        dist = yards_to_goal_line(st0.field)
        if event.kind == "good" and dist > rules.field_goal.max_distance_yards:
            return TransitionError(
                f"FG distance {dist} yd exceeds max {rules.field_goal.max_distance_yards}",
                ("FieldGoalOutcome",),
            )
        if event.kind == "good":
            if not sixty_yard_field_goal_line_ok(st0):
                return TransitionError(
                    "60-yard field goals only from your own 40 to 49 yard line",
                    ("FieldGoalOutcome",),
                )
            s2 = replace(
                st0,
                scores=st0.scores.add(scoring, rules.scoring.field_goal),
                **field_goal_sequence_clear_fields(),
            )
            nc, st = advance_clock_for_scrimmage_play(s2, rules)
            s2 = replace(st, clock=nc)
            s3 = setup_kickoff_after_score(s2, scoring, rules)
            return TransitionOk(
                s3,
                Phase.KICKOFF_KICK,
                f"Field goal good (+{rules.scoring.field_goal}) — kickoff next",
            )
        s_to = field_after_missed_field_goal(
            replace(st0, **field_goal_sequence_clear_fields()),
            rules,
        )
        nc, st = advance_clock_for_scrimmage_play(s_to, rules)
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
        new_clock, st = advance_clock_for_scrimmage_play(st0, rules)
        scoring = st0.offense
        s2 = replace(st, clock=new_clock, **field_goal_sequence_clear_fields())
        s_td = state_after_touchdown(s2, scoring, rules)
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
    re = fg_kick_range_error_or_none(st0, rules)
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
        same = wedge_board_color_parity(eff) == team_field_goal_board_parity(st0.offense)
        pending = "good" if same else "miss"
        return TransitionOk(
            replace(st0, fg_snap_field=snap, fg_pending_outcome=pending),
            Phase.FIELD_GOAL_DEFENSE,
            f"FG on triple ring — would be {'good' if same else 'miss'}; defense may block",
        )
    return TransitionError("internal: unknown FG zone", ())


def handle_field_goal_green_choice(
    state: GameState,
    event: Event,
    rules: RuleSet,
) -> TransitionOk | TransitionError:
    if not isinstance(event, ChooseFieldGoalAfterGreen):
        return TransitionError("expected real kick vs fake choice", ("ChooseFieldGoalAfterGreen",))
    snap = state.fg_snap_field
    if snap is None:
        return TransitionError("internal: missing FG snap", ())
    st0 = replace(state, field=snap)
    if event.real_kick:
        re = fg_kick_range_error_or_none(st0, rules)
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


def handle_field_goal_fake_offense(
    state: GameState,
    event: Event,
    rules: RuleSet,
) -> TransitionOk | TransitionError:
    if not isinstance(event, FieldGoalFakeOffenseDart):
        return TransitionError("expected fake FG offense dart", ("FieldGoalFakeOffenseDart",))
    snap = state.fg_snap_field
    if snap is None:
        return TransitionError("internal: missing FG snap", ())
    yds = field_goal_fake_yards_from_dart(event, rules)
    if yds is None:
        return TransitionError(
            "fake FG uses wedge-number scrimmage rules (segment range / settings)",
            ("FieldGoalFakeOffenseDart",),
        )
    new_field = advance_field_position(snap, yds)
    dist = yards_to_goal_line(new_field)
    to_go = min(10, dist)
    downs = DownAndDistance(1, to_go, new_field.scrimmage_line)
    fd_line = first_down_line_yard(new_field, downs)
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


def handle_field_goal_defense(
    state: GameState,
    event: Event,
    rules: RuleSet,
) -> TransitionOk | TransitionError:
    if not isinstance(event, FieldGoalDefenseDart):
        return TransitionError("expected field goal defense dart", ("FieldGoalDefenseDart",))
    sc = rules.scrimmage
    eff = (
        event.segment
        if event.bull == "none"
        else effective_segment_with_bull(event.segment, event.bull, rules)
    )
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

    def blocked_field_goal_at_snap_plus_10() -> TransitionOk:
        new_clock, st = advance_clock_for_scrimmage_play(state, rules)
        s_inter = replace(st, clock=new_clock, **field_goal_sequence_clear_fields())
        stk = replace(s_inter, field=snap, offense=kicker)
        s_to = field_after_missed_field_goal(stk, rules)
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
            new_clock, st = advance_clock_for_scrimmage_play(state, rules)
            short_field = fake_field_goal_defense_green_field(state.field, fd)
            dist = yards_to_goal_line(short_field)
            to_go = min(10, dist)
            downs = DownAndDistance(1, to_go, short_field.scrimmage_line)
            s_fin = replace(
                st,
                clock=new_clock,
                **field_goal_sequence_clear_fields(),
                field=short_field,
                downs=downs,
                offense=kicker,
            )
            return TransitionOk(
                s_fin,
                Phase.SCRIMMAGE_OFFENSE,
                "Fake FG — defense green bull: 1 yd short of sticks or own 11, whichever is worse toward goal",
            )
        return blocked_field_goal_at_snap_plus_10()

    if event.bull == "red":
        new_clock, st = advance_clock_for_scrimmage_play(state, rules)
        s_inter = replace(st, clock=new_clock, **field_goal_sequence_clear_fields())
        if pending == "fake_resolved":
            dist = yards_to_goal_line(snap)
            downs = DownAndDistance(1, min(10, dist), snap.scrimmage_line)
            s_fin = replace(s_inter, field=snap, downs=downs, offense=kicker)
            return TransitionOk(
                s_fin,
                Phase.SCRIMMAGE_OFFENSE,
                "Fake FG — defense red bull: ball at the line of scrimmage (no gain from snap)",
            )
        scoring = opponent(kicker)
        s_td = state_after_touchdown(s_inter, scoring, rules)
        return TransitionOk(
            s_td,
            Phase.AFTER_TOUCHDOWN_CHOICE,
            f"FG blocked (red bull) — defensive TD {scoring.value}! (+{rules.scoring.touchdown})",
        )

    new_clock, st = advance_clock_for_scrimmage_play(state, rules)
    s_base = replace(st, clock=new_clock, **field_goal_sequence_clear_fields())

    if pending == "good":
        s2 = replace(s_base, scores=s_base.scores.add(kicker, rules.scoring.field_goal))
        s3 = setup_kickoff_after_score(s2, kicker, rules)
        return TransitionOk(
            s3,
            Phase.KICKOFF_KICK,
            f"Field goal good (+{rules.scoring.field_goal}) — kickoff next",
        )
    if pending == "miss":
        stk = replace(s_base, field=snap, offense=kicker)
        s_to = field_after_missed_field_goal(stk, rules)
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


def handle_punt_attempt(
    state: GameState,
    event: Event,
    rules: RuleSet,
) -> TransitionOk | TransitionError:
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
        new_clock, st = advance_clock_for_scrimmage_play(state, rules)
        s_inter = replace(
            st,
            clock=new_clock,
            declared_punt=False,
            scrimmage_pending_offense_yards=None,
            scrimmage_pending_offense_kind="none",
            scrimmage_pending_offense_eff_segment=None,
        )
        return no_gain_advance_down(
            s_inter,
            state,
            state.field,
            "Fake punt — no gain at LOS",
        )
    if event.bull == "red":
        new_clock, st = advance_clock_for_scrimmage_play(state, rules)
        s_inter = replace(
            st,
            clock=new_clock,
            declared_punt=False,
            scrimmage_pending_offense_yards=None,
            scrimmage_pending_offense_kind="none",
            scrimmage_pending_offense_eff_segment=None,
        )
        s_to = defensive_takeover_at_spot(s_inter, state.field)
        return TransitionOk(
            s_to,
            Phase.SCRIMMAGE_OFFENSE,
            f"Blocked punt — turnover at LOS | {format_possession_summary(s_to)}",
        )
    band = match_spot_band_for_segment(pr.bands, eff)
    if band is None:
        return TransitionError(f"no punt band for segment {eff}", ("PuntKick",))
    receiver = opponent(state.offense)
    field = field_from_spot_band(receiver, band, eff)
    dist = yards_to_goal_line(field)
    downs = DownAndDistance(1, min(10, dist), field.scrimmage_line)
    new_clock, st = advance_clock_for_scrimmage_play(state, rules)
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


def handle_scrimmage_offense(
    state: GameState,
    event: Event,
    rules: RuleSet,
) -> TransitionOk | TransitionError:
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
            dist = yards_to_goal_line(state.field)
            if dist > rules.field_goal.max_distance_yards:
                return TransitionError(
                    f"field goal out of range ({dist} yd; max {rules.field_goal.max_distance_yards} yd)",
                    ("FourthDownChoice",),
                )
            if not sixty_yard_field_goal_line_ok(state):
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
    eff = (
        event.segment
        if event.bull == "none"
        else effective_segment_with_bull(event.segment, event.bull, rules)
    )
    if eff < sc.segment_min or eff > sc.segment_max:
        return TransitionError(
            f"segment must be {sc.segment_min}..{sc.segment_max}",
            ("ScrimmageOffense",),
        )
    if not sc.use_wedge_number_yards:
        if event.bull == "red":
            new_clock, st = advance_clock_for_scrimmage_play(state, rules)
            s_base = replace(st, clock=new_clock)
            s_to = defensive_takeover_at_spot(s_base, s_base.field)
            return TransitionOk(
                s_to,
                Phase.SCRIMMAGE_OFFENSE,
                f"Offense red bull — turnover | {format_possession_summary(s_to)}",
            )
        base = match_scrimmage_yard_band(sc.offense_yards, eff)
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


def handle_scrimmage_defense(
    state: GameState,
    event: Event,
    rules: RuleSet,
) -> TransitionOk | TransitionError:
    if state.scrimmage_pending_offense_yards is None:
        return TransitionError("internal: missing pending offense yards", ())
    if not isinstance(event, ScrimmageDefense):
        return TransitionError("expected scrimmage defense dart", ("ScrimmageDefense",))
    sc = rules.scrimmage
    off_yards = state.scrimmage_pending_offense_yards
    kind = state.scrimmage_pending_offense_kind
    eff = (
        event.segment
        if event.bull == "none"
        else effective_segment_with_bull(event.segment, event.bull, rules)
    )
    if eff < sc.segment_min or eff > sc.segment_max:
        return TransitionError(
            f"segment must be {sc.segment_min}..{sc.segment_max}",
            ("ScrimmageDefense",),
        )

    if not sc.use_wedge_number_yards or kind == "none":
        if sc.use_wedge_number_yards and event.bull == "red":
            hypo = advance_field_position(state.field, off_yards)
            new_clock, st = advance_clock_for_scrimmage_play(state, rules)
            s_inter = replace(
                st,
                clock=new_clock,
                scrimmage_pending_offense_yards=None,
                scrimmage_pending_offense_kind="none",
                scrimmage_pending_offense_eff_segment=None,
            )
            if is_touchdown_field(hypo):
                scoring = state.offense
                s_td = state_after_touchdown(s_inter, scoring, rules)
                return TransitionOk(
                    s_td,
                    Phase.AFTER_TOUCHDOWN_CHOICE,
                    f"Play: off {off_yards} yds | def red bull moot — TD {scoring.value}! (+{rules.scoring.touchdown})",
                )
            s_to = defensive_takeover_at_spot(s_inter, hypo)
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
            def_yards = match_scrimmage_yard_band(sc.defense_yards, eff)
            if def_yards is None:
                return TransitionError(
                    f"no defense yard band for segment {eff}",
                    ("ScrimmageDefense",),
                )
        raw_net = off_yards - def_yards
        net = max(raw_net, -sc.max_loss_yards)
        new_field = advance_field_position(state.field, net)
        new_clock, st = advance_clock_for_scrimmage_play(state, rules)
        s_inter = replace(
            st,
            field=new_field,
            clock=new_clock,
            scrimmage_pending_offense_yards=None,
            scrimmage_pending_offense_kind="none",
            scrimmage_pending_offense_eff_segment=None,
        )
        dn = defense_ring_note(event)
        return finish_scrimmage_net_play(
            state, rules, s_inter, new_field, off_yards, def_yards, net, dn
        )

    if kind == "wedge":
        if event.bull == "green":
            return TransitionOk(
                replace(state),
                Phase.SCRIMMAGE_STRIP_DART,
                "Defense green bull — throw a numbered wedge dart (strip). Same board wedge color as offense wedge: "
                "full offensive yards then turnover (or offensive TD); else turnover at LOS.",
            )
        if event.bull == "red":
            return defensive_touchdown_after_offense_yards(
                state,
                rules,
                off_yards,
                f"Play: off {off_yards} yds | def red bull",
            )
        def_yards = eff
        raw_net = off_yards - def_yards
        net = max(raw_net, -sc.max_loss_yards)
        new_field = advance_field_position(state.field, net)
        new_clock, st = advance_clock_for_scrimmage_play(state, rules)
        s_inter = replace(
            st,
            field=new_field,
            clock=new_clock,
            scrimmage_pending_offense_yards=None,
            scrimmage_pending_offense_kind="none",
            scrimmage_pending_offense_eff_segment=None,
        )
        dn = defense_ring_note(event)
        return finish_scrimmage_net_play(
            state, rules, s_inter, new_field, off_yards, def_yards, net, dn
        )

    if kind == "green":
        if event.bull == "red":
            new_clock, st = advance_clock_for_scrimmage_play(state, rules)
            s_inter = replace(
                st,
                clock=new_clock,
                scrimmage_pending_offense_yards=None,
                scrimmage_pending_offense_kind="none",
                scrimmage_pending_offense_eff_segment=None,
            )
            s_to = defensive_takeover_at_spot(s_inter, state.field)
            return TransitionOk(
                s_to,
                Phase.SCRIMMAGE_OFFENSE,
                f"Play: off {off_yards} yds (off green) | def red bull — turnover at LOS | "
                f"{format_possession_summary(s_to)}",
            )
        new_clock, st = advance_clock_for_scrimmage_play(state, rules)
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
        return no_gain_advance_down(s_inter, state, state.field, summ)

    if event.bull == "red":
        new_clock, st = advance_clock_for_scrimmage_play(state, rules)
        s_inter = replace(
            st,
            clock=new_clock,
            scrimmage_pending_offense_yards=None,
            scrimmage_pending_offense_kind="none",
            scrimmage_pending_offense_eff_segment=None,
        )
        return no_gain_advance_down(
            s_inter,
            state,
            state.field,
            "Play: offense red bull | def red — no gain at LOS",
        )
    new_clock, st = advance_clock_for_scrimmage_play(state, rules)
    s_inter = replace(
        st,
        clock=new_clock,
        scrimmage_pending_offense_yards=None,
        scrimmage_pending_offense_kind="none",
        scrimmage_pending_offense_eff_segment=None,
    )
    return no_gain_advance_down(
        s_inter,
        state,
        state.field,
        "Play: offense red bull | def dart — no effect, no gain",
    )


def handle_scrimmage_strip_dart(
    state: GameState,
    event: Event,
    rules: RuleSet,
) -> TransitionOk | TransitionError:
    if state.scrimmage_pending_offense_kind != "wedge":
        return TransitionError("strip dart only after defense green vs offense numbered wedge", ())
    if (
        state.scrimmage_pending_offense_yards is None
        or state.scrimmage_pending_offense_eff_segment is None
    ):
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
    new_clock, st = advance_clock_for_scrimmage_play(state, rules)
    pending_clear = {
        "scrimmage_pending_offense_yards": None,
        "scrimmage_pending_offense_kind": "none",
        "scrimmage_pending_offense_eff_segment": None,
    }
    if wedge_board_colors_match(off_eff, seg):
        hypo = advance_field_position(state.field, off_yards)
        s_inter = replace(st, clock=new_clock, field=hypo, **pending_clear)
        if is_touchdown_field(hypo):
            scoring = state.offense
            s_td = state_after_touchdown(s_inter, scoring, rules)
            return TransitionOk(
                s_td,
                Phase.AFTER_TOUCHDOWN_CHOICE,
                f"Strip match — offense gains {off_yards} yds | TD {scoring.value}! (+{rules.scoring.touchdown})",
            )
        s_to = defensive_takeover_at_spot(s_inter, hypo)
        return TransitionOk(
            s_to,
            Phase.SCRIMMAGE_OFFENSE,
            f"Strip match — offense gains {off_yards} yds then turnover | {format_possession_summary(s_to)}",
        )
    s_inter = replace(st, clock=new_clock, **pending_clear)
    s_to = defensive_takeover_at_spot(s_inter, state.field)
    return TransitionOk(
        s_to,
        Phase.SCRIMMAGE_OFFENSE,
        f"Strip no color match — turnover at LOS | {format_possession_summary(s_to)}",
    )


def handle_safety_sequence(
    state: GameState,
    event: Event,
    rules: RuleSet,
) -> TransitionOk | TransitionError:
    if not isinstance(event, ConfirmSafetyKickoff):
        return TransitionError(
            "expected confirm safety free kick",
            ("ConfirmSafetyKickoff",),
        )
    if state.safety_pending_kicker is None:
        return TransitionError("internal: no pending safety kicker", ())
    k = state.safety_pending_kicker
    recv = opponent(k)
    s2 = replace(state, safety_pending_kicker=None)
    s3 = setup_safety_free_kick(s2, k, recv, rules)
    return TransitionOk(
        s3,
        Phase.KICKOFF_KICK,
        "Safety free kick — kicker chooses regular or onside, then throw",
    )


def handle_overtime_start(
    state: GameState,
    event: Event,
    rules: RuleSet,
) -> TransitionOk | TransitionError:
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


def handle_game_over(
    state: GameState,
    event: Event,
    rules: RuleSet,
) -> TransitionOk | TransitionError:
    return TransitionError("game over", ())
