"""Closed-form qualification of the lna-passive-study bench (issue #340).

No simulator, no fleet, no PDK install: everything checked here is a property
of files committed in the tree (plan, sizing table, variant decks, prematch
outcome) or of pure arithmetic in passive.py. The fleet-verified model facts
(closed-form R/C vs the instanced r3_cmc / MIM models) are re-checked against
the sizing table's own embedded model parameters, so a PDK change that breaks
the derivation's assumptions fails here without any ngspice.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import passive as PS  # noqa: E402

REPO = PS.REPO_ROOT


@pytest.fixture(scope="module")
def plan() -> dict:
    return PS.load_plan()


@pytest.fixture(scope="module")
def sizing() -> dict:
    return PS.load_sizing()


@pytest.fixture(scope="module")
def prematch() -> dict:
    return json.loads(PS.PREMATCH_PATH.read_text(encoding="utf-8"))


def test_plan_is_the_frozen_declaration(plan, sizing) -> None:
    assert PS.plan_problems(plan, PS.DUT_PATH.read_text(encoding="utf-8"),
                            sizing) == []


def test_variant_decks_regenerate(plan, sizing, prematch) -> None:
    from run import variant_decks
    decks = variant_decks(plan, sizing, prematch)
    assert sorted(decks) == sorted(v["id"] for v in plan["variants"])
    for vid, text in decks.items():
        committed = PS.VARIANTS_DIR / f"{vid}.spice"
        assert committed.is_file(), f"{vid}.spice missing"
        assert committed.read_text() == text, f"{vid}.spice drifted from plan+sizing+prematch"


def test_control_deck_is_the_committed_netlist_verbatim() -> None:
    text = PS.control_dut_text(PS.DUT_PATH.read_text(encoding="utf-8"))
    body = text.split("* lna_stage1 subcircuit", 1)[1]
    committed = PS.DUT_PATH.read_text(encoding="utf-8").split(
        "* lna_stage1 subcircuit", 1)[1]
    assert body == committed  # only the study's header is added


def test_variant_decks_keep_inductors_ideal(plan, sizing, prematch) -> None:
    from run import variant_decks
    for vid, text in variant_decks(plan, sizing, prematch).items():
        for line in text.splitlines():
            if line.startswith(("Lfeed ", "Le1 ")):
                assert line == next(l for l in PS.DUT_PATH.read_text().splitlines()
                                    if l.startswith(line.split()[0] + " ")), \
                    f"{vid}: an inductor line changed: {line}"


def test_v04_freezes_the_prematch_selection(plan, sizing, prematch) -> None:
    from run import variant_decks
    deck = variant_decks(plan, sizing, prematch)["V04"]
    sel = prematch["selection"]
    assert sel, "prematch selected nothing; V04 must be dropped, not frozen"
    match = prematch["rematches"][f"{sel['cblk_f']:g}"]
    for ref, nodes, side in (("Xblk_in", "in2 b1", match["side_um"]),
                             ("Xshunt", "in gnd", match["shunt_side_um"])):
        assert f"{ref} {nodes} cap_cmim w={side:g}u l={side:g}u" in deck
    assert f"Lin in in2 {sel['lin_h']*1e9:.4g}n" in deck
    assert prematch["runs"]["V04"]["deck_sha256"] == PS.sha256_text(deck)
    bounds = []
    for i, value in enumerate(sorted(PS.PREMATCH_GRID_F), 1):
        bound = max(cell[f"s11_db_{band}_c{i}"] for cell in prematch["grid"].values()
                    for band in ("lo", "mid", "hi"))
        bounds.append((value, bound))
    assert next(pair for pair in bounds if pair[1] <= PS.S11_TARGET_DB) == (
        sel["cblk_f"], sel["worst_s11_db"])


def test_prematch_grid_and_corners_are_the_declared_ones(prematch, plan) -> None:
    assert {f"{v:g}" for v in PS.PREMATCH_GRID_F} == \
        {f"{float(k):g}" for k in prematch["rematches"]}
    assert set(prematch["grid"]) == {
        f"{proc}/novdd/{t:g}C" for proc in PS.PREMATCH_CORNERS
        for t in PS.PREMATCH_TEMPS_C}
    assert set(prematch["selected_row4"]) == set(prematch["grid"])
    assert len(prematch["grid"]) == 8
    tag = PS.PREMATCH_GRID_F.index(prematch["selection"]["cblk_f"]) + 1
    for cell, bands in prematch["selected_row4"].items():
        for band in ("lo", "mid", "hi"):
            assert bands[band]["s11_db"] == pytest.approx(
                prematch["grid"][cell][f"s11_db_{band}_c{tag}"], abs=0.001)
            assert math.isfinite(bands[band]["delta_nf_db"])
    # every grid cell measured every candidate at every band point
    tags = range(1, len(PS.PREMATCH_GRID_F) + 1)
    for cell in prematch["grid"].values():
        for i in tags:
            for band in ("lo", "mid", "hi"):
                assert f"s11_db_{band}_c{i}" in cell


def test_m_multiplier_check_passed(prematch) -> None:
    check = prematch["probe"]["m_multiplier_check"]
    assert abs(check["m2_f"] / check["two_f"] - 1.0) <= 0.01


def test_rf_multiplier_with_substrate_loading(prematch) -> None:
    probe = prematch["probe"]["rf_array_at_19_45_ghz"]
    for name in ("input_a", "out_v", "bulk_a"):
        for part in ("real", "imag"):
            explicit = probe[f"rf_e_{name}_{part}"]
            assert explicit != 0
            assert probe[f"rf_m_{name}_{part}"] == pytest.approx(explicit, rel=1e-8)


def test_wide_resistor_choices_reach_three_ohms(sizing) -> None:
    re1 = next(r for r in sizing["resistors"] if r["refdes"] == "Re1")["candidates"]
    for flavour in ("rsil", "rppd", "rhigh"):
        assert re1[flavour]["r_ohm"]["typ"] == pytest.approx(3.0, rel=0.01)
    assert re1["rsil"]["body_area_um2"] < re1["rppd"]["body_area_um2"]


def test_cell_keys_and_control_mapping() -> None:
    ck = PS.cell_key("V01", "res_wcs__cap_bcs", -40.0, 2.25)
    assert ck == "V01__res_wcs__cap_bcs__-40C__2.25V"
    # the passive-extreme cells compare against the typ control at the same
    # hbt section (hbt_typ), not against a passive corner of the control
    assert PS.control_cell_key("res_wcs__cap_bcs", -40.0, 2.25) == \
        PS.cell_key("V00", "typ", -40.0, 2.25)
    assert PS.control_cell_key("hbt_wcs", 125.0, 2.5) == \
        PS.cell_key("V00", "hbt_wcs", 125.0, 2.5)


def test_deltas_need_every_control_cell() -> None:
    variant = {PS.cell_key("V01", "typ", 27.0, 2.5): {"s21_db_mid": 18.0,
                                                      "nf_db_mid": 3.0}}
    control = {PS.cell_key("V00", "typ", 27.0, 2.5): {"s21_db_mid": 17.0,
                                                      "nf_db_mid": 2.5}}
    for deck in (variant, control):
        for row in deck.values():
            for name in PS.DELTA_MEASURES:
                row.setdefault(name, 0.0)
    d = PS.deltas(variant, control)
    assert d[PS.cell_key("V01", "typ", 27.0, 2.5)]["s21_db_mid"] == pytest.approx(1.0)
    assert d[PS.cell_key("V01", "typ", 27.0, 2.5)]["nf_db_mid"] == pytest.approx(0.5)
    with pytest.raises(ValueError):
        PS.deltas(variant, {})
    del next(iter(variant.values()))["nf_db_mid"]
    with pytest.raises(ValueError, match="missing nf_db_mid"):
        PS.deltas(variant, control)


def test_l_section_match_matches_exactly_at_f0_below_50() -> None:
    r_b, x_b, cblk = 24.0, -148.0, 1e-9
    lin_h, cshunt_f = PS.l_section_match(r_b, x_b, cblk, PS.BAND_CENTRE_HZ)
    w = 2 * math.pi * PS.BAND_CENTRE_HZ
    z_l = complex(r_b, x_b - 1.0 / (w * cblk))
    y = complex(0.0, w * cshunt_f) + 1.0 / (complex(0.0, w * lin_h) + z_l)
    assert y.real == pytest.approx(1.0 / 50.0, abs=1e-9)
    assert y.imag == pytest.approx(0.0, abs=1e-9)


def test_l_section_match_degrades_to_reactance_cancellation_at_or_above_50() -> None:
    # the measured post-Le1 core resistance sits just below 50 ohm; a load at
    # or above 50 cannot be matched by the fixed topology, and the tuner must
    # say so by cancelling reactance only with the committed shunt value
    lin_h, cshunt_f = PS.l_section_match(334.0, -143.0, 1e-12, PS.BAND_CENTRE_HZ)
    w = 2 * math.pi * PS.BAND_CENTRE_HZ
    z_l = complex(334.0, -143.0 - 1.0 / (w * 1e-12))
    assert (w * lin_h + z_l.imag) == pytest.approx(0.0, abs=1e-6)
    assert cshunt_f == 170e-15
    with pytest.raises(ValueError):
        PS.l_section_match(48.0, +200.0, 0.5e-12, PS.BAND_CENTRE_HZ)  # negative Lin


def test_cap_side_inversion_hits_the_design_value(sizing) -> None:
    for value_f in (1e-12, 5e-12, 57.8e-15, 170e-15):
        side = PS.cap_side_for_value(sizing, "cmim", value_f)
        assert abs(side["c_typ_f"] - value_f) / value_f <= 0.01


def test_probe_measured_values_reproduce_from_the_table(sizing) -> None:
    """The fleet-probe cross-check embedded in passive_sizing must re-derive
    from the committed table's own model parameters (PDK-free)."""
    sys.path.insert(0, str(REPO / "layout" / "lna_stage1"))
    import passive_sizing as SZ
    rm, cm = sizing["resistor_models"], sizing["capacitor_models"]
    for label, meas in SZ._PROBE_MEASURED.items():
        kind = label.split()[0]
        if kind in rm:
            w = float(label.split()[1].split("=")[1])
            l = float(label.split()[2].split("=")[1])
            for corner, want in meas.items():
                got = SZ.model_r_ohm(rm[kind], w, l, corner)
                assert abs(got - want) <= max(0.02, 1e-4 * abs(want)), \
                    f"{label} {corner}: {got} vs probe {want}"
        else:
            side = float(label.split()[1].split("x")[0])
            for corner, want in meas.items():
                got = SZ.model_c_f(cm[kind], side, side, corner)
                assert abs(got - want) / want <= 1e-3, \
                    f"{label} {corner}: {got} vs probe {want}"


