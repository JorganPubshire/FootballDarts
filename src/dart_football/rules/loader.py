from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from dart_football.rules.schema import (
    FieldGoalRules,
    KickoffBand,
    KickoffRules,
    OvertimeRules,
    PatRules,
    PuntRules,
    RuleSet,
    ScoringRules,
    ScrimmageRules,
    ScrimmageYardBand,
    StructureRules,
    ThrowMarkers,
)


def _segments_from_row(row: dict[str, Any]) -> frozenset[int]:
    raw = row.get("segments")
    if raw is None:
        raise ValueError("kickoff band missing segments")
    if isinstance(raw, list):
        return frozenset(int(x) for x in raw)
    raise TypeError("segments must be a list of integers")


def _parse_kickoff_bands(data: dict[str, Any]) -> tuple[KickoffBand, ...]:
    bands_raw = data.get("bands")
    if bands_raw is None:
        return ()
    if not isinstance(bands_raw, list):
        raise TypeError("kickoff.bands must be a list")
    out: list[KickoffBand] = []
    for row in bands_raw:
        if not isinstance(row, dict):
            raise TypeError("each kickoff band must be a table")
        segs = _segments_from_row(row)
        effect = row.get("effect")
        if not isinstance(effect, dict):
            raise ValueError("band missing effect table")
        kind = effect.get("kind")
        if kind == "touchback":
            line = effect.get("touchback_line")
            if line is None:
                raise ValueError("touchback effect needs touchback_line")
            out.append(KickoffBand(segments=segs, kind="touchback", touchback_line=int(line)))
        elif kind == "field":
            y = effect.get("yards_from_receiving_goal")
            if y is None:
                raise ValueError("field effect needs yards_from_receiving_goal")
            out.append(
                KickoffBand(
                    segments=segs,
                    kind="field",
                    field_yard_from_receiving_goal=int(y),
                )
            )
        elif kind == "wedge_times":
            mult = effect.get("multiplier")
            if mult is None:
                raise ValueError("wedge_times effect needs multiplier")
            out.append(KickoffBand(segments=segs, kind="wedge_times", multiplier=int(mult)))
        elif kind == "wedge_times_penalty":
            mult = effect.get("multiplier")
            pen = effect.get("penalty_yards")
            if mult is None or pen is None:
                raise ValueError("wedge_times_penalty needs multiplier and penalty_yards")
            out.append(
                KickoffBand(
                    segments=segs,
                    kind="wedge_times_penalty",
                    multiplier=int(mult),
                    penalty_yards=int(pen),
                )
            )
        else:
            raise ValueError(f"unknown kickoff effect kind: {kind!r}")
    return tuple(out)


def _parse_scrimmage_yard_bands(table_key: str, data: dict[str, Any]) -> tuple[ScrimmageYardBand, ...]:
    bands_raw = data.get(table_key)
    if bands_raw is None:
        return ()
    if not isinstance(bands_raw, list):
        raise TypeError(f"scrimmage.{table_key} must be a list")
    out: list[ScrimmageYardBand] = []
    for row in bands_raw:
        if not isinstance(row, dict):
            raise TypeError(f"each scrimmage.{table_key} row must be a table")
        segs = _segments_from_row(row)
        y = row.get("yards")
        if y is None:
            raise ValueError(f"scrimmage.{table_key} row missing yards")
        out.append(ScrimmageYardBand(segments=segs, yards=int(y)))
    return tuple(out)


