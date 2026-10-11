"""run.py (klt-sim driver) and the verified PDK artifact identity (issue #103).

A record needs the hash-verified artifact identity; `build_record` refuses
without one. These tests pin that run.py refuses BEFORE anything is
submitted or written (no klt call, no record id, no corners/<id>/ directory)
and that the identity it verified is the one handed to ingest/build_record.
No PDK, no simulator, no klt.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[1]
SIM = BENCH.parent
for p in (str(SIM), str(BENCH)):
    if p not in sys.path:
        sys.path.insert(0, p)

from harness import pdkartifact  # noqa: E402

_spec = importlib.util.spec_from_file_location("lna_sparam_nf_run", BENCH / "run.py")
run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run)

FAKE_PDK = object()
IDENTITY = {"status": "verified", "upstream_commit": "a" * 40, "manifest_sha256": "b" * 64}


def _unverified(pdk, sim_dir):
    raise pdkartifact.ArtifactNotVerified("model closure differs from the pin")


def _boom(*a, **k):
    raise AssertionError("must not be reached on an unverified install")


@pytest.fixture
def unverified(monkeypatch):
    monkeypatch.setattr(run, "_pdk", lambda: FAKE_PDK)
    monkeypatch.setattr(run.pdkartifact, "verified_identity", _unverified)
    # Anything that submits work or touches the evidence tree must not run.
    monkeypatch.setattr(run.subprocess, "run", _boom)
    monkeypatch.setattr(run, "allocate_record_id", _boom)
    monkeypatch.setattr(run, "build_record", _boom)
    monkeypatch.setattr(run, "write_record", _boom)
    monkeypatch.setattr(run, "write_netlist_snapshot", _boom)


def test_characterize_refuses_before_submitting_on_unverified_install(unverified, capsys):
    assert run.main(["characterize"]) == 3
    err = capsys.readouterr().err
    assert "differs from the pin" in err and "nothing submitted" in err


def test_ingest_refuses_before_any_log_dir_on_unverified_install(unverified, tmp_path, capsys):
    report = tmp_path / "report_2.50v.json"
    report.write_text("{}")
    (tmp_path / "body_2.50v.spice").write_text(run.klt_body(load_tb(BENCH), 2.5))
    corners_before = sorted((BENCH / "corners").iterdir()) if (BENCH / "corners").exists() else []
    assert run.main(["ingest", str(report)]) == 3
    assert "NO record written" in capsys.readouterr().err
    corners_after = sorted((BENCH / "corners").iterdir()) if (BENCH / "corners").exists() else []
    assert corners_after == corners_before


def test_characterize_hands_its_verified_identity_to_ingest(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "_pdk", lambda: FAKE_PDK)
    monkeypatch.setattr(run.pdkartifact, "verified_identity", lambda pdk, sim: IDENTITY)
    seen = {}

    class Done:
        returncode, stderr = 0, ""

    monkeypatch.setattr(run.subprocess, "run", lambda *a, **k: Done())
    monkeypatch.setattr(run, "SCRATCH", tmp_path)

    def fake_ingest(tb, reports, args, verified=None):
        seen["v"] = verified
        return 0

    monkeypatch.setattr(run, "ingest", fake_ingest)
    assert run.main(["characterize"]) == 0
    assert seen["v"] == (FAKE_PDK, IDENTITY)


def test_ingest_passes_identity_to_build_record():
    # Static guard: the only build_record call in run.py carries pdk_artifact.
    src = (BENCH / "run.py").read_text()
    call = src[src.index("record = build_record("):]
    call = call[:call.index("\n    write_netlist_snapshot")]
    assert "pdk_artifact=pdk_artifact" in call


def test_dry_run_needs_no_verified_install(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "_pdk", _boom)
    monkeypatch.setattr(run, "SCRATCH", tmp_path)
    monkeypatch.setattr(run.subprocess, "run", _boom)
    assert run.main(["characterize", "--dry-run"]) == 0


# --- issue #103 P1: the RUNNER's model closure, not the ingest host's install ---
#
# Every fixture below has a local install that matches the pin (verified_identity
# is stubbed to succeed). Only the klt reports differ. A record may be written
# only when the reports themselves bind the simulation models to the manifest.

import argparse  # noqa: E402
import copy  # noqa: E402
import json  # noqa: E402

from harness.corners import resolve_corners, supply_points  # noqa: E402
from harness.testbench import load as load_tb  # noqa: E402

MANIFEST = json.loads((SIM / "pdk-artifact.json").read_text())
PINNED = MANIFEST["files"]
MODEL_LIB = MANIFEST["model_lib"]


def _staged_assets():
    """What a staging-aware klt would report for the pinned closure: the
    top-level library is rewritten (its .include targets get staged names) and
    carries its source digest; the rest ship byte-for-byte."""
    out = []
    for rel, digest in sorted(PINNED.items()):
        name = rel.rsplit("/", 1)[-1]
        if rel == MODEL_LIB:
            out.append({"name": name, "field": "models.lib", "kind": "library",
                        "sha256": "c" * 64, "rewritten": True, "source_sha256": digest})
        else:
            out.append({"name": name, "field": "models.lib", "kind": "dependency",
                        "sha256": digest, "rewritten": False})
    return out


def _good_env(job="klt-sim-000000000001"):
    return {
        "engine": "ngspice", "engine_version": "46",
        "models_lib_sha256": PINNED[MODEL_LIB],
        "staged_model_inputs": _staged_assets(),
        "remote": {"provider": "aws-batch-fleet", "job_id": job, "runner_klt_version": "0.7.0",
                   "client_klt_version": "0.7.0", "runner_compatibility": "match"},
    }


def _drop_staged(env):
    # The shape real batch reports in this repo have today: no staged_model_inputs,
    # and models_lib_sha256 (client-side) equal to the pin.
    env.pop("staged_model_inputs")


def _no_source_digest(env):
    # The shape klt 0.7.0 emits when it does stage: rewritten lib, no source digest.
    for a in env["staged_model_inputs"]:
        a.pop("source_sha256", None)


def _mismatched_file(env):
    a = next(a for a in env["staged_model_inputs"] if not a["rewritten"])
    a["sha256"] = "d" * 64


def _missing_file(env):
    env["staged_model_inputs"] = [a for a in env["staged_model_inputs"] if a["rewritten"]]


def _extra_file(env):
    env["staged_model_inputs"].append({"name": "x.lib", "field": "models.lib", "kind": "dependency",
                                       "sha256": "e" * 64, "rewritten": False})


def _runner_mismatch(env):
    env["remote"].update(runner_klt_version="0.5.0", runner_compatibility="mismatch")


def _runner_unknown(env):
    env["remote"].update(runner_klt_version=None, runner_compatibility="unknown")


def _no_remote(env):
    env.pop("remote")


def _client_lib_differs(env):
    env["models_lib_sha256"] = "f" * 64


NEGATIVE = {
    "no-staged-model-inputs": (_drop_staged, "no environment.staged_model_inputs"),
    "rewritten-without-source-digest": (_no_source_digest, "no source_sha256"),
    "mismatched-model-file": (_mismatched_file, "is not a pinned file"),
    "missing-pinned-file": (_missing_file, "is not among the job's staged model inputs"),
    "extra-unpinned-file": (_extra_file, "is not a pinned file"),
    "runner-build-mismatch": (_runner_mismatch, "runner_compatibility is 'mismatch'"),
    "runner-build-unknown": (_runner_unknown, "runner_compatibility is 'unknown'"),
    "not-an-offhost-report": (_no_remote, "no environment.remote"),
    "client-lib-differs": (_client_lib_differs, "submitting client resolved model_lib"),
}


@pytest.mark.parametrize("case", sorted(NEGATIVE))
def test_verify_job_models_rejects(case):
    env = _good_env()
    mutate, needle = NEGATIVE[case]
    mutate(env)
    rep = pdkartifact.verify_job_models(env, SIM)
    assert not rep.ok
    assert any(needle in p for p in rep.problems), rep.problems


def test_verify_job_models_accepts_pinned_closure():
    rep = pdkartifact.verify_job_models(_good_env(), SIM)
    assert rep.ok, rep.problems


def test_offhost_identity_fails_if_any_job_lacks_evidence():
    bad = _good_env("klt-sim-bad")
    _drop_staged(bad)
    with pytest.raises(pdkartifact.ArtifactNotVerified) as exc:
        pdkartifact.offhost_identity([("report_a.json", _good_env()), ("report_b.json", bad)], SIM)
    assert "report_b.json" in str(exc.value) and "report_a.json" not in str(exc.value)
    with pytest.raises(pdkartifact.ArtifactNotVerified):
        pdkartifact.offhost_identity([], SIM)


# --- end-to-end through run.ingest -------------------------------------------

class _TbIn:
    """The real lna-sparam-nf testbench with its evidence tree moved to tmp."""

    def __init__(self, tb, exp):
        self._tb, self.experiment_dir = tb, exp

    def __getattr__(self, name):
        return getattr(self._tb, name)


def _write_reports(tmp_path, tb, env_for, log_text=None):
    """One klt report per supply, 9 corners each, logs with every measurement."""
    if log_text is None:
        log_text = "\n".join(f"m_{n} = 1.0" for n in tb.measure) + "\n"
    reports = []
    for vdd in supply_points(tb.nominal_supply_v, tb.supply_tolerance):
        tag = f"{vdd:.2f}v"
        out = tmp_path / f"out_{tag}"
        out.mkdir()
        corners = []
        for c in resolve_corners(list(tb.corners)):
            for t in tb.temperatures_c:
                log = out / f"{c.name}_{t}.log"
                log.write_text(log_text)
                corners.append({"process": c.name, "temperature_c": t,
                                "artifacts": {"log": str(log)}, "runtime_s": 1.0})
        path = tmp_path / f"report_{tag}.json"
        path.write_text(json.dumps({"status": "ok", "corners": corners,
                                    "environment": env_for(tag)}))
        # The body deck characterize writes beside every report; ingest's
        # issue-#141 gate compares it against the reloaded testbench.
        (tmp_path / f"body_{tag}.spice").write_text(run.klt_body(tb, vdd))
        reports.append((vdd, path))
    return reports


@pytest.fixture
def local_install_matches(monkeypatch, tmp_path):
    """Local install on the pin; nothing may touch the real evidence tree."""
    monkeypatch.setattr(run, "_pdk", lambda: FAKE_PDK)
    monkeypatch.setattr(run.pdkartifact, "verified_identity", lambda pdk, sim: IDENTITY)

    class Ver:
        returncode, stdout, stderr = 0, "klt 0.7.0", ""

    monkeypatch.setattr(run.subprocess, "run", lambda *a, **k: Ver())
    monkeypatch.setattr(run, "ngspice_version", lambda: "ngspice-46")
    monkeypatch.setattr(run, "git_provenance", lambda root: {"commit": "0" * 40, "short": "0000000"})
    tb = _TbIn(load_tb(BENCH), tmp_path / "exp")
    (tb.experiment_dir / "records").mkdir(parents=True)
    return tb


def _args():
    return argparse.Namespace(supersedes="", claim="", klt_cmd="klt")


@pytest.mark.parametrize("case", sorted(NEGATIVE))
def test_ingest_refuses_unbound_runner_models_before_record_id(local_install_matches, monkeypatch,
                                                                tmp_path, capsys, case):
    tb = local_install_matches
    mutate, needle = NEGATIVE[case]

    def env_for(tag):
        env = _good_env(f"klt-sim-{tag}")
        if tag != f"{tb.nominal_supply_v:.2f}v":  # one bad job is enough to refuse
            return env
        mutate(env)
        return env

    monkeypatch.setattr(run, "allocate_record_id", _boom)
    monkeypatch.setattr(run, "build_record", _boom)
    monkeypatch.setattr(run, "write_record", _boom)
    monkeypatch.setattr(run, "write_netlist_snapshot", _boom)
    reports = _write_reports(tmp_path, tb, env_for)
    assert run.ingest(tb, reports, _args()) == 3
    err = capsys.readouterr().err
    assert needle in err and "NO record written" in err
    assert not (tb.experiment_dir / "corners").exists()  # no log copied


# --- issue #141, bare ingest: a later manifest may not be attached to results
# --- simulated from decks an earlier characterize wrote from other inputs ---

def test_ingest_refuses_body_deck_from_other_inputs(local_install_matches, monkeypatch, tmp_path,
                                                    capsys):
    tb = local_install_matches
    monkeypatch.setattr(run, "allocate_record_id", _boom)
    monkeypatch.setattr(run, "build_record", _boom)
    monkeypatch.setattr(run, "write_record", _boom)
    monkeypatch.setattr(run, "write_netlist_snapshot", _boom)
    reports = _write_reports(tmp_path, tb, lambda tag: _good_env(f"klt-sim-{tag}"))
    # The tb.json/fragment changed after the deck was written: the deck on
    # disk is no longer what the reloaded testbench would generate.
    stale = run.body_for(reports[0][1])
    stale.write_text(run.klt_body(tb, reports[0][0]) + "* edited after characterize\n")
    assert run.ingest(tb, reports, _args()) == 1
    err = capsys.readouterr().err
    assert stale.name in err and "different testbench inputs" in err
    assert "NO record written" in err
    _nothing_published(tb)


def test_ingest_refuses_missing_body_deck(local_install_matches, monkeypatch, tmp_path, capsys):
    tb = local_install_matches
    monkeypatch.setattr(run, "allocate_record_id", _boom)
    monkeypatch.setattr(run, "build_record", _boom)
    monkeypatch.setattr(run, "write_record", _boom)
    monkeypatch.setattr(run, "write_netlist_snapshot", _boom)
    reports = _write_reports(tmp_path, tb, lambda tag: _good_env(f"klt-sim-{tag}"))
    run.body_for(reports[-1][1]).unlink()
    assert run.ingest(tb, reports, _args()) == 1
    assert "NO record written" in capsys.readouterr().err
    _nothing_published(tb)


def test_cmd_ingest_refuses_missing_body_before_ingest(monkeypatch, tmp_path, capsys):
    # CLI path: cmd_ingest refuses before _body_supply ever reads the deck
    # (a missing file must not surface as a traceback) and before ingest runs.
    monkeypatch.setattr(run, "ingest", _boom)
    report = tmp_path / "report_2.50v.json"
    report.write_text("{}")
    assert run.main(["ingest", str(report)]) == 1
    err = capsys.readouterr().err
    assert "body_2.50v.spice is missing" in err and "NO record written" in err


def test_ingest_binds_record_to_offhost_models_not_local_install(local_install_matches, monkeypatch,
                                                                  tmp_path):
    tb = local_install_matches
    seen = {}

    def fake_build_record(*a, **k):
        seen.update(k)
        return {"status": "pass"}

    def fake_write_record(record, exp):
        p = exp / "records" / "TESTID.md"
        p.write_text("")
        return p

    monkeypatch.setattr(run, "allocate_record_id", lambda *a, **k: "TESTID")
    monkeypatch.setattr(run, "build_record", fake_build_record)
    monkeypatch.setattr(run, "write_record", fake_write_record)
    monkeypatch.setattr(run, "write_netlist_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(run.stage1_tables, "render", lambda *a, **k: "")
    reports = _write_reports(tmp_path, tb, lambda tag: _good_env(f"klt-sim-{tag}"))
    assert run.ingest(tb, reports, _args()) == 0

    art = seen["pdk_artifact"]
    assert art is not IDENTITY and art["verified_scope"] == "offhost-job-model-inputs"
    assert art["upstream_commit"] == MANIFEST["upstream"]["commit"]
    assert art["files_verified"] == len(PINNED)
    assert sorted(j["job_id"] for j in art["jobs"]) == sorted(
        f"klt-sim-{v:.2f}v" for v in supply_points(tb.nominal_supply_v, tb.supply_tolerance))
    pdkartifact.validate_identity(art)
    notes = "\n".join(seen["extensions"].notes)
    assert "ingest host" in notes and "says nothing about the runner" in notes
    assert len(list((tb.experiment_dir / "corners" / "TESTID").glob("*.log"))) == 27


def test_characterize_refuses_unstaged_submission(monkeypatch):
    monkeypatch.setattr(run, "_pdk", _boom)
    monkeypatch.setattr(run.subprocess, "run", _boom)
    assert run.main(["characterize", "--no-stage-models"]) == 3


# --- stage1 tables are validated before anything is published (issue #130) ---

def _stage1_log(tb, *, markers=True, unstable=False, sw_kmin_scale=1.0):
    """A corner log whose scalars agree with its printed 3-point sweep."""
    ks, ds, mus = ([5.0, 3.0, 2.0], [0.5, 0.6, 0.7], [1.5, 1.2, 1.1])
    if unstable:
        ks[1], ds[1] = 0.8, 1.2
    vals = {n: 1.0 for n in tb.measure}
    vals.update({f"{d}_vce": 1.0 for d in ("q1", "q2", "qr")})
    vals.update({f"{d}_vbe": 0.8 for d in ("q1", "q2", "qr")})
    vals.update({f"{d}_icfrac": 0.5 for d in ("q1", "q2", "qr")})
    vals.update({f"{d}_ft": 100.0 for d in ("q1", "q2", "qr")})
    for s in ("lo", "mid", "hi"):
        vals.update({f"k_{s}": 5.0, f"d_{s}": 0.5})
    nunst = sum(1 for k, d in zip(ks, ds) if k <= 1.0 or d >= 1.0)
    vals.update({"sw_n": 3.0, "sw_kmin": min(ks) * sw_kmin_scale, "sw_dmax": max(ds),
                 "sw_mumin": min(mus), "sw_nunst": float(nunst)})
    if unstable:
        vals["k_mid"] = 0.8
        vals["sw_fkmin_ghz"] = 1.0
    lines = [f"m_{n} = {vals[n]!r}" for n in tb.measure]
    if markers:
        lines.append("SWEEP_BEGIN")
        lines.append("Index frequency wf wk wd wmu")
        for i, (k, d, mu) in enumerate(zip(ks, ds, mus)):
            f = 1e9 * 10 ** (i / 100)
            lines.append(f"{i}\t{f:.10e}\t{f:.10e}\t{k:.10e}\t{d:.10e}\t{mu:.10e}\t")
        lines.append("SWEEP_END")
    return "\n".join(lines) + "\n"


def _ingest_real(tb, tmp_path, log_text):
    reports = _write_reports(tmp_path, tb, lambda tag: _good_env(f"klt-sim-{tag}"), log_text)
    return run.ingest(tb, reports, _args())


def _nothing_published(tb):
    assert list((tb.experiment_dir / "records").iterdir()) == []
    assert not (tb.experiment_dir / "corners").exists()
    assert not (tb.experiment_dir / "snapshots").exists()


@pytest.mark.parametrize("case", ["missing_markers", "scalar_disagreement"])
def test_invalid_stage1_package_publishes_nothing(local_install_matches, tmp_path, capsys, case):
    tb = local_install_matches
    log = (_stage1_log(tb, markers=False) if case == "missing_markers"
           else _stage1_log(tb, sw_kmin_scale=1.5))
    rc = _ingest_real(tb, tmp_path, log)
    assert rc == 4 and rc not in (1, 3)
    err = capsys.readouterr().err
    assert "invalid stage1 measurement package" in err and "NO record" in err
    if case == "missing_markers":
        assert "SWEEP_BEGIN" in err
    else:
        assert "disagree" in err
    _nothing_published(tb)


@pytest.mark.parametrize("unstable", [False, True])
def test_valid_stage1_package_keeps_tables(local_install_matches, monkeypatch, tmp_path, unstable):
    tb = local_install_matches

    class _Pdk:
        def provenance(self):
            return {"pdk": "fake"}

    monkeypatch.setattr(run, "_pdk", lambda: _Pdk())
    rc = _ingest_real(tb, tmp_path, _stage1_log(tb, unstable=unstable))
    assert rc in (0, 1)  # status verdict is independent of the tables
    (rec,) = (tb.experiment_dir / "records").glob("*.md")
    text = rec.read_text()
    assert "## Operating points per device and grid cell" in text
    assert "## Stability: k, |Delta|, mu" in text
    assert "### Sweep statistics cross-check" in text
    assert text.index("## How to read this record") > text.index("Status")
    if unstable:
        assert "POTENTIALLY UNSTABLE" in text and "Cells labelled POTENTIALLY UNSTABLE: **27 of 27**" in text
    else:
        assert "Cells labelled POTENTIALLY UNSTABLE: **0 of 27**" in text
    assert len(list((tb.experiment_dir / "corners" / rec.stem).glob("*.log"))) == 27