def test_parse_log_roundtrip() -> None:
    log = "m_s21_db_mid = 1.790494e+01\nm_nf_db_mid = 2.865450e+00\nnoise\n"
    assert PS.parse_log(log) == {"s21_db_mid": 17.90494, "nf_db_mid": 2.86545}


def test_requests_use_per_section_corner_bundles() -> None:
    req = PS.klt_request("body.spice", ["typ", "res_wcs__cap_bcs"], [27.0], 600,
                         "/abs/r3_cmc.osdi")
    axis = req["corners"]["process"]
    assert [c["name"] for c in axis] == ["typ", "res_wcs__cap_bcs"]
    for corner in axis:
        libs = {s["lib"] for s in corner["sections"]}
        assert libs == set(PS.MODEL_LIBS.values())
    assert req["options"]["osdi_preload"] == ["/abs/r3_cmc.osdi"]
    assert req["options"]["stage_model_inputs"] is True
    assert req["models"]["pdk"] == "ihp-sg13g2"


def test_control_gates_check_the_reference_rows_and_envelopes():
    import run
    # Populate the nominal device measurements from each actual table row.
    text = (REPO / PS.BASELINE_RECORD).read_text()
    cells = {ck: dict.fromkeys(PS.load_json(PS.METHOD_TB)["measure"], 0.)
             for ck in run._grid("V00")}
    for line in text.splitlines():
        if line.startswith("- `") and "`: min " in line:
            name = line.split("`")[1]
            for row in cells.values():
                row[name] = float(line.split(": min ")[1].split()[0])
        if line.startswith("| hbt_") and "c_2.50v |" in line:
            cols = [c.strip() for c in line.split("|")]
            device = {"Q1 (CE)": "q1", "Q2 (CB)": "q2", "Qref (mirror)": "qr"}.get(cols[3])
            if device:
                proc, temp, _ = cols[1].rsplit("_", 2)
                ck = PS.cell_key("V00", "typ" if proc == "hbt_typ" else proc,
                                 float(temp[:-1]), 2.5)
                for measure, raw in zip(("vce", "vbe", "ic"), cols[4:7]):
                    cells[ck][f"{device}_{measure}"] = float(raw) / (1000 if measure == "ic" else 1)
    for proc in PS.PREMATCH_CORNERS:
        for temp in PS.TEMPERATURES_C:
            cells[PS.cell_key("V00", proc, temp, 2.5)] = cells[PS.cell_key("V00", "typ", temp, 2.5)].copy()
    assert run._gate_control(cells)["pass"]
    ck = PS.cell_key("V00", "hbt_wcs", 125, 2.5)
    cells[ck]["qr_ic"] *= 1000
    cells[ck]["s11_db_lo"] = 99.
    assert run._gate_control(cells)["checks"] == {
        "baseline_op_table": False, "baseline_envelope": False,
        "finite_values": True, "passive_inertness": True}
    row = next(line for line in text.splitlines() if "| hbt_wcs_125c_2.50v" in line and "Qref" in line)
    assert any("required 27" in msg for msg in run._baseline_checks(cells, text.replace(row, ""))[0])


