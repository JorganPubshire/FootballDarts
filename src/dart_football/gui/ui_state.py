"""Build API payloads for the graphical dashboard (actions, help text, field)."""

from __future__ import annotations

from typing import Any

from dart_football.cli.play_ui.shared import field_goal_attempt_allowed, field_goal_choice_available
from dart_football.display import dart_help
from dart_football.display.field_visual import gui_field_graphic_spec
from dart_football.engine.event_codec import encode_game_state
from dart_football.engine.phases import Phase
from dart_football.engine.session import GameSession
from dart_football.engine.state import GameState, TeamId


def _defense_team(state: GameState) -> TeamId:
    return TeamId.GREEN if state.offense is TeamId.RED else TeamId.RED


def _with_accent(action: dict[str, Any], team: TeamId | None) -> dict[str, Any]:
    """Tag a play action button with red/green/neutral for GUI styling."""
    out = dict(action)
    out["accent"] = "neutral" if team is None else team.value
    return out


def _meta_list(phase: Phase) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if phase not in (Phase.PRE_GAME_COIN_TOSS, Phase.GAME_OVER):
        out.append({"id": "timeout", "label": "Timeout"})
    if phase is not Phase.PRE_GAME_COIN_TOSS:
        out.extend(
            [
                {"id": "undo", "label": "Undo"},
                {"id": "save", "label": "Save"},
                {"id": "history", "label": "History"},
            ]
        )
    out.append({"id": "quit", "label": "Exit"})
    return out


def _phase_rules_blurb(rules: Any, state: Any, phase: Phase) -> str:
    try:
        if phase is Phase.PRE_GAME_COIN_TOSS:
            return (
                "Choose Darts on board or Simulated flip in Play. For darts, each side taps where their dart "
                "landed; closest to the board center wins (wedge does not matter).\n\n"
                + dart_help.coin_toss_dart_instructions(rules)
            )
        if phase is Phase.CHOOSE_KICK_OR_RECEIVE:
            return "Winner chooses whether to kick off or receive."
        if phase in (Phase.KICKOFF_KICK, Phase.ONSIDE_KICK):
            return dart_help.kickoff_instructions(rules, state)
        if phase is Phase.KICKOFF_RUN_OR_SPOT:
            return dart_help.kickoff_run_or_spot_instructions(rules, state)
        if phase is Phase.KICKOFF_RUN_OUT_DART:
            return dart_help.kickoff_run_out_instructions(rules, state)
        if phase is Phase.KICKOFF_RETURN_DART:
            return dart_help.kickoff_return_instructions(rules, state)
        if phase is Phase.SCRIMMAGE_OFFENSE:
            return dart_help.scrimmage_offense_instructions(rules, state)
        if phase is Phase.SCRIMMAGE_DEFENSE:
            return dart_help.scrimmage_defense_instructions(rules, state)
        if phase is Phase.SCRIMMAGE_STRIP_DART:
            return dart_help.scrimmage_strip_instructions(rules, state)
        if phase is Phase.FOURTH_DOWN_DECISION:
            return "Fourth down: scrimmage play, punt, or field goal when allowed."
        if phase is Phase.FIELD_GOAL_OFFENSE_DART:
            return dart_help.field_goal_offense_dart_instructions(state, rules)
        if phase is Phase.FIELD_GOAL_GREEN_CHOICE:
            return dart_help.field_goal_green_choice_instructions(state, rules)
        if phase is Phase.FIELD_GOAL_FAKE_OFFENSE:
            return dart_help.field_goal_fake_offense_instructions(state, rules)
        if phase is Phase.FIELD_GOAL_DEFENSE:
            return dart_help.field_goal_defense_instructions(state, rules)
        if phase is Phase.PUNT_ATTEMPT:
            return dart_help.punt_instructions(rules, state)
        if phase is Phase.AFTER_TOUCHDOWN_CHOICE:
            return "Choose extra point (1) or two-point conversion (2)."
        if phase is Phase.EXTRA_POINT_ATTEMPT:
            return dart_help.extra_point_attempt_instructions(rules, state)
        if phase is Phase.TWO_POINT_ATTEMPT:
            return dart_help.two_point_instructions(rules, state)
        if phase is Phase.SAFETY_SEQUENCE:
            return dart_help.safety_sequence_instructions(state, rules)
        if phase is Phase.OVERTIME_START:
            return dart_help.overtime_start_instructions(state, rules)
    except Exception:
        return ""
    return ""


