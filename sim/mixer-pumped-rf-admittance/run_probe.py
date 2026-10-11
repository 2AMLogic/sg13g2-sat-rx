#!/usr/bin/env python3
"""Pumped RF-port admittance probe + record writer (issue #111).

    python3 sim/mixer-pumped-rf-admittance/run_probe.py --controls-only
                                    # qualification: known-answer fixtures only, no DUT, no record
    python3 sim/mixer-pumped-rf-admittance/run_probe.py --no-write
                                    # controls + DUT once, print the record, write nothing
    python3 sim/mixer-pumped-rf-admittance/run_probe.py
                                    # controls + DUT once, append a record (+ probe-logs/<id>/)
    python3 sim/mixer-pumped-rf-admittance/run_probe.py --reparse probe-logs/<id>
                                    # re-derive a recorded frozen log under the thresholds stored in
                                    # records/<id>-<STATUS>.json; fails if the classification disagrees
    python3 sim/mixer-pumped-rf-admittance/run_probe.py --reparse probe-logs/<id> --sabotage omit_image
                                    # apply an extraction sabotage to a frozen log; controls must FAIL
    python3 sim/mixer-pumped-rf-admittance/run_probe.py --reparse <dir> --declaration <thresholds file>
                                    # replay an UNRECORDED (exploratory) log; the declaration is required

Runs ONE ngspice process locally at one nominal point (hbt_typ / 27 C / 2.50 V, the
existing placeholder mixer as an exploratory DUT, its LO drive a probe setting). The
process steps through eight short `.tran` runs in its own control block (LO-only baseline,
two perturbation phases, both phases at half amplitude, and baseline + both phases at half
the time step). No grid, no corner loop, no seed campaign; a band/PVT campaign would go
through `klt sim` and is out of scope here (README "Campaign path").

The executable must be the pinned ngspice major (sim/pdk-artifact.json). A missing or
different binary yields a CAPABILITY_UNAVAILABLE record that carries no probe result.
A record is refused while thresholds.json is uncommitted or modified: the classification
thresholds must be declared (committed) before the DUT result they judge.

Writes, append-only (exclusive create; an existing record is never touched):
  probe-logs/<id>/deck.spice      the composed deck exactly as run
  probe-logs/<id>/stdout.txt      full ngspice stdout
  probe-logs/<id>/stderr.txt      full ngspice stderr
  probe-logs/<id>/inventory.json  parsed marks + the full evaluation
  records/<id>-<STATUS>.md/.json  the record

Exit status: 0 when a record (any status) was produced or a print-only run finished (a
sabotage whose controls FAIL is also 0: failing is its job); 1 on a parse defect or a
refused record or a refused replay (missing, ambiguous, mismatched or malformed record /
declaration); 2 when a sabotaged control unexpectedly PASSES or the unsabotaged controls
fail in --controls-only mode; 3 when a replayed recorded log's recomputed classification
disagrees with the classification stored in its record.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM_DIR = HERE.parent
REPO = SIM_DIR.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SIM_DIR))

import pumped as P  # noqa: E402

TEMPLATE = HERE / "probe" / "admittance_probe.spice"
CONTROL_RC = HERE / "controls" / "rc_known_answer.spice"
CONTROL_MD = HERE / "controls" / "modulated_known_answer.spice"
PLACEHOLDER = SIM_DIR / "mixer-conversion-iip3" / "testbench" / "mixer_ce_placeholder.spice"
PDK_ARTIFACT = SIM_DIR / "pdk-artifact.json"
RECORDS = HERE / "records"
PROBE_LOGS = HERE / "probe-logs"
BENCH = "mixer-pumped-rf-admittance"

MANUAL_URL = "https://ngspice.sourceforge.io/docs/ngspice-46-manual.pdf"
MANUAL_SHA256 = "b5bc7c4f3aac00e670b01b1d1ab64ec87055a491014af1de828764bf98faf766"
REFERENCES = {
    "method": f"ngspice User's Manual v46 ({MANUAL_URL}, sha256 {MANUAL_SHA256}), chapter 15 "
              "'Transient analysis' (.tran) and chapter 13 'Measurements' (.meas INTEG); "
              "sideband-coupled (conversion-matrix) port model as in pumped.py; probe marks are the evidence",
    "dr_0004": "spec/decision-records/0004-lna-mixer-interface-convention.md (proposed; row 5 under "
               "Option B needs an LO-on mixer RF-port impedance method; falsifier 3)",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pinned_major() -> int:
    return int(json.loads(PDK_ARTIFACT.read_text())["ngspice"]["major"])


def ngspice_info(exe: str) -> dict:
    out = subprocess.run([exe, "-v"], capture_output=True, text=True, check=False).stdout
    line = next((ln.strip(" *") for ln in out.splitlines() if "ngspice-" in ln), "unknown")
    m = re.search(r"ngspice-(\d+)", line)
    return {"path": exe, "version": line.strip(), "major": int(m.group(1)) if m else None,
            "sha256": sha256(Path(exe).resolve())}


def pdk_info() -> dict:
    from harness.pdk import find_pdk  # noqa: WPS433
    p = find_pdk(SIM_DIR)
    fv = p.path.parent / ".fetched-version"
    fv2 = p.path / ".fetched-version"
    ver = (fv.read_text().strip() if fv.is_file() else
           fv2.read_text().strip() if fv2.is_file() else "unknown")
    models = p.model_lib.parent
    return {"path": str(p.path), "fetched_version": ver, "model_lib": str(p.model_lib),
            "section": "hbt_typ",
            "sha256": {"cornerHBT.lib": sha256(p.model_lib),
                       "sg13g2_hbt_mod.lib": sha256(models / "sg13g2_hbt_mod.lib")},
            "device": "npn13G2 (subckt) -> npn13G2_NX_vbic, VBIC level=9, Nx=4 in the placeholder"}


def pdk_integrity(banner: str) -> dict:
    from harness import pdkartifact  # noqa: WPS433
    from harness.pdk import find_pdk  # noqa: WPS433
    rep = pdkartifact.verify(find_pdk(SIM_DIR), SIM_DIR, banner, require_ngspice=True)
    return {"gate": "sim/harness/pdkartifact.py verify(require_ngspice=True)", "ok": rep.ok,
            "problems": list(rep.problems), "notes": list(rep.notes)}


def _git(*a) -> str:
    return subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True).stdout.strip()


def git_info() -> dict:
    return {"commit": _git("rev-parse", "HEAD"), "dirty": bool(_git("status", "--porcelain"))}


def thresholds_provenance() -> dict:
    rel = str(P.THRESHOLDS_PATH.relative_to(REPO))
    return {"file": rel, "sha256": sha256(P.THRESHOLDS_PATH),
            "commit": _git("log", "-1", "--format=%H", "--", rel) or None,
            "dirty": bool(_git("status", "--porcelain", "--", rel))}


def new_record_id(short: str) -> str:
    when = _dt.datetime.now(_dt.timezone.utc)
    while True:
        rid = f"{when.strftime('%Y%m%d-%H%M%S')}-{short}"
        if not list(RECORDS.glob(f"{rid}*")) and not (PROBE_LOGS / rid).exists():
            return rid
        when += _dt.timedelta(seconds=1)


def write_excl(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x") as fh:
        fh.write(text)


# ---- deck composition ----------------------------------------------------------------------

def _fmt(x: float) -> str:
    return f"{x:.10g}"


SIG_EXPR = {"v": "v({port})", "i": "i({sense})", "t": "v({term})"}


def run_block(name: str, with_dut: bool) -> str:
    a, phu, phl, refined = P.RUNS[name]
    tmax = P.TMAX_REFINED if refined else P.TMAX
    tstop = P.T_STOP_REFINED if refined else P.T_STOP
    lines = [f"* ---- run {name}: amplitude={_fmt(a)} phu={_fmt(phu)} phl={_fmt(phl)} tmax={_fmt(tmax)} ----",
             f"alterparam apu={_fmt(a)}", f"alterparam apl={_fmt(a)}",
             f"alterparam phu={_fmt(phu)}", f"alterparam phl={_fmt(phl)}"]
    if with_dut:
        lines.append("alterparam vrf=0")
    lines += ["reset", f"tran {_fmt(tmax)} {_fmt(tstop)} 0 {_fmt(tmax)}",
              "let npts = length(time)", f'echo "MARK R_{name}_points=$&npts"']
    for fx, (port, sense, term, _z0) in P.FIXTURES.items():
        if fx == "dut" and not with_dut:
            continue
        for sig in P.fixture_signals(fx):
            expr = SIG_EXPR[sig].format(port=port, sense=sense, term=term)
            for sb in P.SIDEBANDS:
                lines += [f"let pc = {expr}*cos(w{sb}*time)", f"let ps = {expr}*sin(w{sb}*time)"]
                for win in P.run_windows(name):
                    lo, hi = (_fmt(x) for x in P.WINDOWS[win])
                    kc, ks = (P.mark_key(fx, sig, name, win, sb, cs) for cs in ("c", "s"))
                    lines += [f"meas tran {kc} INTEG pc from={lo} to={hi}",
                              f"meas tran {ks} INTEG ps from={lo} to={hi}",
                              f'echo "MARK {kc}=$&{kc} {ks}=$&{ks}"']
    return "\n".join(lines)


DUT_BLOCK = """
* ---- DUT: the placeholder, included verbatim, and its Norton perturbation ----
.lib "{model_lib}" hbt_typ
.temp 27
.param vdd_val=2.5
.include "{placeholder}"
Ipu 0 pj DC 0 SIN(0 {{apu/z0}} 19.45e9 0 0 {{phu}})
Ipl 0 pj DC 0 SIN(0 {{apl/z0}} 17.45e9 0 0 {{phl}})
Vpsense pj prf DC 0
"""


def compose_deck(model_lib: str | None, with_dut: bool = True) -> str:
    runs = "\n\n".join(run_block(n, with_dut) for n in P.RUNS)
    dut = (DUT_BLOCK.format(model_lib=model_lib, placeholder=PLACEHOLDER) if with_dut else
           "\n* ---- controls-only deck: no DUT ----\n.temp 27\n")
    deck = TEMPLATE.read_text().replace("{dut_block}", dut).replace("{runs}", runs)
    # Control fragments are inlined (not .include'd) so deck.spice alone reproduces the run.
    for token, path in (("{control_rc}", CONTROL_RC), ("{control_md}", CONTROL_MD)):
        inline = (f"* ---- inlined from sim/{BENCH}/controls/{path.name} ----\n{path.read_text()}"
                  f"* ---- end inlined control ----\n")
        deck = deck.replace(f'.include "{token}"', inline)
    return deck


# ---- rendering ---------------------------------------------------------------------------------

def _mp(v) -> str:
    """complex [re, im] -> 'mag mS / phase deg'."""
    import cmath
    import math
    z = complex(v[0], v[1])
    return f"{abs(z) * 1e3:.4g} mS / {math.degrees(cmath.phase(z)) if z else 0.0:.2f} deg"


def integrity_line(env: dict) -> str:
    integ = env.get("pdk_integrity")
    if not isinstance(integ, dict):
        return ""
    verdict = "OK" if integ.get("ok") else "FAILED"
    detail = "; ".join(list(integ.get("notes") or []) + list(integ.get("problems") or []))
    return (f"- Model integrity gate (`sim/harness/pdkartifact.py`, run before the simulator): {verdict}"
            f"{'; ' + detail if detail else ''}\n")


#: The checker requires SCOPE_MD_MARKERS verbatim in every record's Markdown.
SCOPE_MD_MARKERS = ("- **Scope: method-feasibility evidence only.**",
                    "**no claim of `spec/target-spec.md` row 5 compliance**")
SCOPE_MD = (f"{SCOPE_MD_MARKERS[0]} One nominal point of an exploratory\n"
            "  placeholder DUT. This record asks whether the LO-on (pumped) RF-port admittance can be\n"
            "  extracted with stated limits. It makes\n"
            f"  {SCOPE_MD_MARKERS[1]},\n"
            "  reports no mixer or cascade noise figure, selects no topology, matching network or LO\n"
            "  drive, and neither ratifies nor reverses DR-0004.")


def render_md(rid: str, status: str, reasons: list, ev: dict, thr: dict, thr_prov: dict, env: dict) -> str:
    dut = ev["dut"]
    ctl = ev["controls"]
    yrows = "\n".join(f"| `Y_{e}` | {_mp(dut['y'][e])} |" for e in P.ELEMENTS)
    nrows = "\n".join(f"| {n} | {'pass' if c['pass'] else 'FAIL'} | "
                      f"{ {k: v for k, v in c.items() if k != 'pass'} } |" for n, c in dut["checks"].items())
    crows = "\n".join(f"| {n} | {'pass' if c['pass'] else 'FAIL'} | "
                      f"{ {k: v for k, v in c.items() if k != 'pass'} } |" for n, c in ctl["checks"].items())
    trows = "\n".join(f"| `{k}` | {v:g} |" for k, v in thr.items())
    return f"""# {BENCH} record {rid}-{status}