def test_verify_rejects_incomplete_historical_variant():
    import run
    rid = "20261121-044750-495011a"
    rec = PS.load_json(run.RECORDS / f"{rid}.json")
    for row in rec["deltas"]["V01"].values():
        del row["nf_db_mid"]
    del rec["worst"]["V01"]["nf_db_mid"]
    assert any("nf_db_mid" in msg for msg in run._verify_one(rec, (run.RECORDS / f"{rid}.md").read_text()))


def test_collect_requires_complete_screen_and_propagates_store_failure(monkeypatch, tmp_path, prematch):
    import run
    from argparse import Namespace
    args = Namespace(backend="batch", dry_run=True, klt_cmd="klt", wait_for_capacity=1,
                     capacity_retries=0, timeout_s=10)
    path = tmp_path / "prematch.json"
    monkeypatch.setattr(PS, "PREMATCH_PATH", path)
    monkeypatch.setattr(run, "SCRATCH", tmp_path / "work")
    monkeypatch.setattr(run, "_osdi_abs_path", lambda: "/unused/r3_cmc.osdi")
    path.write_text('{"selection": null}')
    assert run.cmd_collect(args) == 1
    screen = dict(prematch, selection=None,
                  grid={k: dict.fromkeys(row, -9.) for k, row in prematch["grid"].items()})
    path.write_text(json.dumps(screen))
    assert run.cmd_collect(args) == 0
    reqs = list(run.SCRATCH.rglob("request_*.json"))
    assert len(reqs) == 12 and not any("V04" in p.name for p in reqs)
    args.dry_run = False
    monkeypatch.setattr(run.store_mod, "preflight", lambda *a, **kw: None)
    monkeypatch.setattr(run.klt_driver, "submit_set", lambda *a, **kw: {})
    monkeypatch.setattr(run, "_verify_model_identity", lambda *a: {})
    monkeypatch.setattr(run, "_read_cells", lambda *a: {})
    monkeypatch.setattr(run, "_gate_control", lambda *a: {"pass": True})
    monkeypatch.setattr(run, "_build_record", lambda *a: {})
    monkeypatch.setattr(run, "_write_record", lambda *a: 10)
    assert run.cmd_collect(args) == 10


