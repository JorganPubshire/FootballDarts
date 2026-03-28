from __future__ import annotations

from dataclasses import replace
from typing import Literal

from dart_football.display.formatting import format_possession_summary, yards_from_own_goal
from dart_football.engine.events import (
    CallTimeout,
    ChooseKickOrReceive,
    ChoosePatOrTwo,
    CoinTossWinner,
    Event,
    ExtraPointOutcome,
    FieldGoalOutcome,
    FourthDownChoice,
    KickoffKick,
    PuntKick,
    ScrimmageDefense,
    ScrimmageOffense,
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
    """Kickoff/punt: fixed own yard, or wedge × multiplier (PDF)."""
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
    """PDF: receiving-team fumble; kicking team recovers at opponent's 35-yard line."""
    if kicker is TeamId.RED:
        return _field_spot_from_own_yard(kicker, 35)
    return _field_spot_from_own_yard(kicker, 65)


def _match_spot_band(bands: tuple[KickoffBand, ...], segment: int) -> KickoffBand | None:
    for b in bands:
        if segment in b.segments:
            return b
    return None


def _bump_clock(state: GameState) -> GameClock:
    c = state.clock
    return GameClock(
        quarter=c.quarter,
        plays_in_quarter=c.plays_in_quarter + 1,
        total_plays=c.total_plays + 1,
    )


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
    s = replace(state, timeouts=nt)
    return TransitionOk(
        s,
        phase,
        f"{label} timeout (no play counted; {left} left in {half})",
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
        scrimmage_pending_offense_yards=None,
        declared_fg_attempt=False,
        declared_punt=False,
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
        scrimmage_pending_offense_yards=None,
    )


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


def _pdf_fg_sixty_yard_line_ok(state: GameState) -> bool:
    """FootballDartsRules.pdf: 60-yard field goals only from own 40 to 49."""
    dist = _yards_to_goal_line(state.field)
    if _round_up_to_10(dist) != 60:
        return True
    own = yards_from_own_goal(state.offense, state.field)
    return 40 <= own <= 49


def _field_after_missed_field_goal(state: GameState, rules: RuleSet) -> GameState:
    """PDF: missed/blocked FG — opponent takes over at previous line of scrimmage +10 yards."""
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
    )


def _turnover_on_downs_state(state: GameState, field: FieldPosition) -> GameState:
    new_off = _other(state.offense)
    new_goal = 100 if field.goal_yard == 0 else 0
    nf = FieldPosition(field.scrimmage_line, new_goal)
    dist = _yards_to_goal_line(nf)
    downs = DownAndDistance(1, min(10, dist), nf.scrimmage_line)
    return replace(
        state,
        offense=new_off,
        field=nf,
        downs=downs,
        scrimmage_pending_offense_yards=None,
        declared_fg_attempt=False,
        declared_punt=False,
    )


