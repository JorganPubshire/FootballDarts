"""Human-readable dart outcome tables for the CLI (driven by loaded rules)."""

from __future__ import annotations

from dart_football.display.formatting import format_line_of_scrimmage, opponent, team_display_name
from dart_football.engine.state import GameState
from dart_football.rules.schema import KickoffBand, RuleSet, ScrimmageYardBand


def _sorted_seg_str(segments: frozenset[int]) -> str:
    return ", ".join(str(x) for x in sorted(segments))


def _kickoff_field_outcome_prefix(segments: frozenset[int]) -> str:
    """Lead-in for standard kickoff field bands (segments 1–5 vs 6–8)."""
    if not segments:
        return ""
    if all(1 <= s <= 5 for s in segments):
        return "Ball kicked out of bounds. "
    if all(6 <= s <= 8 for s in segments):
        return "Kicked short of landing zone. "
    return ""


def _kickoff_touchback_outcome_prefix(segments: frozenset[int]) -> str:
    """Lead-in for kickoff touchback when the ball leaves the end zone with no return (e.g. 16–20)."""
    if not segments:
        return ""
    if all(16 <= s <= 20 for s in segments):
        return "Out of end zone, no return. "
    return ""


def format_spot_band_lines(
    bands: tuple[KickoffBand, ...],
    header: str,
    *,
    kickoff_field_prefixes: bool = False,
) -> list[str]:
    lines = [header, ""]
    for b in bands:
        segs = _sorted_seg_str(b.segments)
        if b.kind == "touchback":
            assert b.touchback_line is not None
            tpre = _kickoff_touchback_outcome_prefix(b.segments) if kickoff_field_prefixes else ""
            if b.allow_runout_choice:
                lines.append(
                    f"  Segments {segs}: {tpre}receiver chooses ball at own {b.touchback_line} "
                    "or run out from the goal line."
                )
            else:
                lines.append(f"  Segments {segs}: {tpre}1st & 10 at own {b.touchback_line}.")
        elif b.kind == "field":
            assert b.field_yard_from_receiving_goal is not None
            pre = _kickoff_field_outcome_prefix(b.segments) if kickoff_field_prefixes else ""
            lines.append(
                f"  Segments {segs}: {pre}1st & 10 at own {b.field_yard_from_receiving_goal}."
            )
        elif b.kind == "wedge_times":
            assert b.multiplier is not None
            if kickoff_field_prefixes:
                if b.requires_return_dart:
                    lines.append(
                        f"  Segments {segs}: wedge ×{b.multiplier} = yards from the kick tee toward the "
                        "kicker's scoring goal (Red kicker toward the Red goal, Green kicker toward the Green goal); "
                        "possession flips to the receiver at that spot, then mandatory return dart."
                    )
                else:
                    lines.append(
                        f"  Segments {segs}: wedge ×{b.multiplier} = yards from the tee toward the kicker's "
                        "scoring goal; ball spotted for the receiver (no return dart in this band)."
                    )
            elif b.requires_return_dart:
                lines.append(
                    f"  Segments {segs}: {b.multiplier}x yards, receiver gets a return dart."
                )
            else:
                lines.append(f"  Segments {segs}: {b.multiplier}x yards.")
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
    out = [
        f"Thrower: {team_display_name(k)} is the kickoff kicker — only that player throws this dart.",
    ]
    if state.offense == k:
        out.append(f"Ball at kickoff tee: {format_line_of_scrimmage(k, state.field)}.")
    return out


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
        f"Thrower: {team_display_name(d)}",
        f"Line of scrimmage: {format_line_of_scrimmage(state.offense, state.field)}.",
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
        f"Numbered wedges (×{km} bands): travel yards from the kickoff tee toward the kicker's scoring goal "
        "(the end that team attacks). Possession switches to the receiving team at the resulting spot before "
        "any return dart. Ignore doubles/triples on the kick dart unless a return dart applies.",
        "",
        *format_spot_band_lines(
            rules.kickoff.bands,
            "Numbered wedge spots:",
            kickoff_field_prefixes=True,
        ),
        "",
        "Green bull: receiving-team fumble — kicking team recovers at opponent 35 (handled here).",
        "Red bull: receiving-team fumble — touchdown for the kicking team.",
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
        "  Wedges 1–12: +12 yards.",
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


