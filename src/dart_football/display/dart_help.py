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
            if b.allow_runout_choice:
                lines.append(
                    f"  Segments {segs}: receiver chooses ball at own {b.touchback_line} "
                    "or run out from the goal line (run-out dart in app)."
                )
            else:
                lines.append(f"  Segments {segs}: 1st & 10 at own {b.touchback_line}.")
        elif b.kind == "field":
            assert b.field_yard_from_receiving_goal is not None
            lines.append(f"  Segments {segs}: 1st & 10 at own {b.field_yard_from_receiving_goal}.")
        elif b.kind == "wedge_times":
            assert b.multiplier is not None
            if b.requires_return_dart:
                lines.append(
                    f"  Segments {segs}: spot uses wedge × {b.multiplier} yards (own field, clamped); "
                    "then mandatory return dart in app."
                )
            else:
                lines.append(
                    f"  Segments {segs}: spot uses wedge × {b.multiplier} yards (own field, clamped)."
                )
        elif b.kind == "wedge_times_penalty":
            assert b.multiplier is not None and b.penalty_yards is not None
            lines.append(
                f"  Segments {segs}: wedge × {b.multiplier} − {b.penalty_yards} yd penalty (punt band)."
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


def coin_toss_dart_instructions(rules: RuleSet) -> str:
    tm = rules.throw_markers
    lines = [
        "Coin toss — darts",
        "",
        "Start of play: the youngest player decides who is Red and who is Green (do that before this step).",
        "",
        tm.coin_toss_dart_line,
        "",
        "Order: oldest throws at the board first, then the youngest throws second.",
        "",
        "Throw from your floor yard marks. "
        "Compare both darts to see which landed closest to the center of the board (bull is closer than the number ring, etc.).",
        "",
        "Then say below whether Red or Green had the dart closest to the center.",
    ]
    return "\n".join(lines)


def _kickoff_thrower_line(state: GameState | None) -> list[str]:
    if state is None or state.kickoff_kicker is None:
        return [
            "Kickoff kicker missing from game state.",
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
        "Kickoff",
        "",
        *_kickoff_thrower_line(state),
        "",
        tm.kickoff_line,
        "",
        f"Numbered wedges: yardage uses dart number ×{km} where noted; ignore doubles/triples on the kick dart unless a return dart applies.",
        "",
        *format_spot_band_lines(rules.kickoff.bands, "Numbered wedge spots:"),
        "",
        "Green bull: receiving-team fumble — kicking team recovers at opponent 35 (handled here).",
        "Red bull: receiving-team fumble — touchdown for the kicking team (then PAT).",
        "Bands marked for run-out choice or mandatory return dart continue in the next phase after this kick.",
    ]
    return "\n".join(lines)


def kickoff_run_or_spot_instructions(rules: RuleSet, state: GameState) -> str:
    line = state.kickoff_pending_touchback_line
    recv = state.kickoff_receiver
    line_s = str(line) if line is not None else "?"
    recv_s = team_display_name(recv) if recv is not None else "receiving team"
    return "\n".join(
        [
            "Kickoff — touchback or run out",
            "",
            f"Receiving team: {recv_s}.",
            f"You may take the ball at your own {line_s} yard line, or run out from your goal line.",
            "If you run out, the next screen records the run-out dart (wedges 1–12: +25 yd; 13–20: wedge×2, ignore D/T; "
            "green bull: +50 yd; red bull: touchdown).",
            "",
            rules.throw_markers.kickoff_line,
        ]
    )


def kickoff_run_out_instructions(rules: RuleSet, state: GameState | None = None) -> str:
    lines = [
        "Run-out dart (from your goal line)",
        "",
    ]
    if state is not None and state.kickoff_receiver is not None:
        lines.append(f"Thrower: {team_display_name(state.kickoff_receiver)} — receiving team only.")
        lines.append("")
    lines += [
        "From your goal line toward the far goal:",
        "  Wedges 1–12: +25 yards.",
        "  Wedges 13–20: wedge number × 2 (ignore doubles and triples).",
        "  Green bull: +50 yards.",
        "  Red bull: touchdown (receiving team).",
        "",
        rules.throw_markers.kickoff_line,
    ]
    return "\n".join(lines)


def kickoff_return_instructions(rules: RuleSet, state: GameState | None = None) -> str:
    sc = rules.scrimmage
    lines = [
        "Kickoff return dart (from the kick spot)",
        "",
    ]
    if state is not None and state.kickoff_receiver is not None:
        lines.append(f"Thrower: {team_display_name(state.kickoff_receiver)} — receiving team only.")
        lines.append(f"Ball: {format_line_of_scrimmage(state.offense, state.field)}.")
        lines.append("")
    lines += [
        "From the current spot toward the far goal:",
        f"  Wedges 1–12: +12 yards.",
        f"  Wedges 13–20: wedge ×1, then ×{sc.double_multiplier} double / ×{sc.triple_multiplier} triple on D/T.",
        "  Green bull: +50 yards.",
        "  Red bull: touchdown (receiving team).",
        "",
        rules.throw_markers.kickoff_line,
    ]
    return "\n".join(lines)


def onside_kick_instructions(rules: RuleSet, state: GameState | None = None) -> str:
    head = "\n".join(
        [
            "Onside kick attempt",
            "",
            "Recovery, illegal touching, and follow-up throws aren't fully handled in this app.",
            "For this kick dart only, the ball is spotted with the same numbered-wedge table as a regular kickoff.",
            "",
            "— — —",
            "",
        ]
    )
    return head + kickoff_instructions(rules, state)


def scrimmage_offense_instructions(rules: RuleSet, state: GameState | None = None, play_label: str = "Offense") -> str:
    sc = rules.scrimmage
    tm = rules.throw_markers
    lines = [
        play_label,
        "",
        *_offense_thrower_line(state),
        "",
        tm.offense_line,
        "",
    ]
    if sc.use_wedge_number_yards:
        lines += [
            f"Base yards = wedge number ({sc.segment_min}–{sc.segment_max}) ×1. "
            f"Double ring: ×{sc.double_multiplier}. Triple ring: ×{sc.triple_multiplier}.",
            "",
            f"Green bull: yardage dart — counts as wedge {sc.bull_green_segment} ×1 (no double/triple on the bull); "
            "then the defense throws as usual.",
            "Red bull: turnover — defense takes over at the line of scrimmage (no defense dart for this play).",
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
        "Defense",
        "",
        *_defense_thrower_line(state),
        "",
        tm.defense_line,
        "",
    ]
    if sc.use_wedge_number_yards:
        lines += [
            f"Defense yards = wedge number ({sc.segment_min}–{sc.segment_max}) ×1. Ignore doubles and triples for yardage.",
            "",
            "Green bull: nullify — your wedge yards count as 0; offense keeps full offensive yards on the play.",
            "Red bull: turnover — your team takes the ball where the play ended (offense's forward yards). "
            "If that spot is a touchdown for the offense, the TD stands instead.",
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
        "Punt",
        "",
        *_punt_thrower_line(state),
        "",
        tm.punt_line,
        "",
        *format_spot_band_lines(rules.punt.bands, "Punting team — wedge spots:"),
        "",
        "Green/red bull on a punt: fake punt, block, and recovery aren't automated here.",
        "Block attempt and return dart (when allowed) aren't simulated in this app.",
    ]
    return "\n".join(lines)


def field_goal_instructions(state: GameState, rules: RuleSet) -> str:
    tm = rules.throw_markers
    dist = abs(state.field.goal_yard - state.field.scrimmage_line)
    o = state.offense
    return "\n".join(
        [
            "Field goal",
            "",
            f"Kicker side: {team_display_name(o)} attempts the field goal.",
            f"Line of scrimmage: {format_line_of_scrimmage(o, state.field)}.",
            "",
            tm.field_goal_line,
            "",
            f"Rough distance: {dist} yd to the goal posts (round up to nearest 10 yd).",
            "Attempts only on 3rd or 4th down unless last play of half or game; "
            f"60-yard tries only from your own 40–49 yard line; max kick {rules.field_goal.max_distance_yards} yd here.",
            f"If missed or no good: opponent takes over at previous LOS + {rules.field_goal.miss_spot_offset_yards} yd.",
            "FG circle, triple goal post, blocks, and fakes aren't fully automated.",
        ]
    )


def pat_instructions(rules: RuleSet, state: GameState) -> str:
    tm = rules.throw_markers
    o = state.offense
    return "\n".join(
        [
            "Extra point",
            "",
            f"Kicking team: {team_display_name(o)}.",
            "",
            tm.pat_line,
            "",
            "Outside FG circle = no good; inside FG circle or triple of your team color = good; defense bulls can block.",
            "Record made or missed below to match your throw.",
        ]
    )


def two_point_instructions(rules: RuleSet, state: GameState) -> str:
    tm = rules.throw_markers
    o = state.offense
    return "\n".join(
        [
            "Two point conversion",
            "",
            f"Offense: {team_display_name(o)}.",
            "",
            tm.two_point_line,
            "",
            "Wedges 1–9 no good; 10–20 good; bulls and defense throws — resolve at the board.",
            "Record good or no good below to match your throw.",
        ]
    )
