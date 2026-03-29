from __future__ import annotations

import json
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from dart_football.engine.events import (
    CallTimeout,
    ChooseKickoffKind,
    ChooseKickoffTouchbackOrRun,
    ChooseKickOrReceive,
    ChoosePatOrTwo,
    CoinTossWinner,
    Event,
    ExtraPointOutcome,
    FieldGoalOutcome,
    FourthDownChoice,
    KickoffKick,
    KickoffReturnKick,
    KickoffRunOutKick,
    PuntKick,
    ScrimmageDefense,
    ScrimmageOffense,
    TwoPointOutcome,
)
from dart_football.engine.phases import Phase
from dart_football.engine.state import (
    DownAndDistance,
    FieldPosition,
    GameClock,
    GameState,
    Scoreboard,
    TeamId,
    Timeouts,
)
from dart_football.engine.transitions import TransitionError, TransitionOk, transition
from dart_football.rules.schema import RuleSet


def _event_to_dict(e: Event) -> dict[str, Any]:
    name = type(e).__name__
    if name == "CoinTossWinner":
        return {"type": name, "winner": e.winner.value}
    if name == "ChooseKickOrReceive":
        return {"type": name, "kick": e.kick}
    if name == "ChooseKickoffKind":
        return {"type": name, "onside": e.onside}
    if name == "KickoffKick":
        return {"type": name, "segment": e.segment, "bull": e.bull}
    if name == "ChooseKickoffTouchbackOrRun":
        return {"type": name, "take_touchback": e.take_touchback}
    if name == "KickoffRunOutKick":
        return {"type": name, "segment": e.segment, "bull": e.bull}
    if name == "KickoffReturnKick":
        return {
            "type": name,
            "segment": e.segment,
            "double_ring": e.double_ring,
            "triple_ring": e.triple_ring,
            "triple_inner": e.triple_inner,
            "bull": e.bull,
        }
    if name == "ScrimmageOffense":
        return {
            "type": name,
            "segment": e.segment,
            "double_ring": e.double_ring,
            "triple_ring": e.triple_ring,
            "triple_inner": e.triple_inner,
            "bull": e.bull,
        }
    if name == "ScrimmageDefense":
        return {
            "type": name,
            "segment": e.segment,
            "bull": e.bull,
            "double_ring": e.double_ring,
            "triple_ring": e.triple_ring,
            "triple_inner": e.triple_inner,
        }
    if name == "FourthDownChoice":
        return {"type": name, "kind": e.kind}
    if name == "FieldGoalOutcome":
        return {"type": name, "kind": e.kind}
    if name == "PuntKick":
        return {"type": name, "segment": e.segment, "bull": e.bull}
    if name == "ChoosePatOrTwo":
        return {"type": name, "extra_point": e.extra_point}
    if name == "ExtraPointOutcome":
        return {"type": name, "good": e.good}
    if name == "TwoPointOutcome":
        return {"type": name, "good": e.good}
    if name == "CallTimeout":
        return {"type": name, "team": e.team.value}
    raise TypeError(e)


