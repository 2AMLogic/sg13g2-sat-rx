"""run.py's record-note branches and the batch capacity wait (issues #22, #28, #250).

A record can relate to an earlier one in exactly three ways, and run.py's
ingest must stamp the right note on each: ``--supersedes`` is a method
CORRECTION (same DUT; the logs are compared under lna_nf.py's linear-F
relation and disagreement refuses the record), ``--supersedes-new-dut`` is a
NEW core revision of the DUT (same bench and method; the note says the circuit
-- not the method -- changed, and the agreement comparison is deliberately NOT
run, because a real core change must be allowed to violate it), and neither
flag is a new design that supersedes nothing. Also pinned here: every
``--backend batch`` characterize submit carries ``--wait-for-capacity`` (the
host rule), the default is 600 s, a local backend submit does not, and the
two supersedes flags refuse each other.

No PDK, no simulator, no klt, no broker.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[1]
SIM = BENCH.parent
for p in (str(SIM), str(BENCH)):
    if p not in sys.path:
        sys.path.insert(0, p)

from harness.corners import resolve_corners, supply_points  # noqa: E402
from harness import pdkartifact  # noqa: E402
from harness.testbench import load as load_tb  # noqa: E402

_spec = importlib.util.spec_from_file_location("lna_sparam_nf_run", BENCH / "run.py")
run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run)

FAKE_PDK = object()
IDENTITY = {"status": "verified", "upstream_commit": "a" * 40, "manifest_sha256": "b" * 64}
OLD_RECORD = "20261010-012923-6cad7fc"

MANIFEST = json.loads((SIM / "pdk-artifact.json").read_text())
PINNED = MANIFEST["files"]
MODEL_LIB = MANIFEST["model_lib"]

import importlib.util as _ilu  # noqa: E402

_spec2 = _ilu.spec_from_file_location(
    "harness_test_evidence_store", SIM / "harness" / "tests" / "test_evidence_store.py")
_mod = _ilu.module_from_spec(_spec2)
_spec2.loader.exec_module(_mod)
fake_klt = _mod.fake_klt

REAL_PUT = run.store_mod.put_files  # captured before any test patches it


def _staged_assets():
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


class _TbIn:
    """The real lna-sparam-nf testbench with its evidence tree moved to tmp."""

    def __init__(self, tb, exp):
        self._tb, self.experiment_dir = tb, exp

    def __getattr__(self, name):
        return getattr(self._tb, name)


def _write_reports(tmp_path, tb):
    """One klt report per supply, 9 corners each, logs with every measurement."""
    reports = []
    for vdd in supply_points(tb.nominal_supply_v, tb.supply_tolerance):
        tag = f"{vdd:.2f}v"
        out = tmp_path / f"out_{tag}"
        out.mkdir()
        corners = []
        for c in resolve_corners(list(tb.corners)):
            for t in tb.temperatures_c:
                log = out / f"{c.name}_{t}.log"
                log.write_text("\n".join(f"m_{n} = 1.0" for n in tb.measure) + "\n")
                corners.append({"process": c.name, "temperature_c": t,
                                "artifacts": {"log": str(log)}, "runtime_s": 1.0})
        path = tmp_path / f"report_{tag}.json"
        path.write_text(json.dumps({"status": "ok", "corners": corners,
                                    "environment": _good_env(f"klt-sim-{tag}")}))
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
    monkeypatch.delenv("KLT_ARTIFACT_BROKER", raising=False)  # never the real store
    monkeypatch.setattr(run.harness_cli, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(run.harness_cli, "STAGE_DIR", tmp_path / "stage")
    monkeypatch.setattr(run.store_mod, "preflight", lambda *a, **k: None)
    objects = {}
    monkeypatch.setattr(
        run.store_mod, "put_files",
        lambda files, root, klt="klt": REAL_PUT(files, root, klt=klt, run=fake_klt(objects)))
    return tb


def _capture_record(monkeypatch):
    seen = {}

    def fake_build_record(*a, **k):
        seen.update(k)
        return {"status": "pass"}

    def fake_write_record(record, exp):
        p = exp / "records" / "TESTID.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")
        return p

    monkeypatch.setattr(run, "allocate_record_id", lambda *a, **k: "TESTID")
    monkeypatch.setattr(run, "build_record", fake_build_record)
    monkeypatch.setattr(run, "write_record", fake_write_record)
    monkeypatch.setattr(run, "write_netlist_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(run.stage1_tables, "render", lambda *a, **k: "")
    return seen


def _args(**kw):
    return argparse.Namespace(supersedes=kw.get("supersedes", ""),
                              supersedes_new_dut=kw.get("supersedes_new_dut", ""),
                              claim="", klt_cmd="klt")


# --- the new-core-revision branch (issue #250) -------------------------------


def test_new_dut_note_names_superseded_record_and_reason(local_install_matches, monkeypatch,
                                                         tmp_path):
    tb = local_install_matches
    seen = _capture_record(monkeypatch)

    def _boom(*a, **k):
        raise AssertionError("the agreement comparison must not run on a new core revision")

    monkeypatch.setattr(run.lna_nf, "compare_to_superseded", _boom)
    reports = _write_reports(tmp_path, tb)
    assert run.ingest(tb, reports, _args(supersedes_new_dut=OLD_RECORD)) == 0
    assert seen["supersedes"] == OLD_RECORD
    notes = "\n".join(seen["extensions"].notes)
    assert "NEW-CORE-REVISION RECORD (issue #250)" in notes
    assert OLD_RECORD in notes
    assert "stays valid as evidence for the earlier core" in notes
    assert "CORRECTION RECORD" not in notes
    assert "supersedes NOTHING" not in notes
    # The provenance note the bare/new-design path carries applies here too.
    assert "NF expression used (post-#22, corrected)" in notes


def test_new_dut_branch_does_not_weaken_the_correction_check(local_install_matches, monkeypatch,
                                                             tmp_path, capsys):
    """With --supersedes (correction) the comparison MUST still run and fold its
    problems into the refuse-to-write list: the new flag sits beside it, never
    in place of it."""
    tb = local_install_matches
    monkeypatch.setattr(run, "build_record",
                        lambda *a, **k: pytest.fail("correction must refuse before any record"))
    monkeypatch.setattr(run, "write_record",
                        lambda *a, **k: pytest.fail("correction must refuse before any record"))
    comparison = {
        "compared": 729,
        "worst": {"nf_f": 1e-9, "nf_db": 1e-9, "sparam_db": 1e-9, "k": 1e-9},
        "tolerances": {"nf_f": run.lna_nf.TOL_F, "sparam_db": run.lna_nf.TOL_DB,
                       "k": run.lna_nf.TOL_K},
        "problems": ["hbt_typ_27c_2.50v: deliberately injected disagreement"],
    }
    called = {}

    def fake_compare(new, old_dir):
        called["ran"] = True
        return comparison

    monkeypatch.setattr(run.lna_nf, "compare_to_superseded", fake_compare)
    reports = _write_reports(tmp_path, tb)
    assert run.ingest(tb, reports, _args(supersedes=OLD_RECORD)) == 1
    assert called.get("ran")
    err = capsys.readouterr().err
    assert "deliberately injected disagreement" in err
    assert "NO record written" in err


# --- the other two branches stay byte-identical ------------------------------


def test_correction_note_branch_unchanged(local_install_matches, monkeypatch, tmp_path, capsys):
    tb = local_install_matches
    seen = _capture_record(monkeypatch)
    comparison = {
        "compared": 729,
        "worst": {"nf_f": 1.2e-6, "nf_db": 1e-9, "sparam_db": 3e-7, "k": 2e-7},
        "tolerances": {"nf_f": run.lna_nf.TOL_F, "sparam_db": run.lna_nf.TOL_DB,
                       "k": run.lna_nf.TOL_K},
        "problems": [],
    }
    monkeypatch.setattr(run.lna_nf, "compare_to_superseded", lambda new, old_dir: comparison)
    reports = _write_reports(tmp_path, tb)
    assert run.ingest(tb, reports, _args(supersedes=OLD_RECORD)) == 0
    assert seen["supersedes"] == OLD_RECORD
    notes = "\n".join(seen["extensions"].notes)
    assert "CORRECTION RECORD (issue #22)" in notes and OLD_RECORD in notes
    assert "Comparison with the superseded logs" in notes
    assert "NEW-CORE-REVISION RECORD" not in notes
    assert "NEW-DESIGN RECORD" not in notes


def test_bare_ingest_still_says_supersedes_nothing(local_install_matches, monkeypatch, tmp_path):
    tb = local_install_matches
    seen = _capture_record(monkeypatch)
    reports = _write_reports(tmp_path, tb)
    assert run.ingest(tb, reports, _args()) == 0
    assert seen["supersedes"] == ""
    notes = "\n".join(seen["extensions"].notes)
    assert "NEW-DESIGN RECORD (issue #28)" in notes and "supersedes NOTHING" in notes
    assert "NEW-CORE-REVISION RECORD" not in notes
    assert "CORRECTION RECORD" not in notes


# --- flag surface -------------------------------------------------------------


def test_supersedes_flags_are_mutually_exclusive(tmp_path):
    report = tmp_path / "report_2.50v.json"
    report.write_text("{}")
    with pytest.raises(SystemExit):
        run.main(["ingest", str(report), "--supersedes", "A", "--supersedes-new-dut", "B"])
    with pytest.raises(SystemExit):
        run.main(["characterize", "--supersedes", "A", "--supersedes-new-dut", "B"])


def test_wait_for_capacity_defaults_to_600():
    args = run.build_parser().parse_args(["characterize"])
    assert args.wait_for_capacity == 600
    assert run.build_parser().parse_args(
        ["characterize", "--supersedes-new-dut", OLD_RECORD]).supersedes_new_dut == OLD_RECORD


def _stub_characterize(monkeypatch, tmp_path, cmds):
    class Done:
        returncode, stderr = 0, ""

    def fake_run(cmd, *a, **k):
        cmds.append(list(cmd))
        return Done()

    monkeypatch.setattr(run.subprocess, "run", fake_run)
    monkeypatch.setattr(run, "SCRATCH", tmp_path)
    monkeypatch.setattr(run.store_mod, "preflight", lambda *a, **k: None)
    monkeypatch.setattr(run, "ingest", lambda *a, **k: 0)
    return fake_run


def test_batch_submit_carries_wait_for_capacity(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "_pdk", lambda: FAKE_PDK)
    monkeypatch.setattr(run.pdkartifact, "verified_identity", lambda pdk, sim: IDENTITY)
    cmds = []
    _stub_characterize(monkeypatch, tmp_path, cmds)
    assert run.main(["characterize", "--backend", "batch"]) == 0
    sim_cmds = [c for c in cmds if "sim" in c]
    assert len(sim_cmds) == 3  # one per supply point
    for cmd in sim_cmds:
        assert "--wait-for-capacity" in cmd
        assert cmd[cmd.index("--wait-for-capacity") + 1] == "600"


def test_local_backend_submit_omits_wait_for_capacity(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "_pdk", lambda: FAKE_PDK)
    monkeypatch.setattr(run.pdkartifact, "verified_identity", lambda pdk, sim: IDENTITY)
    cmds = []
    _stub_characterize(monkeypatch, tmp_path, cmds)
    assert run.main(["characterize", "--backend", "local"]) == 0
    for cmd in (c for c in cmds if "sim" in c):
        assert "--wait-for-capacity" not in cmd
