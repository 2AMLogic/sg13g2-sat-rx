"""Round trip: records rendered by sim/harness/report.py ``render_markdown``
must parse with check_evidence_formats.py ``declared_native_matrix``.

The harness emits two wordings for the grid-size line (issue #81):
``N point full-factorial grid (...), M completed`` when the run covers the
bench's required process x temperature x supply product, and
``N point grid (subset of ...), M completed`` otherwise. The checker has to
accept both, or the first committed subset record fails the evidence-formats
CI job. These tests render with the real harness (standard library only, so
it imports in the checker job without extra dependencies) and parse with the
real checker, so the two cannot drift apart silently.

Run: python3 -m pytest .github/scripts/tests -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parents[1]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(REPO / "sim"))

import check_evidence_formats as chk  # noqa: E402
from harness import corners as C  # noqa: E402
from harness import report as R  # noqa: E402
from harness import testbench as T  # noqa: E402
from harness.pdk import Pdk  # noqa: E402
from harness.runner import PointResult  # noqa: E402

GIT = {"short": "abc1234", "branch": "b", "dirty": False}
RECORD_ID = "20260101-000000-abc1234"


def make_bench(root: Path) -> tuple[Path, T.Testbench]:
    exp = root / "sim" / "roundtrip-bench"
    tbdir = exp / "testbench"
    tbdir.mkdir(parents=True)
    (tbdir / "d.spice").write_text("R1 a b 1k\n")
    (tbdir / "tb.json").write_text(json.dumps({
        "name": "roundtrip", "netlist": "d.spice", "measure": {"gain": "1"},
        "nominal_supply_v": 2.5, "corners": ["hbt"], "claim": "round-trip claim",
    }))
    (exp / "README.md").write_text("# roundtrip-bench\n\n## Cold start\n\n```\ntrue\n```\n")
    return exp, T.load(exp)


def format_problems(root: Path) -> list[str]:
    """check_format minus the PDK-'unknown' finding: the fake Pdk used here has
    no SOURCES file, so the real renderer prints 'unknown' (the T1 item 9 gap)."""
    return [m for m in chk.check_format(root).items if "names the PDK as 'unknown'" not in m]


def render(root: Path, points, subset_reason: str = "") -> tuple[Path, dict, str]:
    exp, tb = make_bench(root)
    res = [PointResult(point=p, status="ok", measurements={"gain": 1.0 + i}) for i, p in enumerate(points)]
    pdk = Pdk(name="fake", path=root, variant="v", source="test", model_lib_rel="m.lib")
    rec = R.build_record(tb, pdk, points, res, "ngspice-0", root, RECORD_ID,
                         "2026-01-01T00:00:00+00:00", 1.0, subset_reason=subset_reason, git=GIT)
    return exp, rec, R.render_markdown(rec)


def full_grid():
    return C.build_grid(C.resolve_corners(["hbt"]), [-40, 27, 125], [2.25, 2.5, 2.75])


def subset_grid():
    return C.build_grid(C.resolve_corners(["hbt_typ"]), [27], [2.5])


def write_artifacts(exp: Path, rec: dict, tb_points) -> Path:
    R.write_record(rec, exp)
    R.write_netlist_snapshot(T.load(exp), exp, rec["record_id"])
    logs = exp / "corners" / rec["record_id"]
    logs.mkdir(parents=True)
    for p in tb_points:
        (logs / f"{p.corner_id}.log").write_text("log\n")
    return logs


def test_full_record_line_parses(tmp_path):
    _, rec, md = render(tmp_path, full_grid())
    assert rec["matrix"]["full"] and "27 point full-factorial grid" in md
    processes, temps, supplies, n_total, n_done = chk.declared_native_matrix(md)
    assert sorted(processes) == ["hbt_bcs", "hbt_typ", "hbt_wcs"]
    assert temps == [-40.0, 27.0, 125.0] and supplies == [2.25, 2.5, 2.75]
    assert (n_total, n_done) == (27, 27)


def test_subset_record_line_parses(tmp_path):
    _, rec, md = render(tmp_path, subset_grid(), subset_reason="debug probe")
    assert not rec["matrix"]["full"]
    assert "full-factorial" not in md and "1 point grid (subset of" in md
    assert chk.declared_native_matrix(md) == (["hbt_typ"], [27.0], [2.5], 1, 1)


def test_rendered_subset_record_passes_the_whole_format_check(tmp_path):
    exp, rec, _ = render(tmp_path, subset_grid(), subset_reason="debug probe")
    write_artifacts(exp, rec, subset_grid())
    assert format_problems(tmp_path) == []


def test_rendered_full_record_passes_the_whole_format_check(tmp_path):
    exp, rec, _ = render(tmp_path, full_grid())
    write_artifacts(exp, rec, full_grid())
    assert format_problems(tmp_path) == []


def test_subset_wording_keeps_the_artifact_and_count_checks(tmp_path):
    """Accepting the subset wording must not relax anything downstream: a
    missing corner log and a count that disagrees with the declared lists are
    still reported for a subset record."""
    exp, rec, _ = render(tmp_path, subset_grid(), subset_reason="debug probe")
    logs = write_artifacts(exp, rec, subset_grid())
    (logs / f"{subset_grid()[0].corner_id}.log").unlink()
    assert any("missing declared corner identity" in m for m in chk.check_format(tmp_path).items)

    md = exp / "records" / f"{RECORD_ID}.md"
    md.write_text(md.read_text().replace("1 point grid (subset of", "2 point grid (subset of"))
    assert any("declares 2 grid points" in m for m in chk.check_format(tmp_path).items)


def test_non_cartesian_subset_is_still_rejected(tmp_path):
    """A diagonal run renders with the subset wording, but its declared
    Process/Temperature/Supply lists expand to 27 identities, not 3. The
    checker keeps refusing it rather than trusting the wording."""
    diag = [C.PvtPoint(C.CORNERS["hbt_typ"], -40, 2.25), C.PvtPoint(C.CORNERS["hbt_bcs"], 27, 2.5),
            C.PvtPoint(C.CORNERS["hbt_wcs"], 125, 2.75)]
    _, rec, md = render(tmp_path, diag, subset_reason="diagonal")
    assert not rec["matrix"]["full"]
    *_, n_total, _ = chk.declared_native_matrix(md)
    assert n_total == 3
    exp = tmp_path / "sim" / "roundtrip-bench"
    write_artifacts(exp, rec, diag)
    assert any("declares 3 grid points but its process x temperature x supply lists expand to 27" in m
               for m in chk.check_format(tmp_path).items)


def test_unrecognised_grid_line_is_reported():
    text = "- Process: hbt_typ\n- Temperature: 27 C\n- Supply: 2.50 V\n- 1 point sampling, 1 completed\n"
    assert chk.declared_native_matrix(text)[3:] == (None, None)
