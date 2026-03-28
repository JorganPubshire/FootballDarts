"""Human-readable dart outcome tables for the CLI (driven by loaded rules)."""

from __future__ import annotations

from dart_football.display.formatting import format_line_of_scrimmage, opponent, team_display_name
from dart_football.engine.state import GameState
from dart_football.rules.schema import KickoffBand, RuleSet, ScrimmageYardBand


def _sorted_seg_str(segments: frozenset[int]) -> str:
    return ", ".join(str(x) for x in sorted(segments))


def format_spot_band_lines(bands: tuple[KickoffBand, ...], header: str) -> list[str]:
    lines = [header, ""]
    for b in bands:
        segs = _sorted_seg_str(b.segments)
        if b.kind == "touchback":
            assert b.touchback_line is not None
            lines.append(f"  Segments {segs}: 1st & 10 at own {b.touchback_line} (FootballDartsRules.pdf).")
        elif b.kind == "field":
            assert b.field_yard_from_receiving_goal is not None
            lines.append(
                f"  Segments {segs}: 1st & 10 at own {b.field_yard_from_receiving_goal} (PDF)."
            )
        elif b.kind == "wedge_times":
            assert b.multiplier is not None
            lines.append(
                f"  Segments {segs}: spot uses wedge × {b.multiplier} yards (own field, clamped); "
                "PDF may require a return dart or other steps — engine uses the spot only."
            )
        elif b.kind == "wedge_times_penalty":
            assert b.multiplier is not None and b.penalty_yards is not None
            lines.append(
                f"  Segments {segs}: wedge × {b.multiplier} − {b.penalty_yards} yd penalty (PDF punt band)."
            )
        else:
            lines.append(f"  Segments {segs}: ({b.kind})")
    return lines


def format_scrimmage_yard_lines(bands: tuple[ScrimmageYardBand, ...], header: str) -> list[str]:
    lines = [header, ""]
    for b in bands:
        segs = _sorted_seg_str(b.segments)
        lines.append(f"  Segments {segs}: {b.yards} base yards")
    return lines


def _kickoff_thrower_line(state: GameState | None) -> list[str]:
    if state is None or state.kickoff_kicker is None:
        return [
            "Kickoff kicker missing from game state — see FootballDartsRules.pdf.",
        ]
    k = state.kickoff_kicker
    return [
        f"Thrower: {team_display_name(k)} is the kickoff kicker — only that player throws this dart.",
    ]


def _offense_thrower_line(state: GameState | None) -> list[str]:
    if state is None:
        return []
    o = state.offense
    return [
        f"Thrower: {team_display_name(o)} is on offense — offense throws this dart.",
        f"Line of scrimmage: {format_line_of_scrimmage(o, state.field)}.",
    ]


def _defense_thrower_line(state: GameState | None) -> list[str]:
    if state is None:
        return []
    d = opponent(state.offense)
    return [
        f"Thrower: {team_display_name(d)} is on defense — defense throws this dart.",
        f"Line of scrimmage (offense's ball): {format_line_of_scrimmage(state.offense, state.field)}.",
    ]


def _punt_thrower_line(state: GameState | None) -> list[str]:
    if state is None:
        return []
    o = state.offense
    return [
        f"Thrower: {team_display_name(o)} is punting — the punter uses the punt throw.",
        f"Line of scrimmage: {format_line_of_scrimmage(o, state.field)}.",
    ]


def kickoff_instructions(rules: RuleSet, state: GameState | None = None) -> str:
    tm = rules.throw_markers
    km = rules.kickoff.kickoff_yard_multiplier
    lines = [
        "Kickoff (FootballDartsRules.pdf)",
        "",
        *_kickoff_thrower_line(state),
        "",
        tm.kickoff_line,
        "",
        f"Numbered wedges: yardage is based on the dart number ×{km} where the PDF says so; ignore doubles/triples on the kick dart unless a return dart applies.",
        "",
        *format_spot_band_lines(rules.kickoff.bands, "Numbered wedge outcomes (simplified in app):"),
        "",
        "Green bull (PDF): receiving-team fumble — kicking team recovers at opponent 35 (automated).",
        "Red bull (PDF): receiving-team fumble — touchdown for the kicking team (automated to PAT).",
        "Other kickoff branches (return dart, 15–13 run-out option, etc.) follow the PDF; not all are simulated.",
    ]
    return "\n".join(lines)