def parse_rules_dict(raw: dict[str, Any]) -> RuleSet:
    meta = raw.get("ruleset")
    if not isinstance(meta, dict):
        raise ValueError("missing [ruleset] section")
    version = int(meta["version"])
    rules_id = str(meta["id"])

    scoring = ScoringRules()
    if "scoring" in raw and isinstance(raw["scoring"], dict):
        s = raw["scoring"]
        scoring = ScoringRules(
            touchdown=int(s.get("touchdown", scoring.touchdown)),
            field_goal=int(s.get("field_goal", scoring.field_goal)),
            safety=int(s.get("safety", scoring.safety)),
            pat=int(s.get("pat", scoring.pat)),
            two_point=int(s.get("two_point", scoring.two_point)),
        )

    structure = StructureRules()
    if "structure" in raw and isinstance(raw["structure"], dict):
        st = raw["structure"]
        structure = StructureRules(
            quarters=int(st.get("quarters", structure.quarters)),
            downs_per_series=int(st.get("downs_per_series", structure.downs_per_series)),
            timeouts_per_half=int(st.get("timeouts_per_half", structure.timeouts_per_half)),
        )

    kickoff = KickoffRules()
    if "kickoff" in raw and isinstance(raw["kickoff"], dict):
        k = raw["kickoff"]
        kickoff = KickoffRules(
            segment_min=int(k.get("segment_min", kickoff.segment_min)),
            segment_max=int(k.get("segment_max", kickoff.segment_max)),
            bands=_parse_kickoff_bands(k),
            kickoff_yard_multiplier=int(k.get("kickoff_yard_multiplier", kickoff.kickoff_yard_multiplier)),
        )

    scrimmage = ScrimmageRules()
    if "scrimmage" in raw and isinstance(raw["scrimmage"], dict):
        sc = raw["scrimmage"]
        scrimmage = ScrimmageRules(
            segment_min=int(sc.get("segment_min", scrimmage.segment_min)),
            segment_max=int(sc.get("segment_max", scrimmage.segment_max)),
            max_loss_yards=int(sc.get("max_loss_yards", scrimmage.max_loss_yards)),
            double_multiplier=int(sc.get("double_multiplier", scrimmage.double_multiplier)),
            triple_multiplier=int(sc.get("triple_multiplier", scrimmage.triple_multiplier)),
            use_pdf_segment_yards=bool(sc.get("use_pdf_segment_yards", scrimmage.use_pdf_segment_yards)),
            bull_green_segment=int(sc.get("bull_green_segment", scrimmage.bull_green_segment)),
            bull_red_segment=int(sc.get("bull_red_segment", scrimmage.bull_red_segment)),
            offense_yards=_parse_scrimmage_yard_bands("offense_yards", sc),
            defense_yards=_parse_scrimmage_yard_bands("defense_yards", sc),
        )

    field_goal = FieldGoalRules()
    if "field_goal" in raw and isinstance(raw["field_goal"], dict):
        fg = raw["field_goal"]
        field_goal = FieldGoalRules(
            distance_round_to=int(fg.get("distance_round_to", field_goal.distance_round_to)),
            max_distance_yards=int(fg.get("max_distance_yards", field_goal.max_distance_yards)),
            miss_spot_offset_yards=int(fg.get("miss_spot_offset_yards", field_goal.miss_spot_offset_yards)),
        )

    punt = PuntRules()
    if "punt" in raw and isinstance(raw["punt"], dict):
        pu = raw["punt"]
        punt = PuntRules(
            segment_min=int(pu.get("segment_min", punt.segment_min)),
            segment_max=int(pu.get("segment_max", punt.segment_max)),
            bands=_parse_kickoff_bands(pu),
        )

    pat = PatRules()
    if "pat" in raw and isinstance(raw["pat"], dict):
        pa = raw["pat"]
        pat = PatRules(pat_advances_game_clock=bool(pa.get("pat_advances_game_clock", pat.pat_advances_game_clock)))

    overtime = OvertimeRules()
    if "overtime" in raw and isinstance(raw["overtime"], dict):
        ot = raw["overtime"]
        overtime = OvertimeRules(
            enabled=bool(ot.get("enabled", overtime.enabled)),
            template=str(ot.get("template", overtime.template)),
        )

    throw_markers = ThrowMarkers()
    if "throw_markers" in raw and isinstance(raw["throw_markers"], dict):
        tm = raw["throw_markers"]
        throw_markers = ThrowMarkers(
            kickoff_line=str(tm.get("kickoff_line", throw_markers.kickoff_line)),
            offense_line=str(tm.get("offense_line", throw_markers.offense_line)),
            defense_line=str(tm.get("defense_line", throw_markers.defense_line)),
            punt_line=str(tm.get("punt_line", throw_markers.punt_line)),
            field_goal_line=str(tm.get("field_goal_line", throw_markers.field_goal_line)),
            pat_line=str(tm.get("pat_line", throw_markers.pat_line)),
            two_point_line=str(tm.get("two_point_line", throw_markers.two_point_line)),
        )

    return RuleSet(
        ruleset_version=version,
        ruleset_id=rules_id,
        scoring=scoring,
        structure=structure,
        kickoff=kickoff,
        scrimmage=scrimmage,
        field_goal=field_goal,
        punt=punt,
        pat=pat,
        overtime=overtime,
        throw_markers=throw_markers,
    )


def load_rules_path(path: str | Path) -> RuleSet:
    p = Path(path)
    with p.open("rb") as f:
        data = tomllib.load(f)
    return parse_rules_dict(data)


def default_ruleset_path() -> Path:
    """Project ``rules/standard.toml`` (repo root, sibling of ``src``)."""
    return Path(__file__).resolve().parents[3] / "rules" / "standard.toml"
