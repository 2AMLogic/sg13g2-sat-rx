"""CI-control tests for ``ci_assert`` (issue #122).

Reduced-subset coherence, deck shape and every assertion path, all on the
closed-form fake logs of ``fakes.py`` -- no simulator, PDK or network. What
needs the real pinned ngspice (the one-process run itself) is exercised by
``python3 sim/lna-linearity/ci_assert.py`` in the sim-smoke CI job.

    python3 -m pytest sim/lna-linearity/tests -q
"""

from __future__ import annotations

import re

import pytest

import analysis as A
import ci_assert as CIA
import fakes
import linearity as L

RED = CIA.reduced_plan()
C = RED["controls"]
INFO = {"path": "/fake/ngspice", "version": "ngspice-46", "major": 46}


def fake_combined_log(**kw) -> str:
    return (fakes.fake_log(RED, "control_two", a1=C["a1"], a3=C["a3"], floor_v=1e-9, **kw)
            + fakes.fake_log(RED, "control_one", a1=C["a1"], a3=C["a3"], floor_v=1e-9, **kw))


# ---- the reduced subset is declared, coherent and estimator-sufficient ------


def test_reduced_subset_matches_its_declaration_and_inherits_coherence():
    assert L.sweep_pins(RED, "two") == pytest.approx([-50.0 + i for i in range(15)])
    assert L.sweep_pins(RED, "one") == pytest.approx([-48.0 + 2 * i for i in range(17)])
    fleet = L.load_plan(CIA.PLAN_PATH)
    for kind in ("two", "one"):
        assert RED["sweep"][kind]["step_db"] == fleet["sweep"][kind]["step_db"]
        assert RED["sweep"][kind]["stop_dbm"] == fleet["sweep"][kind]["stop_dbm"]
    assert len(L.sweep_pins(RED, "two")) >= RED["extraction"]["iip3"]["min_points"]
    pl = next(p for p in RED["placements"] if p["name"] == C["placement"])
    for v in L.VARIANTS:
        assert L.placement_coherence(RED, pl, v) == []


def test_reduced_subset_brackets_p1db_and_keeps_im3_above_floor():
    rows_two = L.synthetic_rows(RED, C["a1"], C["a3"], 1e-9, kind="two")
    r = L.fit_iip3(rows_two, RED["extraction"]["iip3"], None, enforce_limits=False)
    assert r["status"] == "ok"
    rows_one = L.synthetic_rows(RED, C["a1"], C["a3"], 1e-9, kind="one")
    r = L.fit_p1db(rows_one, RED["extraction"]["p1db"], None, enforce_limits=False)
    assert r["status"] == "ok"


def test_compose_deck_is_one_pinned_circuit_of_both_kinds():
    deck = CIA.compose_deck(RED)
    assert deck.count(".control") == 1 and deck.count(".endc") == 1
    assert "echo LNLIN_DONE" in deck
    assert L.options_line(RED, "two") in deck
    assert "Bamp ya 0 V = 10.0*v(p1) + -2000.0*v(p1)*v(p1)*v(p1)" in deck
    for rid in ("b_two00", "b_two14", "b_one00", "b_one16"):
        assert f"m_{rid}_n" in deck


# ---- assertion paths on closed-form logs -------------------------------------


def test_assess_passes_on_the_closed_form_log_with_the_pinned_executable():
    problems, evs = CIA.assess(RED, INFO, 46, fake_combined_log())
    assert problems == []
    assert evs["two"]["pass"] and evs["one"]["pass"]


def test_missing_executable_is_a_failure():
    problems, _ = CIA.assess(RED, None, 46, fake_combined_log())
    assert problems == ["ngspice executable not found; the pinned executable did not run"]


def test_wrong_executable_major_is_a_failure():
    problems, _ = CIA.assess(RED, {"path": "/x", "version": "ngspice-45", "major": 45}, 46,
                             fake_combined_log())
    assert problems and "is not the pinned 46" in problems[0]


def test_truncated_log_is_a_failure():
    problems, _ = CIA.assess(RED, INFO, 46, fake_combined_log().replace("LNLIN_DONE", ""))
    assert any("LNLIN_DONE" in p for p in problems)


def test_nonfinite_mark_is_a_failure():
    log = re.sub(r"m_b_two03_f1_c = [-+0-9.eE]+", "m_b_two03_f1_c = nan", fake_combined_log())
    problems, _ = CIA.assess(RED, INFO, 46, log)
    assert any("missing or non-finite" in p for p in problems)


def test_missing_run_is_a_failure():
    log = fake_combined_log()
    for name in ("f1", "fl_lo"):
        log = re.sub(rf"m_b_one05_{name}_[cs] = [-+0-9.eE]+\n?", "", log)
    problems, _ = CIA.assess(RED, INFO, 46, log)
    assert any("b_one05" in p for p in problems)


# ---- sabotages fail their intended measured check ----------------------------


def test_amplitude_sabotage_fails_gain_and_leaves_the_db_answers_alone():
    for kind in ("two", "one"):
        summ, _ = A.summaries_for_key(RED, f"control_{kind}", fake_combined_log())
        scaled = L.points_from_summaries(CIA.sabotage_amplitude(summ, CIA.AMP_SABOTAGE_SCALE), kind)
        ev = L.evaluate_control(RED, kind, scaled, C["a1"], C["a3"])
        assert ev["gain_error_db"] is not None and abs(ev["gain_error_db"]) > ev["gain_tol_db"]
        assert not ev["pass"]
        if kind == "two":
            assert abs(ev["error_db"]) <= ev["tol_db"]


def test_power_axis_sabotage_fails_the_input_referred_answers():
    for kind in ("two", "one"):
        summ, _ = A.summaries_for_key(RED, f"control_{kind}", fake_combined_log())
        rows = L.points_from_summaries(summ, kind)
        shifted = [dict(r, pin_dbm=r["pin_dbm"] + CIA.POWER_SABOTAGE_SHIFT_DB) for r in rows]
        ev = L.evaluate_control(RED, kind, shifted, C["a1"], C["a3"])
        assert ev["error_db"] is not None and abs(ev["error_db"]) > ev["tol_db"]
        assert not ev["pass"]