def test_ingest_rejects_failed_duplicate_and_incomplete_corners(tmp_path):
    import run
    body = tmp_path / "body_V01_2.50v.spice"
    body.write_text("fixture")
    log = tmp_path / "ngspice.log"
    log.write_text("m_s21_db_mid = 1\n")
    report = tmp_path / "report.json"
    corner = {"process": "typ", "temperature_c": 27., "status": "pass",
              "artifacts": {"log": str(log)}}
    for corners, message in [([dict(corner, status="fail")], "failed"),
                             ([corner, corner], "duplicate"), ([corner], "missing")]:
        report.write_text(json.dumps({"status": "pass", "corners": corners,
                                      "environment": {"netlist_sha256": run.sha256_file(body)}}))
        with pytest.raises(run.CollectionError, match=message):
            run._read_cells([("V01_2.50v", report)], ["V01"])
    grid = {ck: dict.fromkeys(PS.DELTA_MEASURES, 0.) for ck in run._grid("V01")}
    grid[next(iter(grid))]["nf_db_mid"] = math.nan
    assert any("nf_db_mid" in msg for msg in run._measurement_problems(
        grid, run._grid("V01"), PS.DELTA_MEASURES))


def test_batch_model_identity_requires_each_pin_and_runner_preload(tmp_path, monkeypatch):
    import run
    from harness import pdk
    from types import SimpleNamespace
    monkeypatch.setattr(pdk, "find_pdk", lambda _: SimpleNamespace(path=tmp_path))
    pins = PS.load_json(PS.SIM_DIR / "pdk-artifact.json")["files"]
    pins.update({rel: PS.load_sizing()["inputs"]["pdk"]["files"][rel][7:] for rel in run.EXTRA_MODEL_FILES[:-1]})
    osdi = run.EXTRA_MODEL_FILES[-1]
    pins[osdi] = PS.load_plan()["prematch"]["osdi_sha256"]
    for rel in pins:
        path = tmp_path / rel
        path.parent.mkdir(exist_ok=True, parents=True)
        path.touch()
    monkeypatch.setattr(run, "sha256_file", lambda p: pins[p.relative_to(tmp_path).as_posix()])
    assets = [{"name": Path(rel).name, "sha256": digest} for rel, digest in pins.items()]
    remote = {"runner_compatibility": "match", "runner_model_inputs": assets,
              "runner_osdi_preload": [assets[-1]]}
    env = {"backend": {"resolved": "batch"}, "remote": remote, "staged_model_inputs": assets}
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"environment": env}))
    assert run._verify_model_identity([report])["jobs"] == 1
    for rel in run.EXTRA_MODEL_FILES:
        env["staged_model_inputs"] = [a for a in assets if a["name"] != Path(rel).name]
        report.write_text(json.dumps({"environment": env}))
        with pytest.raises(run.CollectionError, match="missing or mismatched"):
            run._verify_model_identity([report])
    env["staged_model_inputs"] = assets
    remote["runner_osdi_preload"] = [dict(assets[-1], sha256="0" * 64)]
    report.write_text(json.dumps({"environment": env}))
    with pytest.raises(run.CollectionError, match="loaded OSDI"):
        run._verify_model_identity([report])