def scrimmage_offense_instructions(rules: RuleSet, state: GameState | None = None, play_label: str = "Offense") -> str:
    sc = rules.scrimmage
    tm = rules.throw_markers
    lines = [
        f"{play_label} (FootballDartsRules.pdf)",
        "",
        *_offense_thrower_line(state),
        "",
        tm.offense_line,
        "",
    ]
    if sc.use_pdf_segment_yards:
        lines += [
            f"Base yards = wedge number ({sc.segment_min}–{sc.segment_max}) ×1. "
            f"Double ring: ×{sc.double_multiplier}. Triple ring: ×{sc.triple_multiplier}.",
            "",
            "Green/red bull on offense: turnover, return yardage, and nullify rules are in the PDF — not automated here; resolve manually if you hit a bull.",
        ]
    else:
        lines += [
            f"Single: base yards from the wedge table. Double ring: ×{sc.double_multiplier}. "
            f"Triple ring: ×{sc.triple_multiplier}.",
            "",
            *format_scrimmage_yard_lines(sc.offense_yards, "Base yards by wedge:"),
            "",
            f"If you hit the green bull, rules may map to wedge {sc.bull_green_segment}; "
            f"red bull to wedge {sc.bull_red_segment} (legacy table mode).",
        ]
    lines += [
        "",
        "If you hit the triple ring, say whether it was the inner (smaller) or outer (larger) treble.",
    ]
    return "\n".join(lines)


def scrimmage_defense_instructions(rules: RuleSet, state: GameState | None = None) -> str:
    sc = rules.scrimmage
    tm = rules.throw_markers
    lines = [
        "Defense (FootballDartsRules.pdf)",
        "",
        *_defense_thrower_line(state),
        "",
        tm.defense_line,
        "",
    ]
    if sc.use_pdf_segment_yards:
        lines += [
            f"Defense yards = wedge number ({sc.segment_min}–{sc.segment_max}) ×1. Ignore doubles and triples for yardage.",
            "",
            "Green/red bull on defense: nullify and turnover rules are in the PDF — not automated here.",
        ]
    else:
        lines += [
            "Defense yards come from the wedge table (double/triple ignored for yardage but can be logged).",
            "",
            *format_scrimmage_yard_lines(sc.defense_yards, "Defense yards by wedge:"),
            "",
            f"Green bull → wedge {sc.bull_green_segment}; red bull → wedge {sc.bull_red_segment}.",
        ]
    return "\n".join(lines)


def punt_instructions(rules: RuleSet, state: GameState | None = None) -> str:
    tm = rules.throw_markers
    lines = [
        "Punt (FootballDartsRules.pdf)",
        "",
        *_punt_thrower_line(state),
        "",
        tm.punt_line,
        "",
        *format_spot_band_lines(rules.punt.bands, "Punting team — wedge outcomes (simplified spot in app):"),
        "",
        "Green/red bull on a punt: fake punt, block, and recovery rules are in the PDF — not automated here.",
        "Block attempt and return dart (when allowed) are not simulated in this app.",
    ]
    return "\n".join(lines)


def field_goal_instructions(state: GameState, rules: RuleSet) -> str:
    tm = rules.throw_markers
    dist = abs(state.field.goal_yard - state.field.scrimmage_line)
    o = state.offense
    return "\n".join(
        [
            "Field goal (FootballDartsRules.pdf)",
            "",
            f"Kicker side: {team_display_name(o)} attempts the field goal.",
            f"Line of scrimmage: {format_line_of_scrimmage(o, state.field)}.",
            "",
            tm.field_goal_line,
            "",
            f"Rough distance: {dist} yd to the goal posts (round up to nearest 10 yd per PDF).",
            f"PDF: attempts only on 3rd or 4th down unless last play of half or game; "
            f"60-yard tries only from your own 40–49 yard line; max kick {rules.field_goal.max_distance_yards} yd here.",
            f"If missed or no good: opponent takes over at previous LOS + {rules.field_goal.miss_spot_offset_yards} yd (engine).",
            "FG circle, triple goal post, blocks, and fakes follow the PDF — not fully automated.",
        ]
    )


def pat_instructions(rules: RuleSet, state: GameState) -> str:
    tm = rules.throw_markers
    o = state.offense
    return "\n".join(
        [
            "Extra point (FootballDartsRules.pdf)",
            "",
            f"Kicking team: {team_display_name(o)}.",
            "",
            tm.pat_line,
            "",
            "PDF: outside FG circle = no good; inside FG circle or triple of your team color = good; defense bulls can block per PDF.",
            "Record made or missed below to match your throw.",
        ]
    )


def two_point_instructions(rules: RuleSet, state: GameState) -> str:
    tm = rules.throw_markers
    o = state.offense
    return "\n".join(
        [
            "Two-point conversion (FootballDartsRules.pdf)",
            "",
            f"Offense: {team_display_name(o)}.",
            "",
            tm.two_point_line,
            "",
            "PDF: wedges 1–9 no good; 10–20 good; bulls and defense per PDF.",
            "Record good or no good below to match your throw.",
        ]
    )
