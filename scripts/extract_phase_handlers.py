"""One-off helper: split transition_core phase blocks into handler functions. Run from repo root."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TC = ROOT / "src/dart_football/engine/transitions/transition_core.py"

# Phase enum name -> python function name
NAMES = {
    "PRE_GAME_COIN_TOSS": "handle_pre_game_coin_toss",
    "CHOOSE_KICK_OR_RECEIVE": "handle_choose_kick_or_receive",
    "KICKOFF_KICK": "handle_kickoff_kick",
    "ONSIDE_KICK": "handle_onside_kick",
    "KICKOFF_RUN_OR_SPOT": "handle_kickoff_run_or_spot",
    "KICKOFF_RUN_OUT_DART": "handle_kickoff_run_out_dart",
    "KICKOFF_RETURN_DART": "handle_kickoff_return_dart",
    "AFTER_TOUCHDOWN_CHOICE": "handle_after_touchdown_choice",
    "EXTRA_POINT_ATTEMPT": "handle_extra_point_attempt",
    "TWO_POINT_ATTEMPT": "handle_two_point_attempt",
    "FOURTH_DOWN_DECISION": "handle_fourth_down_decision",
    "FIELD_GOAL_OFFENSE_DART": "handle_field_goal_offense_dart",
    "FIELD_GOAL_GREEN_CHOICE": "handle_field_goal_green_choice",
    "FIELD_GOAL_FAKE_OFFENSE": "handle_field_goal_fake_offense",
    "FIELD_GOAL_DEFENSE": "handle_field_goal_defense",
    "PUNT_ATTEMPT": "handle_punt_attempt",
    "SCRIMMAGE_OFFENSE": "handle_scrimmage_offense",
    "SCRIMMAGE_DEFENSE": "handle_scrimmage_defense",
    "SCRIMMAGE_STRIP_DART": "handle_scrimmage_strip_dart",
    "SAFETY_SEQUENCE": "handle_safety_sequence",
    "OVERTIME_START": "handle_overtime_start",
    "GAME_OVER": "handle_game_over",
}

PHASE_LINE = re.compile(r"^    if phase is Phase\.(\w+):\s*$")


def main() -> None:
    lines = TC.read_text().splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith("def transition_core("):
            start = i
            break
    assert start is not None
    body_start = start + 1
    # Skip timeout block (lines until first `if phase is Phase`)
    i = body_start
    while i < len(lines) and not PHASE_LINE.match(lines[i]):
        i += 1
    phase_lines: list[tuple[str, int]] = []
    j = i
    while j < len(lines):
        m = PHASE_LINE.match(lines[j])
        if m:
            phase_lines.append((m.group(1), j))
        j += 1

    phase_with_ends: list[tuple[str, int, int]] = []
    for idx, (name, start_ln) in enumerate(phase_lines):
        if idx + 1 < len(phase_lines):
            end_ln = phase_lines[idx + 1][1]
        else:
            end_ln = start_ln + 1
            while end_ln < len(lines) and not lines[end_ln].strip().startswith(
                'return TransitionError(f"unhandled phase'
            ):
                end_ln += 1
        phase_with_ends.append((name, start_ln, end_ln))
    phase_lines = phase_with_ends

    out: list[str] = []
    out.append('"""Per-phase transition handlers (dispatched from transition_core)."""')
    out.append("from __future__ import annotations")
    out.append("")
    out.append("from dataclasses import replace")
    out.append("")
    out.append("from dart_football.display.formatting import format_possession_summary, opponent")
    out.append("from dart_football.engine.events import (")
    out.append("    ConfirmSafetyKickoff,")
    out.append("    ChooseFieldGoalAfterGreen,")
    out.append("    ChooseKickoffKind,")
    out.append("    ChooseKickoffTouchbackOrRun,")
    out.append("    ChooseKickOrReceive,")
    out.append("    ChooseExtraPointOrTwo,")
    out.append("    CoinTossWinner,")
    out.append("    Event,")
    out.append("    ExtraPointOutcome,")
    out.append("    FieldGoalDefenseDart,")
    out.append("    FieldGoalFakeOffenseDart,")
    out.append("    FieldGoalOffenseDart,")
    out.append("    FieldGoalOutcome,")
    out.append("    FourthDownChoice,")
    out.append("    KickoffKick,")
    out.append("    KickoffReturnKick,")
    out.append("    KickoffRunOutKick,")
    out.append("    PuntKick,")
    out.append("    ScrimmageDefense,")
    out.append("    ScrimmageOffense,")
    out.append("    ScrimmageStripDart,")
    out.append("    TwoPointOutcome,")
    out.append(")")
    out.append("from dart_football.engine.phases import Phase")
    out.append("from dart_football.engine.state import DownAndDistance, GameState")
    out.append("from dart_football.rules.schema import RuleSet")
    out.append("")
    out.append("from dart_football.engine.transitions.clock_and_timeouts import (")
    out.append("    advance_clock_for_scrimmage_play,")
    out.append(")")
    out.append("from dart_football.engine.transitions.field_geometry import (")
    out.append("    advance_field_position,")
    out.append("    defensive_takeover_at_spot,")
    out.append("    field_from_spot_band,")
    out.append("    field_spot_from_own_yard,")
    out.append("    is_touchdown_field,")
    out.append("    kickoff_tee_down_and_distance,")
    out.append("    kickoff_tee_field_position,")
    out.append("    match_spot_band_for_segment,")
    out.append("    match_scrimmage_yard_band,")
    out.append("    receiver_goal_line_field_position,")
    out.append("    turnover_on_downs_state,")
    out.append("    yards_to_goal_line,")
    out.append(")")
    out.append("from dart_football.engine.transitions.field_goal_and_punt import (")
    out.append("    fake_field_goal_defense_green_field,")
    out.append("    field_after_missed_field_goal,")
    out.append("    field_goal_fake_yards_from_dart,")
    out.append("    field_goal_sequence_clear_fields,")
    out.append("    fg_kick_range_error_or_none,")
    out.append("    first_down_line_yard,")
    out.append("    sixty_yard_field_goal_line_ok,")
    out.append("    team_field_goal_board_parity,")
    out.append(")")
    out.append("from dart_football.engine.transitions.kickoff_resolution import (")
    out.append("    apply_kickoff_dart,")
    out.append("    finish_kickoff_return_touchdown,")
    out.append("    finish_kickoff_to_scrimmage,")
    out.append("    return_dart_net_yards,")
    out.append("    run_out_net_yards,")
    out.append(")")
    out.append("from dart_football.engine.transitions.scoring_setup import (")
    out.append("    setup_kickoff_after_score,")
    out.append("    setup_safety_free_kick,")
    out.append("    state_after_touchdown,")
    out.append(")")
    out.append("from dart_football.engine.transitions.scrimmage_resolution import (")
    out.append("    defense_ring_note,")
    out.append("    defensive_touchdown_after_offense_yards,")
    out.append("    effective_segment_with_bull,")
    out.append("    finish_scrimmage_net_play,")
    out.append("    no_gain_advance_down,")
    out.append("    wedge_board_color_parity,")
    out.append("    wedge_board_colors_match,")
    out.append(")")
    out.append("from dart_football.engine.transitions.types import TransitionError, TransitionOk")
    out.append("")

    for name, start_ln, end_ln in phase_lines:
        fn = NAMES[name]
        block = lines[start_ln + 1 : end_ln]
        # Drop leading 4 spaces from each line in block
        dedented: list[str] = []
        for bl in block:
            if bl.startswith("    "):
                dedented.append(bl[4:])
            else:
                dedented.append(bl)
        out.append("")
        out.append(f"def {fn}(")
        out.append("    state: GameState,")
        out.append("    event: Event,")
        out.append("    rules: RuleSet,")
        out.append(") -> TransitionOk | TransitionError:")
        for bl in dedented:
            out.append(bl)

    dest = ROOT / "src/dart_football/engine/transitions/phase_handlers.py"
    dest.write_text("\n".join(out) + "\n")
    print("Wrote", dest, "handlers:", len(phase_lines))


if __name__ == "__main__":
    main()