def test_row6_absolute_minimum_and_minimum_delta_can_be_different_cells():
    import run
    grid = run._bound_cells("V04")["row6"]
    assert len(grid) == 63
    absolute = dict.fromkeys(run._grid("V00"), 8.)
    absolute.update(dict.fromkeys(grid, 10.))
    limiting = PS.cell_key("V04", "hbt_wcs", 125, 2.75)
    worst_change = PS.cell_key("V04", "res_bcs__cap_wcs", 27, 2.25)
    absolute[limiting] = 6.
    absolute[worst_change] = 7.
    absolute[PS.control_cell_key("res_bcs__cap_wcs", 27, 2.25)] = 12.
    assert run._stability(absolute, grid) == {
        "limiting_cell": limiting, "minimum_k": 6., "delta_at_limiting_cell": -2.,
        "minimum_delta_cell": worst_change, "minimum_delta": -5.}


def test_stored_bundle_digest_is_checked_before_ingest(tmp_path):
    import run
    rid = "20261121-044750-495011a"
    path = tmp_path / "cells.json.gz"
    path.write_bytes(b"wrong object")
    assert "digest mismatch" in run._verify_stored_cells({"record_id": rid}, path)[0]


def test_record_markdown_reproduces_after_sorted_json_round_trip():
    import run
    for path in sorted(run.RECORDS.glob("*.json")):
        rec = json.loads(json.dumps(PS.load_json(path), sort_keys=True))
        assert run._verify_one(rec, path.with_suffix(".md").read_text()) == []