- **Status: {status}**
{SCOPE_MD}
- Nominal point: `hbt_typ` / 27 C / VDD = 2.50 V; placeholder
  `sim/mixer-conversion-iip3/testbench/mixer_ce_placeholder.spice` (included verbatim), LO
  18.45 GHz at the placeholder's own `vlo` = 0.08 V EMF (a probe setting, not a qualified drive;
  issue #68). Sidebands f_u = 19.45 GHz, f_l = 17.45 GHz (IF 1 GHz).
- Port: node `prf` looking into `Cin_rf`, terminated by the placeholder's own 50 ohm `Rrf`; current
  positive into the mixer. The matrix is conditional on that termination at every other mixing
  frequency.

## Reasons

{chr(10).join('- ' + r for r in reasons)}

## Pumped port admittance (retained window, primary phases p1/p2)

I_u = Y_uu V_u + Y_ul conj(V_l);  I_l = Y_lu conj(V_u) + Y_ll V_l

| element | magnitude / phase |
|---|---|
{yrows}

- kappa = max(|Y_ul|/|Y_uu|, |Y_lu|/|Y_ll|) = {dut['kappa']:.4g}; uncertainty {dut['kappa_uncertainty']:.3g};
  scalar bound {thr['kappa_scalar_max']:g}
- Model-free discriminator: the scalar I/V of phase p1 and phase p2 differ by
  {dut['scalar_phase_spread']:.4g} (relative)