def scrimmage_offense_instructions(
    rules: RuleSet, state: GameState | None = None, play_label: str = "Offense"
) -> str:
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
            f"Numbered wedge: base yards = wedge number ({sc.segment_min}–{sc.segment_max}) ×1. "
            f"Double ring: ×{sc.double_multiplier}. Triple ring: ×{sc.triple_multiplier}. "
            "Defense then throws; outcomes depend on both darts (see defense help).",
            "",
            f"Green bull: counts as wedge {sc.bull_green_segment} ×1 for offense yards (no double/triple on the bull). "
            "Defense still throws; numbered defense has no effect; green defense = no gain at LOS; "
            "red defense = turnover at the line of scrimmage.",
            "",
            "Red bull: 0 offensive yards; defense still throws. Numbered and green defense have no effect; "
            "red defense = no gain at LOS (no defensive TD).",
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
        kind = (
            getattr(state, "scrimmage_pending_offense_kind", "none")
            if state is not None
            else "none"
        )
        lines += [
            f"Defense wedge yardage uses the wedge number ({sc.segment_min}–{sc.segment_max}) ×1 only — "
            "ignore doubles and triples for yards.",
            "",
        ]
        if kind == "wedge":
            lines += [
                "Offense hit a numbered wedge.",
                "• Numbered wedge: subtract your wedge from their offensive yards (net gain, first down, TD, etc.).",
                "• Green bull: strip — you will throw another numbered wedge only. "
                "If its board color matches the offense wedge color: they get full offensive yards, then you take over "
                "(or they score a TD if the gain reaches the goal). If colors differ: turnover at the line of scrimmage.",
                "• Red bull: defensive touchdown.",
            ]
        elif kind == "green":
            lines += [
                "Offense hit the green bull.",
                "• Numbered wedge: no effect (no yardage change).",
                "• Green bull: no gain; ball stays at the line of scrimmage; play ends (next down).",
                "• Red bull: turnover at the line of scrimmage.",
            ]
        elif kind == "red":
            lines += [
                "Offense hit the red bull (0 yards).",
                "• Numbered wedge or green bull: no effect.",
                "• Red bull: no gain; ball at the line of scrimmage; play ends (next down).",
            ]
        else:
            lines += [
                "After offense numbered wedge: your wedge offsets theirs; green bull = strip dart next; red = defensive TD.",
                "After offense green bull: your wedge is ignored; green = LOS; red = turnover at LOS.",
                "After offense red bull: wedge/green ignored; red = LOS, no defensive TD.",
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


def scrimmage_strip_instructions(rules: RuleSet, state: GameState | None = None) -> str:
    tm = rules.throw_markers
    eff = state.scrimmage_pending_offense_eff_segment if state is not None else None
    off_y = state.scrimmage_pending_offense_yards if state is not None else None
    head = [
        "Strip dart (after defense green bull vs offense numbered wedge)",
        "",
        *_defense_thrower_line(state),
        "",
        tm.defense_line,
        "",
        "Enter a numbered wedge only (no bull, no double/triple for this throw).",
        "Board colors alternate around the wire; two wedges are the same color if they match that alternating pattern.",
    ]
    if eff is not None and off_y is not None:
        head += [
            "",
            f"Offense wedge (for color match): {eff}. Pending offensive yards if strip matches: {off_y}.",
        ]
    head += [
        "",
        f"Match: full {off_y or '…'} yd gain applies, then defense takes over (or offense TD if the ball crosses the goal).",
        "No match: turnover at the line of scrimmage (no offensive yards from this play).",
    ]
    return "\n".join(head)


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
        "Green bull: fake punt — no gain; ball stays at the line of scrimmage and the down advances "
        "(turnover on downs if that was 4th down).",
        "Red bull: blocked punt — defense takes over at the line of scrimmage.",
    ]
    return "\n".join(lines)


def field_goal_offense_dart_instructions(state: GameState, rules: RuleSet) -> str:
    tm = rules.throw_markers
    dist = abs(state.field.goal_yard - state.field.scrimmage_line)
    o = state.offense
    return "\n".join(
        [
            "Field goal — kicker's dart",
            "",
            f"Kicker: {team_display_name(o)}.",
            f"Line of scrimmage: {format_line_of_scrimmage(o, state.field)}.",
            "",
            tm.field_goal_line,
            "",
            f"Rough kick distance: {dist} yd (round up to nearest 10 yd). "
            f"Max {rules.field_goal.max_distance_yards} yd; 60-yard tries only from own 40–49.",
            "",
            "Offense dart (then defense always throws unless offense red bull):",
            "  • Numbered wedge inside the triple ring (single/double between double ring and triple, not on triple): "
            "would be good (+3) if in range — then defense.",
            "  • Numbered wedge outside the triple ring: would miss — turnover at LOS + "
            f"{rules.field_goal.miss_spot_offset_yards} if it stands — then defense.",
            "  • On the triple ring (triple bed): would be good if wedge board color matches kicker's team, else miss — then defense.",
            "  • Green bull: choose real kick (then defense) or fake (yardage dart, no defense on that throw, then 1st & 10, then defense).",
            "  • Red bull: touchdown for the kicking team (+6) — no defense dart.",
            "",
            "Defense dart (after offense, when required): green bull blocks (opponent ball at LOS + "
            f"{rules.field_goal.miss_spot_offset_yards}); red bull blocks for a defensive touchdown. "
            "Numbered wedge / ring detail: log if you like — often no extra effect.",
        ]
    )


