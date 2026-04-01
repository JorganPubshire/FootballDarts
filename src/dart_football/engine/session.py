from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dart_football.engine.event_codec import (
    decode_game_state,
    encode_game_state,
    event_from_dict,
    event_to_dict,
)
from dart_football.engine.events import Event
from dart_football.engine.phases import Phase, phase_from_stored
from dart_football.engine.state import GameState
from dart_football.engine.transitions import TransitionError, TransitionOk, transition
from dart_football.rules.schema import RuleSet


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
            "event": event_to_dict(self.event),
            "phase_after": self.phase_after.value,
            "state_after": encode_game_state(self.state_after),
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
            phase_before=phase_from_stored(str(d["phase_before"])),
            event=event_from_dict(d["event"]),
            phase_after=phase_from_stored(str(d["phase_after"])),
            state_after=decode_game_state(d["state_after"]),
            effects_summary=str(d["effects_summary"]),
            ruleset_id=str(d["ruleset_id"]),
            ruleset_version=int(d["ruleset_version"]),
            timestamp_iso=d.get("timestamp_iso"),
            source=str(d.get("source", "cli")),
            supersedes_seq=int(d["supersedes_seq"])
            if d.get("supersedes_seq") is not None
            else None,
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
    #: When True, CLI draws the multi-row bordered field; default is single-line field.
    large_field: bool = False

    @staticmethod
    def new(
        initial_state: GameState,
        initial_phase: Phase,
        rules: RuleSet,
        rules_path: str | None = None,
        *,
        large_field: bool = False,
    ) -> GameSession:
        return GameSession(
            initial_state=initial_state,
            initial_phase=initial_phase,
            rules=rules,
            rules_path=rules_path,
            records=[],
            head=0,
            redo_stack=[],
            load_warnings=(),
            large_field=large_field,
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
            timestamp_iso=datetime.now(UTC).isoformat(),
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
            "initial_state": encode_game_state(self.initial_state),
            "initial_phase": self.initial_phase.value,
            "head": self.head,
            "records": [r.to_json_dict() for r in self.records],
            "redo": [r.to_json_dict() for r in self.redo_stack],
            "large_field": self.large_field,
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
        mismatch = (
            rules.ruleset_id != raw["ruleset_id"] or rules.ruleset_version != raw["ruleset_version"]
        )
        if mismatch:
            msg = (
                f"session expects ruleset {raw['ruleset_id']} v{raw['ruleset_version']}, "
                f"but loaded file is {rules.ruleset_id} v{rules.ruleset_version}"
            )
            if not force:
                raise ValueError(msg)
            warnings.append(msg + " — continuing with --force; replay may be inconsistent.")
        initial = decode_game_state(raw["initial_state"])
        sess = GameSession(
            initial_state=initial,
            initial_phase=phase_from_stored(str(raw["initial_phase"])),
            rules=rules,
            rules_path=str(rules_path),
            records=[TransitionRecord.from_json_dict(x) for x in raw["records"]],
            head=int(raw["head"]),
            redo_stack=[TransitionRecord.from_json_dict(x) for x in raw.get("redo", [])],
            load_warnings=tuple(warnings),
            large_field=bool(raw.get("large_field", False)),
        )
        if sess.head > len(sess.records):
            raise ValueError("invalid session: head past records")
        return sess