def test_collect_checks_storage_before_any_submission(monkeypatch, tmp_path, prematch):
    import run
    from argparse import Namespace
    path = tmp_path / "prematch.json"
    path.write_text(json.dumps(prematch))
    monkeypatch.setattr(PS, "PREMATCH_PATH", path)
    monkeypatch.setattr(run, "SCRATCH", tmp_path / "work")
    monkeypatch.setattr(run, "_osdi_abs_path", lambda: "/unused/r3_cmc.osdi")
    calls = []

    def refuse(*a, **kw):
        calls.append("preflight")
        raise run.store_mod.StoreError("no broker")

    def submitted(*a, **kw):
        calls.append("submit")
        return {}

    monkeypatch.setattr(run.store_mod, "preflight", refuse)
    monkeypatch.setattr(run.klt_driver, "submit_set", submitted)
    monkeypatch.setattr(run.klt_driver, "submit_request", submitted)
    for backend in ("batch", "local"):
        args = Namespace(backend=backend, dry_run=False, klt_cmd="klt", wait_for_capacity=1,
                         capacity_retries=0, timeout_s=10)
        assert run.cmd_collect(args) == 10
    assert calls == ["preflight", "preflight"]
    calls.clear()
    args.dry_run = True  # a dry run submits nothing and needs no store
    assert run.cmd_collect(args) == 0 and calls == []


def test_raw_corner_log_bytes_reach_the_archive(tmp_path):
    import run
    body = tmp_path / "body_V01_2.50v.spice"
    body.write_text("fixture")
    text = "warning: something\nm_nf_db_mid = 2.865450e+00\n"
    log = tmp_path / "ngspice.log"
    log.write_text(text)
    report = tmp_path / "report.json"
    report.write_text(json.dumps({
        "status": "pass", "environment": {"netlist_sha256": run.sha256_file(body)},
        "corners": [{"process": "typ", "temperature_c": 27., "status": "pass",
                     "artifacts": {"log": str(log)}}]}))
    raw = {}
    try:
        run._read_cells([("V01_2.50v", report)], ["V01"], raw)
    except run.CollectionError:
        pass  # the one-cell fixture is not a full grid; raw capture precedes that check
    assert list(raw.values()) == [text]


def test_probe_capacitance_sign_and_annotations(sizing, plan) -> None:
    import run
    body = run._probe_body(PS.load_json(PS.METHOD_TB), plan)
    assert "-imag(i(vca))" in body and "-imag(i(vcb))" in body
    assert PS.model_cap_f(sizing, "cmim", 6.16) > 0
    assert PS.cap_annotation_problems(plan, sizing) == []
    assert not PS.ANNOTATION_ERRATA or all(
        (PS.SIM_DIR / "lna-passive-study" / v).is_file() for v in PS.ANNOTATION_ERRATA.values())