def field_goal_green_choice_instructions(state: GameState, rules: RuleSet) -> str:
    o = state.offense
    return "\n".join(
        [
            "Field goal — green bull",
            "",
            f"Kicker: {team_display_name(o)}.",
            "",
            "Choose a real field goal attempt (defense still throws to try to block) "
            "or a fake (one offensive yardage dart using normal scrimmage wedge rules, no defense on that dart; "
            "then 1st & 10, then defense).",
            "",
            "On the fake, defense green bull stops the play 1 yard short of the first-down line or at your own 11, "
            "whichever leaves the ball further from the goal you are driving toward. "
            "Defense red bull puts the ball back at the original line of scrimmage.",
        ]
    )


def field_goal_fake_offense_instructions(state: GameState, rules: RuleSet) -> str:
    o = state.offense
    lines = [
        "Fake field goal — offense yardage dart",
        "",
        f"Offense: {team_display_name(o)}.",
        "",
        "Same wedge rules as a normal scrimmage offensive dart (including doubles/triples when your rules use wedge numbers). "
        "No separate defense dart for this throw.",
    ]
    if rules.scrimmage.use_wedge_number_yards:
        lines.extend(
            [
                "",
                "Green bull: wedge number yards. Red bull: no gain from this dart.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "This rules file does not use wedge-number scrimmage yards — configure use_wedge_number_yards to run a fake FG.",
            ]
        )
    return "\n".join(lines)


def field_goal_defense_instructions(state: GameState, rules: RuleSet) -> str:
    d = opponent(state.offense)
    pending = state.fg_pending_outcome
    extra = ""
    if pending == "good":
        extra = "If your dart has no special effect, the field goal is good (+3) and there will be a kickoff."
    elif pending == "miss":
        extra = (
            "If your dart has no special effect, the kick is no good — opponent at LOS + "
            f"{rules.field_goal.miss_spot_offset_yards}."
        )
    elif pending == "fake_resolved":
        extra = "If your dart has no special effect, the fake stays at the spot after the yardage dart (1st & 10 already set)."
    return "\n".join(
        [
            "Field goal — defense dart",
            "",
            f"Defense throws: {team_display_name(d)}.",
            "",
            "Green bull: block — effects depend on whether this was a real try or a fake (see on-screen result).",
            "Red bull: block — defensive touchdown on a real try; on a fake, ball at the line of scrimmage.",
            "Numbered wedge: choose ring (single / double / triple) for the record; it may not change the outcome.",
            "",
            extra,
        ]
    )


def field_goal_instructions(state: GameState, rules: RuleSet) -> str:
    """Alias for the kicker's first FG dart; kept for callers that expect one FG help block."""
    return field_goal_offense_dart_instructions(state, rules)


def safety_sequence_instructions(state: GameState, rules: RuleSet) -> str:
    k = state.safety_pending_kicker
    ks = team_display_name(k) if k is not None else "the team that was on offense"
    y = rules.safety.free_kick_own_yard
    return "\n".join(
        [
            "Safety",
            "",
            f"The defense has been awarded {rules.scoring.safety} point(s).",
            f"{ks} will free-kick next from their own {y}-yard line (same kickoff flow as after a score).",
            "Confirm when you are ready to set up the kickoff phase.",
        ]
    )


def overtime_start_instructions(state: GameState, rules: RuleSet) -> str:
    lines = [
        "Overtime",
        "",
        "Regulation ended tied. Record who won the overtime coin toss (same as opening toss).",
        "The winner then chooses kick or receive on the next screen.",
    ]
    if rules.overtime.template == "first_score":
        lines.extend(
            [
                "",
                "Sudden score: once the score is no longer tied, the game will end when you reach the kickoff phase "
                "(after any try after touchdown).",
            ]
        )
    return "\n".join(lines)


def extra_point_attempt_instructions(rules: RuleSet, state: GameState) -> str:
    tm = rules.throw_markers
    o = state.offense
    return "\n".join(
        [
            "Extra point",
            "",
            f"Kicking team: {team_display_name(o)}.",
            "",
            tm.extra_point_line,
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
