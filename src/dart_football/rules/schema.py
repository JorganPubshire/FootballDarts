from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ScoringRules:
    touchdown: int = 6
    field_goal: int = 3
    safety: int = 2
    pat: int = 1
    two_point: int = 2


@dataclass(frozen=True)
class StructureRules:
    quarters: int = 4
    downs_per_series: int = 4
    timeouts_per_half: int = 3
    #: Plays counted toward ending a quarter (clock bump). 0 = no limit (quarter never advances on plays).
    plays_per_quarter: int = 24

    def __post_init__(self) -> None:
        if self.plays_per_quarter < 0:
            raise ValueError("plays_per_quarter must be non-negative")


@dataclass(frozen=True)
class KickoffBand:
    """
    Kickoff / punt spot bands. Kinds:
    - touchback: ball at receiving team's own yard (touchback_line = 1..99).
    - field: same as touchback (fixed own yard); name kept for TOML compatibility.
    - wedge_times: own yard = clamp(segment * multiplier) (kickoff ×5, punt ×3).
    - wedge_times_penalty: own yard = clamp(segment * multiplier - penalty_yards) (punt 1–6 band).
    """

    segments: frozenset[int]
    kind: str
    touchback_line: int | None = None
    field_yard_from_receiving_goal: int | None = None
    multiplier: int | None = None
    penalty_yards: int | None = None
    #: Touchback band only: receiver may take the ball at touchback_line or run out from the goal line.
    allow_runout_choice: bool = False
    #: Wedge_times band only: after kick spot, receiver must throw a return dart.
    requires_return_dart: bool = False

    def __post_init__(self) -> None:
        if self.kind == "touchback":
            if self.touchback_line is None:
                raise ValueError("touchback_line required for touchback")
            if self.requires_return_dart:
                raise ValueError("requires_return_dart applies to wedge_times only")
        elif self.kind == "field":
            if self.field_yard_from_receiving_goal is None:
                raise ValueError("field_yard_from_receiving_goal required for field")
            if self.allow_runout_choice or self.requires_return_dart:
                raise ValueError("runout/return flags apply to touchback or wedge_times only")
        elif self.kind == "wedge_times":
            if self.multiplier is None:
                raise ValueError("multiplier required for wedge_times")
            if self.allow_runout_choice:
                raise ValueError("allow_runout_choice applies to touchback only")
        elif self.kind == "wedge_times_penalty":
            if self.multiplier is None or self.penalty_yards is None:
                raise ValueError("multiplier and penalty_yards required for wedge_times_penalty")
            if self.allow_runout_choice or self.requires_return_dart:
                raise ValueError("runout/return flags apply to touchback or wedge_times only")
        else:
            raise ValueError(f"unknown kickoff band kind: {self.kind!r}")


@dataclass(frozen=True)
class KickoffRules:
    segment_min: int = 1
    segment_max: int = 20
    bands: tuple[KickoffBand, ...] = ()
    kickoff_yard_multiplier: int = 5


@dataclass(frozen=True)
class ScrimmageYardBand:
    segments: frozenset[int]
    yards: int


@dataclass(frozen=True)
class ScrimmageRules:
    segment_min: int = 1
    segment_max: int = 20
    max_loss_yards: int = 10
    double_multiplier: int = 2
    triple_multiplier: int = 3
    # Offense/defense use wedge number ×1; doubles/triples on offense only. When True, tables below are ignored.
    use_wedge_number_yards: bool = False
    # Legacy tables when use_wedge_number_yards is False.
    bull_green_segment: int = 20
    bull_red_segment: int = 18
    offense_yards: tuple[ScrimmageYardBand, ...] = ()
    defense_yards: tuple[ScrimmageYardBand, ...] = ()


@dataclass(frozen=True)
class FieldGoalRules:
    distance_round_to: int = 10
    max_distance_yards: int = 60
    miss_spot_offset_yards: int = 10


@dataclass(frozen=True)
class PuntRules:
    segment_min: int = 1
    segment_max: int = 20
    bands: tuple[KickoffBand, ...] = ()


@dataclass(frozen=True)
class PatRules:
    pat_advances_game_clock: bool = False


@dataclass(frozen=True)
class OvertimeRules:
    enabled: bool = False
    template: str = "none"


@dataclass(frozen=True)
class ThrowMarkers:
    """
    Where players stand to throw for each situation, as marked on the Football Darts
    board / mat / layout. Loaded from [throw_markers] in the rules TOML.
    """

    kickoff_line: str = (
        "Use the kickoff throwing line: the line marked for kickoffs on your Football Darts "
        "layout (not the offensive or defensive scrimmage lines)."
    )
    offense_line: str = (
        "Use the offensive line of scrimmage: stand at the offense throw marker (O-line / "
        "offense tape) for the current line of scrimmage."
    )
    defense_line: str = (
        "Use the defensive line: stand at the defense throw marker (D-line / defense tape) "
        "on the defensive side of the line of scrimmage."
    )
    punt_line: str = (
        "Use the punt throwing position: the punt line or punt marker described in your "
        "Football Darts setup (not the same as a standard scrimmage throw if your set uses "
        "a separate punt spot)."
    )
    field_goal_line: str = (
        "Use the field goal / placekick throwing position for FG attempts on your layout."
    )
    pat_line: str = (
        "Use the extra-point (PAT) throwing line: the short kick / PAT marker on your layout."
    )
    two_point_line: str = (
        "Use the two-point conversion throwing position on your Football Darts layout."
    )
    coin_toss_dart_line: str = (
        "Oldest player throws a dart at the dartboard, followed by the youngest. "
        "The dart closest to the center of the board elects to kick off or receive."
    )


@dataclass(frozen=True)
class RuleSet:
    ruleset_version: int
    ruleset_id: str
    scoring: ScoringRules = field(default_factory=ScoringRules)
    structure: StructureRules = field(default_factory=StructureRules)
    kickoff: KickoffRules = field(default_factory=KickoffRules)
    scrimmage: ScrimmageRules = field(default_factory=ScrimmageRules)
    field_goal: FieldGoalRules = field(default_factory=FieldGoalRules)
    punt: PuntRules = field(default_factory=PuntRules)
    pat: PatRules = field(default_factory=PatRules)
    overtime: OvertimeRules = field(default_factory=OvertimeRules)
    throw_markers: ThrowMarkers = field(default_factory=ThrowMarkers)

    def __post_init__(self) -> None:
        if self.ruleset_version != 1:
            raise ValueError(f"unsupported ruleset_version: {self.ruleset_version}")