## Numerical checks (DUT)

| check | result | detail |
|---|---|---|
{nrows}

## Known-answer controls (same runs, same extraction)

| check | result | detail |
|---|---|---|
{crows}

## Thresholds (declared before the DUT result)

`{thr_prov['file']}` sha256 `{thr_prov['sha256']}`, last changed in commit `{thr_prov['commit']}`.

| threshold | value |
|---|---|
{trows}

## Provenance

- ngspice: `{env['ngspice']['path']}` -- {env['ngspice']['version']}, sha256 `{env['ngspice']['sha256']}`
- PDK: `{env['pdk']['path']}` (.fetched-version {env['pdk']['fetched_version']}), section `hbt_typ`;
  cornerHBT.lib `{env['pdk']['sha256']['cornerHBT.lib']}`, sg13g2_hbt_mod.lib
  `{env['pdk']['sha256']['sg13g2_hbt_mod.lib']}`; {env['pdk']['device']}
{integrity_line(env)}- Placeholder sha256 `{env['placeholder_sha256']}`; pdk-artifact.json sha256 `{env['pdk_artifact_sha256']}`
- Repo commit `{env['git']['commit']}` (dirty: {env['git']['dirty']}); host {env['host']}
- Probe logs: `probe-logs/{rid}/`
- Command: `python3 sim/{BENCH}/run_probe.py`
"""


def render_unavailable_md(rid: str, status: str, failed: str) -> str:
    return f"""# {BENCH} record {rid}-{status}