def transition(
    state: GameState,
    phase: Phase,
    event: Event,
    rules: RuleSet,
) -> TransitionOk | TransitionError:
    if phase in (Phase.SAFETY_SEQUENCE, Phase.ONSIDE_KICK, Phase.OVERTIME_START):
        return TransitionError(
            "phase not implemented yet — TODO: align with FootballDartsRules.pdf",
            (),
        )

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
        )
        return TransitionOk(
            s,
            Phase.KICKOFF_KICK,
            f"Kickoff: {kicker.value} kicks, {receiver.value} receives",
        )

    if phase is Phase.KICKOFF_KICK:
        if state.kickoff_kicker is None or state.kickoff_receiver is None:
            return TransitionError("internal: kickoff teams not set", ())
        if not isinstance(event, KickoffKick):
            return TransitionError("expected kickoff segment", ("KickoffKick",))
        kicker = state.kickoff_kicker
        receiver = state.kickoff_receiver
        new_clock = _bump_clock(state)

        if event.bull == "green":
            field = _kickoff_green_bull_field(kicker)
            downs = DownAndDistance(down=1, to_go=10, los_yard=field.scrimmage_line)
            s = replace(
                state,
                offense=kicker,
                field=field,
                downs=downs,
                clock=new_clock,
                kickoff_kicker=None,
                kickoff_receiver=None,
                scrimmage_pending_offense_yards=None,
                last_touchdown_team=None,
            )
            return TransitionOk(
                s,
                Phase.SCRIMMAGE_OFFENSE,
                "Kickoff green bull (PDF): receiving fumble — kicking team ball at opponent 35",
            )

        if event.bull == "red":
            s2 = replace(
                state,
                clock=new_clock,
                kickoff_kicker=None,
                kickoff_receiver=None,
            )
            s_td = _state_after_td(s2, kicker, rules)
            return TransitionOk(
                s_td,
                Phase.PAT_OR_TWO_DECISION,
                f"Kickoff red bull (PDF): receiving fumble — touchdown {kicker.value} (+{rules.scoring.touchdown})",
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
        field = _field_from_spot_band(receiver, band, seg)
        downs = DownAndDistance(down=1, to_go=10, los_yard=field.scrimmage_line)
        s = replace(
            state,
            offense=receiver,
            field=field,
            downs=downs,
            clock=new_clock,
            kickoff_kicker=None,
            kickoff_receiver=None,
            scrimmage_pending_offense_yards=None,
            last_touchdown_team=None,
        )
        summary = f"Kickoff wedge {seg} (PDF) → {format_possession_summary(s)}"
        return TransitionOk(s, Phase.SCRIMMAGE_OFFENSE, summary)

    if phase is Phase.PAT_OR_TWO_DECISION:
        if not isinstance(event, ChoosePatOrTwo):
            return TransitionError("expected PAT or 2-pt choice", ("ChoosePatOrTwo",))
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
        summary = "PAT no good"
        if event.good:
            s2 = replace(s2, scores=s2.scores.add(scoring, rules.scoring.pat))
            summary = f"PAT good (+{rules.scoring.pat})"
        if rules.pat.pat_advances_game_clock:
            s2 = replace(s2, clock=_bump_clock(s2))
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
        s2 = replace(s2, clock=_bump_clock(s2))
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
            if not _pdf_fg_sixty_yard_line_ok(state):
                return TransitionError(
                    "PDF: 60-yard field goals only from your own 40 to 49 yard line",
                    ("FourthDownChoice",),
                )
            return TransitionOk(
                replace(state, declared_fg_attempt=True),
                Phase.FIELD_GOAL_ATTEMPT,
                "Field goal attempt",
            )
        return TransitionError("invalid fourth down kind", ())

    if phase is Phase.FIELD_GOAL_ATTEMPT:
        if not isinstance(event, FieldGoalOutcome):
            return TransitionError("expected field goal outcome", ("FieldGoalOutcome",))
        scoring = state.offense
        dist = _yards_to_goal_line(state.field)
        if event.kind == "good" and dist > rules.field_goal.max_distance_yards:
            return TransitionError(
                f"FG distance {dist} yd exceeds max {rules.field_goal.max_distance_yards}",
                ("FieldGoalOutcome",),
            )
        if event.kind == "good":
            if not _pdf_fg_sixty_yard_line_ok(state):
                return TransitionError(
                    "PDF: 60-yard field goals only from your own 40 to 49 yard line",
                    ("FieldGoalOutcome",),
                )
            s2 = replace(state, scores=state.scores.add(scoring, rules.scoring.field_goal))
            s2 = replace(s2, clock=_bump_clock(state))
            s3 = _setup_kickoff_after_score(s2, scoring, rules)
            return TransitionOk(
                s3,
                Phase.KICKOFF_KICK,
                f"Field goal good (+{rules.scoring.field_goal}) — kickoff next",
            )
        s_to = _field_after_missed_field_goal(state, rules)
        s_to = replace(s_to, clock=_bump_clock(state))
        return TransitionOk(
            s_to,
            Phase.SCRIMMAGE_OFFENSE,
            f"Field goal {event.kind} — opponent ball at previous LOS +{rules.field_goal.miss_spot_offset_yards} yd (PDF)",
        )

    if phase is Phase.PUNT_ATTEMPT:
        if not isinstance(event, PuntKick):
            return TransitionError("expected punt segment", ("PuntKick",))
        if event.bull != "none":
            return TransitionError(
                "punt green/red bull: fake punt / block rules are in FootballDartsRules.pdf — not automated here",
                ("PuntKick",),
            )
        pr = rules.punt
        eff = event.segment
        if eff < pr.segment_min or eff > pr.segment_max:
            return TransitionError(
                f"punt segment must be {pr.segment_min}..{pr.segment_max}",
                ("PuntKick",),
            )
        band = _match_spot_band(pr.bands, eff)
        if band is None:
            return TransitionError(f"no punt band for segment {eff}", ("PuntKick",))
        receiver = _other(state.offense)
        field = _field_from_spot_band(receiver, band, eff)
        dist = _yards_to_goal_line(field)
        downs = DownAndDistance(1, min(10, dist), field.scrimmage_line)
        new_clock = _bump_clock(state)
        s = replace(
            state,
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
                    return TransitionError("PDF: cannot punt on first down", ("FourthDownChoice",))
                return TransitionOk(
                    replace(state, declared_punt=True),
                    Phase.PUNT_ATTEMPT,
                    "Punt attempt",
                )
            if event.kind == "field_goal":
                if state.downs.down not in (3, 4) and not state.last_play_of_period:
                    return TransitionError(
                        "PDF: field goals only on 3rd or 4th down (unless last play of half or game)",
                        ("FourthDownChoice",),
                    )
                dist = _yards_to_goal_line(state.field)
                if dist > rules.field_goal.max_distance_yards:
                    return TransitionError(
                        f"field goal out of range ({dist} yd; max {rules.field_goal.max_distance_yards} yd)",
                        ("FourthDownChoice",),
                    )
                if not _pdf_fg_sixty_yard_line_ok(state):
                    return TransitionError(
                        "PDF: 60-yard field goals only from your own 40 to 49 yard line",
                        ("FourthDownChoice",),
                    )
                return TransitionOk(
                    replace(state, declared_fg_attempt=True),
                    Phase.FIELD_GOAL_ATTEMPT,
                    "Field goal attempt",
                )
        if not isinstance(event, ScrimmageOffense):
            return TransitionError(
                "expected scrimmage offense dart, punt, or field goal",
                ("ScrimmageOffense", "FourthDownChoice"),
            )
        sc = rules.scrimmage
        if sc.use_pdf_segment_yards and event.bull != "none":
            return TransitionError(
                "offense green/red bull: turnover / yardage-dart rules are in FootballDartsRules.pdf — not automated here",
                ("ScrimmageOffense",),
            )
        eff = event.segment if event.bull == "none" else _effective_segment_bull(event.segment, event.bull, rules)
        if eff < sc.segment_min or eff > sc.segment_max:
            return TransitionError(
                f"segment must be {sc.segment_min}..{sc.segment_max}",
                ("ScrimmageOffense",),
            )
        if sc.use_pdf_segment_yards:
            base = eff
        else:
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
        if sc.use_pdf_segment_yards and event.bull != "none":
            return TransitionError(
                "defense green/red bull: nullify / turnover rules are in FootballDartsRules.pdf — not automated here",
                ("ScrimmageDefense",),
            )
        eff = event.segment if event.bull == "none" else _effective_segment_bull(event.segment, event.bull, rules)
        if eff < sc.segment_min or eff > sc.segment_max:
            return TransitionError(
                f"segment must be {sc.segment_min}..{sc.segment_max}",
                ("ScrimmageDefense",),
            )
        if sc.use_pdf_segment_yards:
            def_yards = eff
        else:
            def_yards = _match_scrimmage_yards(sc.defense_yards, eff)
            if def_yards is None:
                return TransitionError(
                    f"no defense yard band for segment {eff}",
                    ("ScrimmageDefense",),
                )
        off_yards = state.scrimmage_pending_offense_yards
        raw_net = off_yards - def_yards
        net = max(raw_net, -sc.max_loss_yards)
        new_field = _advance_field(state.field, net)
        new_clock = _bump_clock(state)
        s_inter = replace(
            state,
            field=new_field,
            clock=new_clock,
            scrimmage_pending_offense_yards=None,
        )
        dn = _defense_ring_note(event)
        if _is_touchdown(new_field):
            scoring = state.offense
            s_td = _state_after_td(s_inter, scoring, rules)
            return TransitionOk(
                s_td,
                Phase.PAT_OR_TWO_DECISION,
                f"Play: off {off_yards} vs def {def_yards}{dn} → net {net} yds | TD {scoring.value}! (+{rules.scoring.touchdown})",
            )
        dist = _yards_to_goal_line(new_field)
        to_go_before = state.downs.to_go
        if net >= to_go_before:
            down = 1
            to_go = min(10, dist)
        else:
            down = state.downs.down + 1
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

    if phase is Phase.GAME_OVER:
        return TransitionError("game over", ())

    return TransitionError(f"unhandled phase {phase!r}", ())