def _event_from_dict(d: dict[str, Any]) -> Event:
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
        )
    if t == "ChooseKickoffTouchbackOrRun":
        return ChooseKickoffTouchbackOrRun(take_touchback=bool(d["take_touchback"]))
    if t == "KickoffRunOutKick":
        return KickoffRunOutKick(
            segment=int(d["segment"]),
            bull=d.get("bull", "none"),  # type: ignore[arg-type]
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
        )
    if t == "ScrimmageOffense":
        ti = d.get("triple_inner")
        triple_inner: bool | None
        if ti is None:
            triple_inner = None
        else:
            triple_inner = bool(ti)
        return ScrimmageOffense(
            segment=int(d["segment"]),
            double_ring=bool(d.get("double_ring", False)),
            triple_ring=bool(d.get("triple_ring", False)),
            triple_inner=triple_inner,
            bull=d.get("bull", "none"),  # type: ignore[arg-type]
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
        )
    if t == "FourthDownChoice":
        return FourthDownChoice(kind=d["kind"])  # type: ignore[arg-type]
    if t == "FieldGoalOutcome":
        return FieldGoalOutcome(kind=d["kind"])  # type: ignore[arg-type]
    if t == "PuntKick":
        return PuntKick(segment=int(d["segment"]), bull=d.get("bull", "none"))  # type: ignore[arg-type]
    if t == "ChoosePatOrTwo":
        return ChoosePatOrTwo(extra_point=bool(d["extra_point"]))
    if t == "ExtraPointOutcome":
        return ExtraPointOutcome(good=bool(d["good"]))
    if t == "TwoPointOutcome":
        return TwoPointOutcome(good=bool(d["good"]))
    if t == "CallTimeout":
        return CallTimeout(TeamId(d["team"]))
    raise ValueError(f"unknown event {t}")


def _encode_state(state: GameState) -> dict[str, Any]:
    def conv(v: Any) -> Any:
        if isinstance(v, TeamId):
            return {"__team__": v.value}
        if is_dataclass(v) and not isinstance(v, type):
            return {k.name: conv(getattr(v, k.name)) for k in fields(v)}
        return v

    return conv(state)


def _decode_state(d: dict[str, Any]) -> GameState:
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
        last_touchdown_team=team(d.get("last_touchdown_team")),
    )


@dataclass(frozen=True)
class TransitionRecord:
    seq: int
    phase_before: Phase
    event: Event
    phase_after: Phase
    state_after: GameState
    effects_summary: str
    ruleset_id: str
    ruleset_version: int
    timestamp_iso: str | None = None
    source: str = "cli"
    supersedes_seq: int | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "phase_before": self.phase_before.value,
            "event": _event_to_dict(self.event),
            "phase_after": self.phase_after.value,
            "state_after": _encode_state(self.state_after),
            "effects_summary": self.effects_summary,
            "ruleset_id": self.ruleset_id,
            "ruleset_version": self.ruleset_version,
            "timestamp_iso": self.timestamp_iso,
            "source": self.source,
            "supersedes_seq": self.supersedes_seq,
        }

    @staticmethod
    def from_json_dict(d: dict[str, Any]) -> TransitionRecord:
        return TransitionRecord(
            seq=int(d["seq"]),
            phase_before=Phase(d["phase_before"]),
            event=_event_from_dict(d["event"]),
            phase_after=Phase(d["phase_after"]),
            state_after=_decode_state(d["state_after"]),
            effects_summary=str(d["effects_summary"]),
            ruleset_id=str(d["ruleset_id"]),
            ruleset_version=int(d["ruleset_version"]),
            timestamp_iso=d.get("timestamp_iso"),
            source=str(d.get("source", "cli")),
            supersedes_seq=int(d["supersedes_seq"]) if d.get("supersedes_seq") is not None else None,
        )