def build_ui_payload(session: GameSession) -> dict[str, Any]:
    state, phase = session.current_state_phase()
    rules = session.rules
    field_graphic = gui_field_graphic_spec(state, phase)

    actions: list[dict[str, Any]] = []
    board: dict[str, Any] | None = None

    if phase is Phase.PRE_GAME_COIN_TOSS:
        actions = [
            _with_accent(
                {
                    "id": "coin_toss_darts",
                    "label": "Coin toss — darts on board",
                    "coin_toss": "darts",
                },
                None,
            ),
            _with_accent(
                {
                    "id": "coin_toss_sim",
                    "label": "Coin toss — simulated flip",
                    "coin_toss": "simulated",
                },
                None,
            ),
        ]
    elif phase is Phase.CHOOSE_KICK_OR_RECEIVE:
        chooser = state.coin_toss_winner
        actions = [
            _with_accent(
                {"id": "kr_kick", "label": "Kick off", "event": {"type": "ChooseKickOrReceive", "kick": True}},
                chooser,
            ),
            _with_accent(
                {"id": "kr_recv", "label": "Receive", "event": {"type": "ChooseKickOrReceive", "kick": False}},
                chooser,
            ),
        ]
    elif phase is Phase.KICKOFF_KICK:
        kicker = state.kickoff_kicker
        if not state.kickoff_type_selected:
            actions = [
                _with_accent(
                    {"id": "kk_reg", "label": "Regular kickoff", "event": {"type": "ChooseKickoffKind", "onside": False}},
                    kicker,
                ),
                _with_accent(
                    {"id": "kk_on", "label": "Onside kick", "event": {"type": "ChooseKickoffKind", "onside": True}},
                    kicker,
                ),
            ]
        else:
            board = {"profile": "kickoff", "title": "Kickoff dart"}
            actions = [_with_accent({"id": "open_board", "label": "Record kickoff dart", "board": board}, kicker)]
    elif phase is Phase.ONSIDE_KICK:
        board = {"profile": "kickoff", "title": "Onside kick dart"}
        actions = [
            _with_accent(
                {"id": "open_board", "label": "Record onside kick", "board": board},
                state.kickoff_kicker,
            )
        ]
    elif phase is Phase.KICKOFF_RUN_OR_SPOT:
        line = state.kickoff_pending_touchback_line
        tb = f"Take ball at own {line}" if line is not None else "Take touchback"
        recv = state.kickoff_receiver
        actions = [
            _with_accent(
                {"id": "tb", "label": tb, "event": {"type": "ChooseKickoffTouchbackOrRun", "take_touchback": True}},
                recv,
            ),
            _with_accent(
                {
                    "id": "runout",
                    "label": "Run out from goal line",
                    "event": {"type": "ChooseKickoffTouchbackOrRun", "take_touchback": False},
                },
                recv,
            ),
        ]
    elif phase is Phase.KICKOFF_RUN_OUT_DART:
        board = {"profile": "kickoff_run_out", "title": "Run-out dart"}
        actions = [
            _with_accent(
                {"id": "open_board", "label": "Record run-out dart", "board": board},
                state.kickoff_receiver,
            )
        ]
    elif phase is Phase.KICKOFF_RETURN_DART:
        board = {"profile": "kickoff_return", "title": "Return dart"}
        actions = [
            _with_accent(
                {"id": "open_board", "label": "Record return dart", "board": board},
                state.kickoff_receiver,
            )
        ]
    elif phase is Phase.SCRIMMAGE_OFFENSE:
        off = state.offense
        actions = [
            _with_accent(
                {
                    "id": "off_scrim",
                    "label": "Scrimmage play",
                    "board": {"profile": "scrimmage_offense", "title": "Offense dart"},
                },
                off,
            )
        ]
        if state.downs.down >= 2:
            actions.append(
                _with_accent(
                    {"id": "fd_punt", "label": "Punt", "event": {"type": "FourthDownChoice", "kind": "punt"}},
                    off,
                )
            )
        if field_goal_choice_available(state, rules):
            actions.append(
                _with_accent(
                    {"id": "fd_fg", "label": "Field goal", "event": {"type": "FourthDownChoice", "kind": "field_goal"}},
                    off,
                )
            )
    elif phase is Phase.SCRIMMAGE_DEFENSE:
        board = {"profile": "scrimmage_defense", "title": "Defense dart"}
        actions = [
            _with_accent(
                {"id": "open_board", "label": "Record defense dart", "board": board},
                _defense_team(state),
            )
        ]
    elif phase is Phase.SCRIMMAGE_STRIP_DART:
        board = {"profile": "strip", "title": "Strip dart (wedge only)"}
        actions = [
            _with_accent(
                {"id": "open_board", "label": "Record strip dart", "board": board},
                _defense_team(state),
            )
        ]
    elif phase is Phase.FOURTH_DOWN_DECISION:
        fg_ok = field_goal_attempt_allowed(state, rules)
        off = state.offense
        actions = [
            _with_accent(
                {
                    "id": "fd_off",
                    "label": "Scrimmage play",
                    "board": {"profile": "scrimmage_offense", "title": "4th down — offense dart"},
                },
                off,
            ),
            _with_accent(
                {"id": "fd_punt", "label": "Punt", "event": {"type": "FourthDownChoice", "kind": "punt"}},
                off,
            ),
        ]
        if fg_ok:
            actions.append(
                _with_accent(
                    {"id": "fd_fg", "label": "Field goal", "event": {"type": "FourthDownChoice", "kind": "field_goal"}},
                    off,
                )
            )
    elif phase is Phase.FIELD_GOAL_OFFENSE_DART:
        board = {
            "profile": "field_goal_offense",
            "title": "Field goal — kicker dart",
            "needs_fg_zone": True,
        }
        actions = [_with_accent({"id": "open_board", "label": "Record FG dart", "board": board}, state.offense)]
    elif phase is Phase.FIELD_GOAL_GREEN_CHOICE:
        actions = [
            _with_accent(
                {"id": "fg_real", "label": "Real field goal", "event": {"type": "ChooseFieldGoalAfterGreen", "real_kick": True}},
                TeamId.GREEN,
            ),
            _with_accent(
                {"id": "fg_fake", "label": "Fake field goal", "event": {"type": "ChooseFieldGoalAfterGreen", "real_kick": False}},
                TeamId.GREEN,
            ),
        ]
    elif phase is Phase.FIELD_GOAL_FAKE_OFFENSE:
        board = {"profile": "field_goal_fake", "title": "Fake FG yardage dart"}
        actions = [_with_accent({"id": "open_board", "label": "Record fake FG dart", "board": board}, state.offense)]
    elif phase is Phase.FIELD_GOAL_DEFENSE:
        board = {"profile": "field_goal_defense", "title": "FG block dart"}
        actions = [
            _with_accent(
                {"id": "open_board", "label": "Record defense dart", "board": board},
                _defense_team(state),
            )
        ]
    elif phase is Phase.PUNT_ATTEMPT:
        board = {"profile": "punt", "title": "Punt"}
        actions = [_with_accent({"id": "open_board", "label": "Record punt dart", "board": board}, state.offense)]
    elif phase is Phase.AFTER_TOUCHDOWN_CHOICE:
        scorer = state.last_touchdown_team or state.offense
        actions = [
            _with_accent(
                {"id": "td_ep", "label": "Extra point (1 pt)", "event": {"type": "ChooseExtraPointOrTwo", "extra_point": True}},
                scorer,
            ),
            _with_accent(
                {"id": "td_2pt", "label": "Two-point conversion", "event": {"type": "ChooseExtraPointOrTwo", "extra_point": False}},
                scorer,
            ),
        ]
    elif phase is Phase.EXTRA_POINT_ATTEMPT:
        att = state.last_touchdown_team or state.offense
        actions = [
            _with_accent(
                {"id": "xpa_good", "label": "Good", "event": {"type": "ExtraPointOutcome", "good": True}},
                att,
            ),
            _with_accent(
                {"id": "xpa_bad", "label": "No good", "event": {"type": "ExtraPointOutcome", "good": False}},
                att,
            ),
        ]
    elif phase is Phase.TWO_POINT_ATTEMPT:
        att = state.last_touchdown_team or state.offense
        actions = [
            _with_accent(
                {"id": "tpc_good", "label": "Good", "event": {"type": "TwoPointOutcome", "good": True}},
                att,
            ),
            _with_accent(
                {"id": "tpc_bad", "label": "No good", "event": {"type": "TwoPointOutcome", "good": False}},
                att,
            ),
        ]
    elif phase is Phase.SAFETY_SEQUENCE:
        actions = [
            _with_accent(
                {
                    "id": "safety_go",
                    "label": "Continue to safety free kick",
                    "event": {"type": "ConfirmSafetyKickoff"},
                },
                state.safety_pending_kicker,
            ),
        ]
    elif phase is Phase.OVERTIME_START:
        actions = [
            _with_accent(
                {
                    "id": "coin_toss_darts",
                    "label": "OT toss — darts on board",
                    "coin_toss": "darts",
                },
                None,
            ),
            _with_accent(
                {
                    "id": "coin_toss_sim",
                    "label": "OT toss — simulated flip",
                    "coin_toss": "simulated",
                },
                None,
            ),
        ]
    elif phase is Phase.GAME_OVER:
        actions = []

    log = [r.effects_summary for r in session.records[-25:]]
    rules_blurb = _phase_rules_blurb(rules, state, phase)

    return {
        "phase": phase.value,
        "state": encode_game_state(state),
        "field_graphic": field_graphic,
        "rules_path": session.rules_path,
        "ruleset_id": rules.ruleset_id,
        "ruleset_version": rules.ruleset_version,
        "load_warnings": list(session.load_warnings),
        "actions": actions,
        "meta": _meta_list(phase),
        "rules_help": rules_blurb,
        "play_log": log,
        "scrimmage": {
            "segment_min": rules.scrimmage.segment_min,
            "segment_max": rules.scrimmage.segment_max,
            "bull_green": rules.scrimmage.bull_green_segment,
            "bull_red": rules.scrimmage.bull_red_segment,
        },
        "kickoff": {
            "segment_min": rules.kickoff.segment_min,
            "segment_max": rules.kickoff.segment_max,
        },
        "punt": {
            "segment_min": rules.punt.segment_min,
            "segment_max": rules.punt.segment_max,
        },
    }