- **Status: {status}**
{SCOPE_MD_MARKERS[0]} No probe ran: no admittance, no classification,
  {SCOPE_MD_MARKERS[1]}, no noise figure, and nothing about
  DR-0004. This status never establishes that the method is impossible.
- Failed check: {failed}

A later record produced on a host that has the pinned executable and passing model-integrity
gate supersedes this one; this file is not edited or removed (records are append-only).
"""


# ---- replay of a frozen probe log (issue #129) ---------------------------------------------------------

#: The declaration keys a replay needs: exactly the keys a record stores (the evidence checker's
#: PRA_THRESHOLDS); a declaration with more or fewer keys is malformed, never silently completed.
REQUIRED_THRESHOLDS = ("control_mag_rel_tol", "control_phase_tol_deg", "control_null_rel_tol", "cond_max",
                       "halving_rel_tol", "window_rel_tol", "timestep_rel_tol", "response_to_baseline_min",
                       "kappa_scalar_max")
RUN_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{7,40}$")
RECORD_JSON_RE = r"^{rid}-([A-Za-z_-]+)\.json$"
REPLAYABLE_STATUSES = (P.S_SCALAR, P.S_MATRIX, P.S_INCONCLUSIVE)

#: exit status when the recomputed classification disagrees with the record's stored one
EXIT_DISAGREE = 3


class ReplayError(Exception):
    """A replay input (log, record or declaration) is missing, ambiguous, mismatched or malformed."""


def _check_threshold_values(vals: object, where: str) -> dict:
    if not isinstance(vals, dict):
        raise ReplayError(f"{where}: thresholds are not an object")
    missing = sorted(set(REQUIRED_THRESHOLDS) - set(vals))
    extra = sorted(set(vals) - set(REQUIRED_THRESHOLDS))
    if missing or extra:
        raise ReplayError(f"{where}: thresholds must carry exactly {', '.join(REQUIRED_THRESHOLDS)} "
                          f"(missing {missing}, unexpected {extra})")
    for k, v in vals.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
            raise ReplayError(f"{where}: threshold {k} = {v!r} is not a positive finite number")
    return dict(vals)


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO))
    except ValueError:
        return str(path)


def resolve_replay(log_dir: Path, declaration: Path | None = None) -> dict:
    """Decide which declaration judges the frozen log in ``log_dir``.

    Recorded log (``log_dir`` is ``probe-logs/<id>/`` and exactly one ``records/<id>-<STATUS>.json``
    exists): the record's stored ``thresholds`` -- the declaration that judged it -- after checking
    the run identity and the record/package relationship. An explicit ``declaration`` is refused
    here: the historical declaration is authoritative, and a changed one needs a new record.

    Unrecorded (exploratory) log: an explicit ``declaration`` (a thresholds.json-format file) is
    required; today's thresholds.json is never borrowed silently.

    Returns {"mode", "run_id", "log_dir", "thresholds", "declaration", "record"?, "stored_classification"?}.
    Raises ReplayError for missing, ambiguous, mismatched or malformed inputs.
    """
    d = log_dir if log_dir.is_absolute() else HERE / log_dir
    if not d.is_dir():
        raise ReplayError(f"probe-log directory {d} does not exist")
    for name in ("stdout.txt", "stderr.txt"):
        if not (d / name).is_file():
            raise ReplayError(f"probe-log directory {d} lacks {name}")
    rid = d.resolve().name
    candidates = []
    if RUN_ID_RE.match(rid) and RECORDS.is_dir():
        pat = re.compile(RECORD_JSON_RE.format(rid=re.escape(rid)))
        candidates = sorted(p for p in RECORDS.iterdir() if p.is_file() and pat.match(p.name))

    if not candidates:
        if declaration is None:
            raise ReplayError(
                f"no record records/{rid}-<STATUS>.json for this log: an unrecorded (exploratory) log "
                "needs an explicit --declaration <thresholds file>; the current thresholds.json is "
                "never borrowed silently")
        dp = declaration if declaration.is_absolute() else Path.cwd() / declaration
        if not dp.is_file():
            raise ReplayError(f"declaration {declaration} does not exist")
        try:
            data = json.loads(dp.read_text())
        except (OSError, ValueError) as exc:
            raise ReplayError(f"declaration {declaration} is not valid JSON ({exc})") from None
        vals = data.get("values") if isinstance(data, dict) else None
        thr = _check_threshold_values(vals, f"declaration {declaration}")
        return {"mode": "exploratory", "run_id": rid, "log_dir": _rel(d), "thresholds": thr,
                "declaration": {"source": "explicit --declaration", "file": _rel(dp), "sha256": sha256(dp)}}

    if len(candidates) > 1:
        raise ReplayError(f"ambiguous: {len(candidates)} records claim run {rid}: "
                          + ", ".join(p.name for p in candidates))
    rec_path = candidates[0]
    where = _rel(rec_path)
    if declaration is not None:
        raise ReplayError(f"run {rid} is recorded in {where}; its stored declaration judges the replay. "
                          "--declaration is only for unrecorded (exploratory) logs; a changed declaration "
                          "needs a new record that says why")
    try:
        rec = json.loads(rec_path.read_text())
    except (OSError, ValueError) as exc:
        raise ReplayError(f"{where} is not valid JSON ({exc})") from None
    if not isinstance(rec, dict):
        raise ReplayError(f"{where} is not a JSON object")
    status = re.compile(RECORD_JSON_RE.format(rid=re.escape(rid))).match(rec_path.name).group(1)
    if rec.get("record_id") != rid:
        raise ReplayError(f"{where}: record_id {rec.get('record_id')!r} does not match the log's run id {rid!r}")
    if rec.get("status") != status:
        raise ReplayError(f"{where}: JSON status {rec.get('status')!r} does not match the file name status {status!r}")
    if status not in REPLAYABLE_STATUSES:
        raise ReplayError(f"{where}: status {status!r} carries no probe result to replay")
    if rec.get("classification") != status:
        raise ReplayError(f"{where}: classification {rec.get('classification')!r} does not match status {status!r}")
    expected_logs = f"sim/{BENCH}/probe-logs/{rid}/"
    if rec.get("probe_logs") != expected_logs:
        raise ReplayError(f"{where}: probe_logs {rec.get('probe_logs')!r} must be {expected_logs!r}")
    if d.resolve() != (PROBE_LOGS / rid).resolve():
        raise ReplayError(f"run {rid} is recorded in {where}, whose package is probe-logs/{rid}/, but the "
                          f"log given is {d}: replay the record's own package")
    thr = _check_threshold_values(rec.get("thresholds"), f"{where}")
    prov = rec.get("thresholds_provenance")
    if not isinstance(prov, dict):
        raise ReplayError(f"{where}: thresholds_provenance is missing")
    return {"mode": "recorded", "run_id": rid, "log_dir": _rel(d), "thresholds": thr,
            "record": where, "stored_classification": status,
            "declaration": {"source": f"{where} 'thresholds' (the run's own declaration)",
                            "file": prov.get("file"), "sha256": prov.get("sha256"),
                            "commit": prov.get("commit")}}


def replay(log_dir: Path, declaration: Path | None, sabotage: str | None) -> int:
    """--reparse: re-derive a frozen log under its resolved declaration (no simulator)."""
    try:
        res = resolve_replay(log_dir, declaration)
    except ReplayError as exc:
        print(f"replay refused: {exc}", file=sys.stderr)
        return 1
    d = log_dir if log_dir.is_absolute() else HERE / log_dir
    parsed = P.parse_log((d / "stdout.txt").read_text(), (d / "stderr.txt").read_text())
    ev = P.evaluate(parsed, res["thresholds"], sabotage)
    used = {k: res[k] for k in ("mode", "run_id", "log_dir", "record", "declaration") if k in res}
    used["thresholds"] = res["thresholds"]
    if sabotage:
        ok, failing = sabotage_verdict(ev, sabotage)
        print(json.dumps({"replay": used, "sabotage": sabotage, "failing_control_checks": failing}, indent=2))
        return 0 if ok else 2
    out = {"replay": used, "status": ev["status"], "reasons": ev["reasons"]}
    rc = 0
    if res["mode"] == "recorded":
        agree = ev["status"] == res["stored_classification"]
        out["classification_check"] = {"stored": res["stored_classification"], "recomputed": ev["status"],
                                       "agree": agree}
        if not agree:
            rc = EXIT_DISAGREE
    out["evaluation"] = ev
    print(json.dumps(out, indent=2, default=str))
    if rc:
        print(f"ERROR: recomputed classification {ev['status']!r} disagrees with the stored "
              f"{res['stored_classification']!r} of {res['record']}", file=sys.stderr)
    return rc


# ---- main ----------------------------------------------------------------------------------------------

def sabotage_verdict(ev: dict, sabotage: str) -> tuple[bool, list[str]]:
    """(ok, failing checks): ok when the sabotaged controls FAIL on an expected measured check."""
    failing = sorted(n for n, c in ev["controls"]["checks"].items() if not c["pass"])
    return bool(set(failing) & P.EXPECTED_FAILING[sabotage]), failing


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--controls-only", action="store_true",
                    help="known-answer fixtures only (no DUT); prints the control verdict; never writes a record")
    ap.add_argument("--ngspice", default=os.environ.get("NGSPICE", "ngspice"))
    ap.add_argument("--reparse", type=Path, help="probe-logs/<id> directory to re-derive (no simulator)")
    ap.add_argument("--sabotage", choices=sorted(P.SABOTAGES),
                    help="extraction sabotage; expects the controls to FAIL; never writes a record")
    ap.add_argument("--allow-unpinned", action="store_true",
                    help="run a non-pinned ngspice for exploration; never writes a record")
    ap.add_argument("--declaration", type=Path,
                    help="with --reparse of an UNRECORDED (exploratory) log only: the thresholds file "
                         "(thresholds.json format) that judges it; a recorded log always uses the "
                         "thresholds stored in its record")
    ap.add_argument("--timeout", type=int, default=1800)
    args = ap.parse_args(argv)

    if args.declaration and not args.reparse:
        ap.error("--declaration only applies to --reparse")
    if args.reparse:
        return replay(args.reparse, args.declaration, args.sabotage)
    thr = P.load_thresholds()

    no_write = args.no_write or args.controls_only or bool(args.sabotage) or args.allow_unpinned
    with_dut = not (args.controls_only or args.sabotage)
    git = git_info()
    env = {"host": platform.node(), "platform": platform.platform(), "python": sys.version.split()[0],
           "git": git, "placeholder_sha256": sha256(PLACEHOLDER), "pdk_artifact_sha256": sha256(PDK_ARTIFACT)}
    rid = new_record_id((git["commit"] or "unknown")[:7])
    thr_prov = thresholds_provenance()
    if not no_write and (thr_prov["dirty"] or not thr_prov["commit"]):
        print("refusing to write a record: thresholds.json is uncommitted or modified; the thresholds "
              "must be committed before the DUT result they judge", file=sys.stderr)
        return 1

    exe = shutil.which(args.ngspice)
    info = ngspice_info(exe) if exe else None
    failed = None
    if exe is None:
        failed = f"shutil.which({args.ngspice!r}) is None"
    elif info["major"] != pinned_major() and not args.allow_unpinned:
        failed = (f"pinned ngspice-{pinned_major()} (sim/pdk-artifact.json) not found: {args.ngspice!r} "
                  f"resolves to {exe} = {info['version']!r}")
    if failed is None and with_dut:
        env["ngspice"] = info
        env["pdk"] = pdk_info()
        env["pdk_integrity"] = pdk_integrity(info["version"])
        if not env["pdk_integrity"]["ok"] and not args.allow_unpinned:
            failed = ("PDK model integrity gate failed (sim/harness/pdkartifact.py): "
                      + "; ".join(env["pdk_integrity"]["problems"]))
    if failed:
        status = P.S_UNAVAILABLE
        rec = {"record_id": rid, "status": status,
               "reasons": ["pinned simulator or model integrity not available on this host; "
                           "this status never establishes that the method is impossible"],
               "failed_check": failed, "scope": P.SCOPE, "environment": env}
        print(json.dumps(rec, indent=2))
        if not no_write:
            write_excl(RECORDS / f"{rid}-{status}.json", json.dumps(rec, indent=2) + "\n")
            write_excl(RECORDS / f"{rid}-{status}.md", render_unavailable_md(rid, status, failed))
            print(f"wrote records/{rid}-{status}.md")
        return 0 if not args.controls_only else 2

    deck = compose_deck(env.get("pdk", {}).get("model_lib"), with_dut)
    work = PROBE_LOGS / rid if not no_write else HERE / "_build" / rid
    work.mkdir(parents=True, exist_ok=False)
    (work / "deck.spice").write_text(deck)
    proc = subprocess.run([exe, "-b", "deck.spice"], cwd=work, capture_output=True, text=True,
                          timeout=args.timeout, check=False)
    (work / "stdout.txt").write_text(proc.stdout)
    (work / "stderr.txt").write_text(proc.stderr)
    env["ngspice_exit"] = proc.returncode
    parsed = P.parse_log(proc.stdout, proc.stderr)
    ev = P.evaluate(parsed, thr, args.sabotage)

    if args.sabotage:
        ok, failing = sabotage_verdict(ev, args.sabotage)
        print(json.dumps({"sabotage": args.sabotage, "failing_control_checks": failing}, indent=2))
        if not ok:
            print(f"ERROR: sabotage '{args.sabotage}' did not fail an expected control check", file=sys.stderr)
            return 2
        print(f"sabotage '{args.sabotage}': controls FAILED as required")
        return 0
    if args.controls_only:
        print(json.dumps({"controls_pass": ev["controls"]["pass"],
                          "checks": ev["controls"]["checks"]}, indent=2, default=str))
        print(f"work dir (not evidence): {work}")
        return 0 if ev["controls"]["pass"] else 2

    status, reasons = ev["status"], ev["reasons"]
    (work / "inventory.json").write_text(json.dumps({"parsed": parsed, "evaluation": ev}, indent=2) + "\n")
    rec = {"record_id": rid, "status": status, "reasons": reasons, "scope": P.SCOPE,
           "nominal_point": {"corner": "hbt_typ", "temp_c": 27, "vdd_v": 2.5, "lo_hz": P.F_LO,
                             "if_hz": P.F_IF, "f_u_hz": P.F_U, "f_l_hz": P.F_L, "vlo_emf_v": 0.08,
                             "note": "LO drive is the placeholder's own value, a probe setting (issue #68)"},
           "port": {"node": "prf", "into": "Cin_rf (placeholder RF coupling capacitor)",
                    "termination": "placeholder Rrf = 50 ohm to its zeroed RF source",
                    "current_direction": "positive into the mixer",
                    "perturbation": f"Norton current per sideband, EMF {P.A_EMF:g} V equivalent; half amplitude for the halving check"},
           "thresholds": thr, "thresholds_provenance": thr_prov,
           "classification": status, "evaluation": ev, "references": REFERENCES,
           "probe_logs": f"sim/{BENCH}/probe-logs/{rid}/", "environment": env}
    md = render_md(rid, status, reasons, ev, thr, thr_prov, env)
    if no_write:
        print(md)
        return 0
    write_excl(RECORDS / f"{rid}-{status}.json", json.dumps(rec, indent=2) + "\n")
    write_excl(RECORDS / f"{rid}-{status}.md", md)
    print(f"wrote records/{rid}-{status}.md")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except P.ProbeError as exc:
        print(f"parse defect, no record written: {exc}", file=sys.stderr)
        sys.exit(1)