@dataclass
class GameSession:
    initial_state: GameState
    initial_phase: Phase
    rules: RuleSet
    rules_path: str | None
    records: list[TransitionRecord]
    head: int
    redo_stack: list[TransitionRecord]
    load_warnings: tuple[str, ...] = ()

    @staticmethod
    def new(initial_state: GameState, initial_phase: Phase, rules: RuleSet, rules_path: str | None = None) -> GameSession:
        return GameSession(
            initial_state=initial_state,
            initial_phase=initial_phase,
            rules=rules,
            rules_path=rules_path,
            records=[],
            head=0,
            redo_stack=[],
            load_warnings=(),
        )

    def current_state_phase(self) -> tuple[GameState, Phase]:
        if self.head == 0:
            return self.initial_state, self.initial_phase
        r = self.records[self.head - 1]
        return r.state_after, r.phase_after

    def apply(self, event: Event, source: str = "cli") -> TransitionOk | TransitionError:
        state, phase = self.current_state_phase()
        out = transition(state, phase, event, self.rules)
        if isinstance(out, TransitionError):
            return out
        seq = self.head + 1
        rec = TransitionRecord(
            seq=seq,
            phase_before=phase,
            event=event,
            phase_after=out.phase,
            state_after=out.state,
            effects_summary=out.effects_summary,
            ruleset_id=self.rules.ruleset_id,
            ruleset_version=self.rules.ruleset_version,
            timestamp_iso=datetime.now(timezone.utc).isoformat(),
            source=source,
        )
        self.records.append(rec)
        self.head = seq
        self.redo_stack.clear()
        return out

    def undo(self) -> bool:
        if self.head <= 0:
            return False
        dropped = self.records.pop()
        self.head -= 1
        self.redo_stack.append(dropped)
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        r = self.redo_stack.pop()
        self.records.append(r)
        self.head = r.seq
        return True

    def correct(self, event: Event) -> TransitionOk | TransitionError:
        if self.head <= 0:
            return TransitionError("nothing to correct", ())
        voided_seq = self.head
        self.undo()
        out = self.apply(event, source="cli")
        if isinstance(out, TransitionError):
            restored = self.redo_stack.pop()
            self.records.append(restored)
            self.head = restored.seq
            return out
        last = self.records[-1]
        self.records[-1] = TransitionRecord(
            seq=last.seq,
            phase_before=last.phase_before,
            event=last.event,
            phase_after=last.phase_after,
            state_after=last.state_after,
            effects_summary=last.effects_summary,
            ruleset_id=last.ruleset_id,
            ruleset_version=last.ruleset_version,
            timestamp_iso=last.timestamp_iso,
            source=last.source,
            supersedes_seq=voided_seq,
        )
        return out

    def save(self, path: str | Path) -> None:
        p = Path(path)
        payload = {
            "format": "dart_football_session",
            "format_version": 1,
            "ruleset_id": self.rules.ruleset_id,
            "ruleset_version": self.rules.ruleset_version,
            "rules_path": self.rules_path,
            "initial_state": _encode_state(self.initial_state),
            "initial_phase": self.initial_phase.value,
            "head": self.head,
            "records": [r.to_json_dict() for r in self.records],
            "redo": [r.to_json_dict() for r in self.redo_stack],
        }
        p.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @staticmethod
    def load(
        path: str | Path,
        rules_loader: Callable[[str], RuleSet],
        *,
        force: bool = False,
    ) -> GameSession:
        p = Path(path)
        raw = json.loads(p.read_text(encoding="utf-8"))
        if raw.get("format") != "dart_football_session":
            raise ValueError("unknown session format")
        rules_path = raw.get("rules_path")
        if not rules_path:
            raise ValueError("session missing rules_path")
        rules = rules_loader(str(rules_path))
        warnings: list[str] = []
        mismatch = rules.ruleset_id != raw["ruleset_id"] or rules.ruleset_version != raw["ruleset_version"]
        if mismatch:
            msg = (
                f"session expects ruleset {raw['ruleset_id']} v{raw['ruleset_version']}, "
                f"but loaded file is {rules.ruleset_id} v{rules.ruleset_version}"
            )
            if not force:
                raise ValueError(msg)
            warnings.append(msg + " — continuing with --force; replay may be inconsistent.")
        initial = _decode_state(raw["initial_state"])
        sess = GameSession(
            initial_state=initial,
            initial_phase=Phase(raw["initial_phase"]),
            rules=rules,
            rules_path=str(rules_path),
            records=[TransitionRecord.from_json_dict(x) for x in raw["records"]],
            head=int(raw["head"]),
            redo_stack=[TransitionRecord.from_json_dict(x) for x in raw.get("redo", [])],
            load_warnings=tuple(warnings),
        )
        if sess.head > len(sess.records):
            raise ValueError("invalid session: head past records")
        return sess
