"""JSON-serializable encoding for game events and ``GameState`` (save/load)."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any

from dart_football.engine.events import (
    CallTimeout,
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
from dart_football.engine.state import (
    DownAndDistance,
    FieldPosition,
    GameClock,
    GameState,
    Scoreboard,
    TeamId,
    Timeouts,
)


def event_to_dict(e: Event) -> dict[str, Any]:
    name = type(e).__name__
    if name == "CoinTossWinner":
        return {"type": name, "winner": e.winner.value}
    if name == "ChooseKickOrReceive":
        return {"type": name, "kick": e.kick}
    if name == "ChooseKickoffKind":
        return {"type": name, "onside": e.onside}
    if name == "KickoffKick":
        return {"type": name, "segment": e.segment, "bull": e.bull, "miss": e.miss}
    if name == "ChooseKickoffTouchbackOrRun":
        return {"type": name, "take_touchback": e.take_touchback}
    if name == "KickoffRunOutKick":
        return {"type": name, "segment": e.segment, "bull": e.bull, "miss": e.miss}
    if name == "KickoffReturnKick":
        return {
            "type": name,
            "segment": e.segment,
            "double_ring": e.double_ring,
            "triple_ring": e.triple_ring,
            "triple_inner": e.triple_inner,
            "bull": e.bull,
            "miss": e.miss,
        }
    if name == "ScrimmageOffense":
        return {
            "type": name,
            "segment": e.segment,
            "double_ring": e.double_ring,
            "triple_ring": e.triple_ring,
            "triple_inner": e.triple_inner,
            "bull": e.bull,
            "miss": e.miss,
        }
    if name == "ScrimmageDefense":
        return {
            "type": name,
            "segment": e.segment,
            "bull": e.bull,
            "double_ring": e.double_ring,
            "triple_ring": e.triple_ring,
            "triple_inner": e.triple_inner,
            "miss": e.miss,
        }
    if name == "ScrimmageStripDart":
        return {"type": name, "segment": e.segment}
    if name == "FourthDownChoice":
        return {"type": name, "kind": e.kind}
    if name == "FieldGoalOutcome":
        return {"type": name, "kind": e.kind}
    if name == "FieldGoalOffenseDart":
        return {"type": name, "zone": e.zone, "segment": e.segment, "miss": e.miss}
    if name == "ChooseFieldGoalAfterGreen":
        return {"type": name, "real_kick": e.real_kick}
    if name == "FieldGoalFakeOffenseDart":
        return {
            "type": name,
            "segment": e.segment,
            "double_ring": e.double_ring,
            "triple_ring": e.triple_ring,
            "triple_inner": e.triple_inner,
            "bull": e.bull,
            "miss": e.miss,
        }
    if name == "FieldGoalDefenseDart":
        return {
            "type": name,
            "segment": e.segment,
            "bull": e.bull,
            "double_ring": e.double_ring,
            "triple_ring": e.triple_ring,
            "triple_inner": e.triple_inner,
            "miss": e.miss,
        }
    if name == "PuntKick":
        return {"type": name, "segment": e.segment, "bull": e.bull, "miss": e.miss}
    if name == "ChooseExtraPointOrTwo":
        return {"type": name, "extra_point": e.extra_point}
    if name == "ExtraPointOutcome":
        return {"type": name, "good": e.good}
    if name == "TwoPointOutcome":
        return {"type": name, "good": e.good}
    if name == "CallTimeout":
        return {"type": name, "team": e.team.value}
    if name == "ConfirmSafetyKickoff":
        return {"type": name}
    raise TypeError(e)


def event_from_dict(d: dict[str, Any]) -> Event:
    t = d["type"]
    if t == "CoinTossWinner":
        return CoinTossWinner(TeamId(d["winner"]))
    if t == "ChooseKickOrReceive":
        return ChooseKickOrReceive(kick=bool(d["kick"]))
    if t == "ChooseKickoffKind":
        return ChooseKickoffKind(onside=bool(d["onside"]))
    if t == "KickoffKick":
        return KickoffKick(
            segment=int(d["segment"]),
            bull=d.get("bull", "none"),  # type: ignore[arg-type]
            miss=bool(d.get("miss", False)),
        )
    if t == "ChooseKickoffTouchbackOrRun":
        return ChooseKickoffTouchbackOrRun(take_touchback=bool(d["take_touchback"]))
    if t == "KickoffRunOutKick":
        return KickoffRunOutKick(
            segment=int(d["segment"]),
            bull=d.get("bull", "none"),  # type: ignore[arg-type]
            miss=bool(d.get("miss", False)),
        )
    if t == "KickoffReturnKick":
        ti = d.get("triple_inner")
        triple_inner: bool | None
        if ti is None:
            triple_inner = None
        else:
            triple_inner = bool(ti)
        return KickoffReturnKick(
            segment=int(d["segment"]),
            double_ring=bool(d.get("double_ring", False)),
            triple_ring=bool(d.get("triple_ring", False)),
            triple_inner=triple_inner,
            bull=d.get("bull", "none"),  # type: ignore[arg-type]
            miss=bool(d.get("miss", False)),
        )
    if t == "ScrimmageOffense":
        ti = d.get("triple_inner")
        triple_inner_so: bool | None
        if ti is None:
            triple_inner_so = None
        else:
            triple_inner_so = bool(ti)
        return ScrimmageOffense(
            segment=int(d["segment"]),
            double_ring=bool(d.get("double_ring", False)),
            triple_ring=bool(d.get("triple_ring", False)),
            triple_inner=triple_inner_so,
            bull=d.get("bull", "none"),  # type: ignore[arg-type]
            miss=bool(d.get("miss", False)),
        )
    if t == "ScrimmageDefense":
        ti = d.get("triple_inner")
        triple_inner_d: bool | None
        if ti is None:
            triple_inner_d = None
        else:
            triple_inner_d = bool(ti)
        return ScrimmageDefense(
            segment=int(d["segment"]),
            bull=d.get("bull", "none"),  # type: ignore[arg-type]
            double_ring=bool(d.get("double_ring", False)),
            triple_ring=bool(d.get("triple_ring", False)),
            triple_inner=triple_inner_d,
            miss=bool(d.get("miss", False)),
        )
    if t == "ScrimmageStripDart":
        return ScrimmageStripDart(segment=int(d["segment"]))
    if t == "FourthDownChoice":
        return FourthDownChoice(kind=d["kind"])  # type: ignore[arg-type]
    if t == "FieldGoalOutcome":
        return FieldGoalOutcome(kind=d["kind"])  # type: ignore[arg-type]
    if t == "FieldGoalOffenseDart":
        return FieldGoalOffenseDart(
            zone=d["zone"],  # type: ignore[arg-type]
            segment=int(d["segment"]),
            miss=bool(d.get("miss", False)),
        )
    if t == "ChooseFieldGoalAfterGreen":
        return ChooseFieldGoalAfterGreen(real_kick=bool(d["real_kick"]))
    if t == "FieldGoalFakeOffenseDart":
        ti = d.get("triple_inner")
        triple_inner_f: bool | None
        if ti is None:
            triple_inner_f = None
        else:
            triple_inner_f = bool(ti)
        return FieldGoalFakeOffenseDart(
            segment=int(d["segment"]),
            double_ring=bool(d.get("double_ring", False)),
            triple_ring=bool(d.get("triple_ring", False)),
            triple_inner=triple_inner_f,
            bull=d.get("bull", "none"),  # type: ignore[arg-type]
            miss=bool(d.get("miss", False)),
        )
    if t == "FieldGoalDefenseDart":
        ti = d.get("triple_inner")
        triple_inner_fd: bool | None
        if ti is None:
            triple_inner_fd = None
        else:
            triple_inner_fd = bool(ti)
        return FieldGoalDefenseDart(
            segment=int(d["segment"]),
            bull=d.get("bull", "none"),  # type: ignore[arg-type]
            double_ring=bool(d.get("double_ring", False)),
            triple_ring=bool(d.get("triple_ring", False)),
            triple_inner=triple_inner_fd,
            miss=bool(d.get("miss", False)),
        )
    if t == "PuntKick":
        return PuntKick(
            segment=int(d["segment"]),
            bull=d.get("bull", "none"),  # type: ignore[arg-type]
            miss=bool(d.get("miss", False)),
        )
    if t in ("ChooseExtraPointOrTwo", "ChoosePatOrTwo"):
        return ChooseExtraPointOrTwo(extra_point=bool(d["extra_point"]))
    if t == "ExtraPointOutcome":
        return ExtraPointOutcome(good=bool(d["good"]))
    if t == "TwoPointOutcome":
        return TwoPointOutcome(good=bool(d["good"]))
    if t == "CallTimeout":
        return CallTimeout(TeamId(d["team"]))
    if t == "ConfirmSafetyKickoff":
        return ConfirmSafetyKickoff()
    raise ValueError(f"unknown event {t}")


def encode_game_state(state: GameState) -> dict[str, Any]:
    def conv(v: Any) -> Any:
        if isinstance(v, TeamId):
            return {"__team__": v.value}
        if is_dataclass(v) and not isinstance(v, type):
            return {k.name: conv(getattr(v, k.name)) for k in fields(v)}
        return v

    return conv(state)


def decode_game_state(d: dict[str, Any]) -> GameState:
    def team(x: Any) -> TeamId | None:
        if x is None:
            return None
        if isinstance(x, dict) and "__team__" in x:
            return TeamId(x["__team__"])
        raise TypeError(x)

    return GameState(
        scores=Scoreboard(red=int(d["scores"]["red"]), green=int(d["scores"]["green"])),
        offense=team(d["offense"]),  # type: ignore[arg-type]
        field=FieldPosition(
            scrimmage_line=int(d["field"]["scrimmage_line"]),
            goal_yard=int(d["field"]["goal_yard"]),
        ),
        downs=DownAndDistance(
            down=int(d["downs"]["down"]),
            to_go=int(d["downs"]["to_go"]),
            los_yard=int(d["downs"]["los_yard"]),
        ),
        clock=GameClock(
            quarter=int(d["clock"]["quarter"]),
            plays_in_quarter=int(d["clock"]["plays_in_quarter"]),
            total_plays=int(d["clock"]["total_plays"]),
        ),
        timeouts=Timeouts(
            red_q1_q2=int(d["timeouts"]["red_q1_q2"]),
            red_q3_q4=int(d["timeouts"]["red_q3_q4"]),
            green_q1_q2=int(d["timeouts"]["green_q1_q2"]),
            green_q3_q4=int(d["timeouts"]["green_q3_q4"]),
        ),
        coin_toss_winner=team(d.get("coin_toss_winner")),
        kickoff_kicker=team(d.get("kickoff_kicker")),
        kickoff_receiver=team(d.get("kickoff_receiver")),
        kickoff_awaiting=str(d.get("kickoff_awaiting", "none")),
        kickoff_pending_touchback_line=(
            int(d["kickoff_pending_touchback_line"])
            if d.get("kickoff_pending_touchback_line") is not None
            else None
        ),
        declared_fg_attempt=bool(d.get("declared_fg_attempt", False)),
        declared_punt=bool(d.get("declared_punt", False)),
        declared_onside=bool(d.get("declared_onside", False)),
        kickoff_type_selected=bool(d.get("kickoff_type_selected", True)),
        last_play_of_period=bool(d.get("last_play_of_period", False)),
        skip_next_play_clock_bump=bool(d.get("skip_next_play_clock_bump", False)),
        scrimmage_pending_offense_yards=(
            int(d["scrimmage_pending_offense_yards"])
            if d.get("scrimmage_pending_offense_yards") is not None
            else None
        ),
        scrimmage_pending_offense_kind=str(d.get("scrimmage_pending_offense_kind", "none")),
        scrimmage_pending_offense_eff_segment=(
            int(d["scrimmage_pending_offense_eff_segment"])
            if d.get("scrimmage_pending_offense_eff_segment") is not None
            else None
        ),
        last_touchdown_team=team(d.get("last_touchdown_team")),
        fg_snap_field=(
            FieldPosition(
                scrimmage_line=int(d["fg_snap_field"]["scrimmage_line"]),
                goal_yard=int(d["fg_snap_field"]["goal_yard"]),
            )
            if d.get("fg_snap_field")
            else None
        ),
        fg_pending_outcome=str(d.get("fg_pending_outcome", "none")),
        fg_fake_first_down_line=(
            int(d["fg_fake_first_down_line"])
            if d.get("fg_fake_first_down_line") is not None
            else None
        ),
        safety_pending_kicker=team(d.get("safety_pending_kicker")),
        overtime_period=int(d.get("overtime_period", 0)),
    )
