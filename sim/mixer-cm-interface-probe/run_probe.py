#!/usr/bin/env python3
"""Interface probe + record writer for a mixer conversion-matrix NF method (issue #89).

    python3 sim/mixer-cm-interface-probe/run_probe.py            # probe once, write a record
    python3 sim/mixer-cm-interface-probe/run_probe.py --no-write # probe once, print only
    python3 sim/mixer-cm-interface-probe/run_probe.py --reparse probe-logs/<id>
                                                                 # re-derive status from a committed
                                                                 # log (no simulator)
    python3 sim/mixer-cm-interface-probe/run_probe.py --sabotage image_sign
                                                                 # break the known-answer control; it
                                                                 # must FAIL (never writes a record)
    python3 sim/mixer-cm-interface-probe/run_probe.py --allow-unpinned --no-write
                                                                 # exploratory run on a non-pinned
                                                                 # ngspice (never writes a record)

Runs ONE ngspice process locally at one nominal point (hbt_typ / 27 C / 2.50 V, the
existing placeholder mixer). The process steps through five short `.tran` runs, a
two-bias `.noise` and a `pss` attempt in its own control block. There is no grid, no
seed campaign and no shell loop; any sideband/seed sweep would have to go through
`klt sim` (README.md "Campaign path").

The executable must be the pinned ngspice major (sim/pdk-artifact.json "ngspice"). A
missing or different binary yields a CAPABILITY_UNAVAILABLE record that carries no
probe results: a missing tool never establishes that an interface is absent.

Writes, append-only (exclusive create; an existing record is never touched):
  probe-logs/<id>/deck.spice      the composed deck exactly as run
  probe-logs/<id>/stdout.txt      full ngspice stdout
  probe-logs/<id>/stderr.txt      full ngspice stderr
  probe-logs/<id>/inventory.json  parsed marks + the interface matrix
  records/<id>-<STATUS>.md/.json  the record

Exit status 0 when a record (any status) was produced or --no-write printed (a
failing --sabotage control is also 0: failing is its job); 1 on a parse defect; 2 when
a sabotaged control unexpectedly PASSES.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
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

import cmprobe as C  # noqa: E402

TEMPLATE = HERE / "probe" / "interface_probe.spice"
CONTROL = HERE / "controls" / "ideal_mixer.spice"
PLACEHOLDER = SIM_DIR / "mixer-conversion-iip3" / "testbench" / "mixer_ce_placeholder.spice"
PDK_ARTIFACT = SIM_DIR / "pdk-artifact.json"
RECORDS = HERE / "records"
PROBE_LOGS = HERE / "probe-logs"
BENCH = "mixer-cm-interface-probe"

MANUAL_URL = "https://ngspice.sourceforge.io/docs/ngspice-46-manual.pdf"
MANUAL_SHA256 = "b5bc7c4f3aac00e670b01b1d1ab64ec87055a491014af1de828764bf98faf766"
SOURCE_TAG = "ngspice-46 (commit ebdaf58ec76a06ffaac7e0f138360dd1cf5ee4b6, https://git.code.sf.net/p/ngspice/ngspice)"
REFERENCES = {
    "manual_tran": f"ngspice User's Manual v46 ({MANUAL_URL}, sha256 {MANUAL_SHA256}), "
                   "chapter 15 'Transient analysis' (.tran) and chapter 13 'Measurements' (.meas INTEG); "
                   "probe marks are the evidence",
    "manual_pss": f"ngspice User's Manual v46 ({MANUAL_URL}, sha256 {MANUAL_SHA256}) "
                  "section 11.3.12 '.PSS: Experimental code, not yet made publicly available' and "
                  "section 1.2.8 (PSS is the basis of PAC/PNoise, neither exists in the release); "
                  "probe mark E: the binary replies 'pss: no such command'",
    "source_noise": f"ngspice source tag {SOURCE_TAG}: src/spicelib/devices/vbic/vbicnoise.c VBICnoise() "
                    "defines 13 independent generators; reached only via DEVnoise from "
                    "src/spicelib/analysis/cktnoise.c (.noise) and noisesp.c (.sp); "
                    "src/spicelib/analysis/dcpss.c exists only under --enable-pss; no pnoise in the tree "
                    "(findings carried from sim/mixer-nf-method/README.md 'Capability inventory', "
                    "where the tag was inspected for issue #27; not re-fetched here)",
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
    """Run the harness model-integrity gate against sim/pdk-artifact.json (no simulator involved)."""
    from harness import pdkartifact  # noqa: WPS433
    from harness.pdk import find_pdk  # noqa: WPS433
    rep = pdkartifact.verify(find_pdk(SIM_DIR), SIM_DIR, banner, require_ngspice=True)
    return {"gate": "sim/harness/pdkartifact.py verify(require_ngspice=True)", "ok": rep.ok,
            "problems": list(rep.problems), "notes": list(rep.notes)}


def git_info() -> dict:
    def g(*a):
        return subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True).stdout.strip()
    return {"commit": g("rev-parse", "HEAD"), "dirty": bool(g("status", "--porcelain"))}


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


# ---- deck composition ------------------------------------------------------------------------

def _fmt(x: float) -> str:
    return f"{x:.10g}"


def run_block(name: str, apu: float, apl: float) -> str:
    """The control-language text for one `.tran` run and its IF/trajectory projections."""
    lo, hi = (_fmt(C.WINDOW[0]), _fmt(C.WINDOW[1]))
    lines = [f"* ---- run {name}: apu={_fmt(apu)} apl={_fmt(apl)} ----",
             f"alterparam apu={_fmt(apu)}", f"alterparam apl={_fmt(apl)}",
             "alterparam vrf=0", "reset", f"tran 1p {_fmt(C.T_STOP)} 0 1p",
             "let npts = length(time)", f'echo "MARK R_{name}_points=$&npts"']
    for ckt, node in (("ctl", "cout"), ("dut", "coll")):
        lines += [f"let {ckt}_c = v({node})*cos(wif*time)", f"let {ckt}_s = v({node})*sin(wif*time)",
                  f"meas tran {ckt}_{name}_c INTEG {ckt}_c from={lo} to={hi}",
                  f"meas tran {ckt}_{name}_s INTEG {ckt}_s from={lo} to={hi}",
                  f'echo "MARK x_{ckt}_{name}_c=$&{ckt}_{name}_c x_{ckt}_{name}_s=$&{ckt}_{name}_s"']
    lines += ["let wx_c = v(cout)*cos(wxf*time)", "let wx_s = v(cout)*sin(wxf*time)",
              f"meas tran wx_{name}_c INTEG wx_c from={lo} to={hi}",
              f"meas tran wx_{name}_s INTEG wx_s from={lo} to={hi}",
              f'echo "MARK w_ctl_{name}_c=$&wx_{name}_c w_ctl_{name}_s=$&wx_{name}_s"']
    if name == "base":
        for h, w in (("f1", "wlo"), ("f2", "w2lo")):
            lines += [f"let t{h}_c = v(coll)*cos({w}*time)", f"let t{h}_s = v(coll)*sin({w}*time)"]
            for i, (a, b) in enumerate(C.TRAJ_WINDOWS, 1):
                fa, fb = _fmt(a), _fmt(b)
                lines += [f"meas tran t{h}w{i}_c INTEG t{h}_c from={fa} to={fb}",
                          f"meas tran t{h}w{i}_s INTEG t{h}_s from={fa} to={fb}",
                          f'echo "MARK t_dut_base_w{i}_{h}_c=$&t{h}w{i}_c t_dut_base_w{i}_{h}_s=$&t{h}w{i}_s"']
        for i, (a, b) in enumerate(C.TRAJ_WINDOWS, 1):
            lines += [f"meas tran tavg{i} AVG v(coll) from={_fmt(a)} to={_fmt(b)}",
                      f'echo "MARK t_dut_base_w{i}_avg=$&tavg{i}"']
    return "\n".join(lines)


def compose_deck(model_lib: str, sabotage: str | None = None) -> str:
    runs = "\n\n".join(run_block(n, a, b) for n, (a, b) in C.RUNS.items())
    ctl = CONTROL.read_text()
    if sabotage:
        # Override the control's .param defaults (sabotage never reaches a record).
        ov = C.SABOTAGES[sabotage]
        ctl += "\n* SABOTAGE (--sabotage %s): control .param overrides, last definition wins\n" % sabotage
        ctl += ".param " + " ".join(f"{k}={_fmt(v)}" for k, v in ov.items()) + "\n"
    ctl_path = "{control}"
    deck = (TEMPLATE.read_text().replace("{model_lib}", model_lib)
            .replace("{placeholder}", str(PLACEHOLDER)).replace("{runs}", runs))
    # The control fragment is inlined (not .include'd) so deck.spice alone reproduces the run.
    inline = f"* ---- inlined from sim/{BENCH}/controls/ideal_mixer.spice ----\n{ctl}* ---- end inlined control ----\n"
    return deck.replace(f'.include "{ctl_path}"', inline)


# ---- rendering -----------------------------------------------------------------------------------

def integrity_line(env: dict) -> str:
    """Provenance bullet for the model-integrity gate, or "" when env carries no gate outcome.

    Records written before the gate existed (issue #107) have no 'pdk_integrity' key; rendering
    such an env must still work and must not invent a gate result for it.
    """
    integ = env.get("pdk_integrity")
    if not isinstance(integ, dict):
        return ""
    verdict = "OK" if integ.get("ok") else "FAILED"
    detail = "; ".join(list(integ.get("notes") or []) + list(integ.get("problems") or []))
    return (f"- Model integrity gate (`sim/harness/pdkartifact.py`, run before the simulator): {verdict}"
            f"{'; ' + detail if detail else ''}\n")


def render_md(rid: str, status: str, reasons: list, matrix: dict, ctl: dict, env: dict) -> str:
    rows = "\n".join(f"| `{k}` | {v['state']} | {v['basis']} | {v['note']} |" for k, v in matrix.items())
    crows = "\n".join(f"| {k} | {'pass' if v['pass'] else 'FAIL'} | "
                      f"{ {kk: vv for kk, vv in v.items() if kk != 'pass'} } |" for k, v in ctl["checks"].items())
    return f"""# {BENCH} record {rid}-{status}

- **Status: {status}**
- **Scope: interface-feasibility evidence only.** This record asks whether the periodic-transfer
  and model-noise interfaces a conversion-matrix noise solver would need are reachable on the
  pinned simulator/model. It is not a noise figure and makes **no claim about
  `spec/target-spec.md` row 10 (mixer SSB NF) or row 12 (cascade NF)**; no active-mixer NF number
  is reported. It is not `METHOD_VALIDATION`.
- Nominal point: `hbt_typ` / 27 C / VDD = 2.50 V, placeholder
  `sim/mixer-conversion-iip3/testbench/mixer_ce_placeholder.spice` (included verbatim). LO drive is a
  probe setting, not a design selection.

## Reasons

{chr(10).join('- ' + r for r in reasons)}

## Interface matrix (full detail in the JSON sidecar and `../probe-logs/{rid}/inventory.json`)

| interface | state | basis | note |
|---|---|---|---|
{rows}

## Known-answer control (ideal multiplying mixer, closed-form Gw/Gi)

| check | result | detail |
|---|---|---|
{crows}

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


INTEGRITY_REASON = ("installed PDK models failed the integrity gate against sim/pdk-artifact.json "
                    "(the pinned simulator was found but not run); this status never establishes absence")


def render_unavailable_md(rid: str, status: str, failed: str, cause: str = "missing-tool") -> str:
    """CAPABILITY_UNAVAILABLE record text. cause is "missing-tool" (default, the original
    wording) or "model-integrity" (simulator present, models failed the pdkartifact gate)."""
    if cause == "model-integrity":
        kind = "a model-integrity outcome only (the simulator was present but was not run)"
        later = "whose installed models pass the integrity gate"
    else:
        kind = "a missing-tool\n  outcome only"
        later = "that has the pinned executable"
    return f"""# {BENCH} record {rid}-{status}

- **Status: {status}**
- **Scope: no probe ran.** No interface-feasibility result of any kind, no active-mixer NF
  number, and no claim about `spec/target-spec.md` rows 10/12. This status is {kind}; it never establishes that an interface is absent.
- Failed check: {failed}

A later record produced on a host {later} supersedes this one; this
file is not edited or removed (records are append-only).
"""


# ---- main ----------------------------------------------------------------------------------------------

def decide_and_describe(parsed: dict) -> tuple[dict, dict, str, list]:
    matrix = C.build_matrix(parsed, REFERENCES)
    ctl = C.evaluate_control(parsed["marks"])
    status, reasons = C.decide_status(True, matrix)
    return matrix, ctl, status, reasons


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--ngspice", default=os.environ.get("NGSPICE", "ngspice"))
    ap.add_argument("--reparse", type=Path, help="probe-logs/<id> directory to re-derive")
    ap.add_argument("--sabotage", choices=sorted(C.SABOTAGES),
                    help="break the known-answer control; expects it to FAIL; never writes a record")
    ap.add_argument("--allow-unpinned", action="store_true",
                    help="run a non-pinned ngspice for exploration; never writes a record")
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args(argv)

    if args.reparse:
        d = args.reparse if args.reparse.is_absolute() else HERE / args.reparse
        parsed = C.parse_log((d / "stdout.txt").read_text(), (d / "stderr.txt").read_text())
        matrix, ctl, status, reasons = decide_and_describe(parsed)
        print(json.dumps({"status": status, "reasons": reasons, "interface_matrix": matrix,
                          "control": ctl}, indent=2, default=str))
        return 0

    no_write = args.no_write or bool(args.sabotage) or args.allow_unpinned
    git = git_info()
    env = {"host": platform.node(), "platform": platform.platform(), "python": sys.version.split()[0],
           "git": git, "placeholder_sha256": sha256(PLACEHOLDER), "pdk_artifact_sha256": sha256(PDK_ARTIFACT)}
    rid = new_record_id((git["commit"] or "unknown")[:7])

    exe = shutil.which(args.ngspice)
    info = ngspice_info(exe) if exe else None
    failed = None
    if exe is None:
        failed = f"shutil.which({args.ngspice!r}) is None"
    elif info["major"] != pinned_major() and not args.allow_unpinned:
        failed = (f"pinned ngspice-{pinned_major()} (sim/pdk-artifact.json) not found: {args.ngspice!r} "
                  f"resolves to {exe} = {info['version']!r}; a different version is not the pinned "
                  "executable, so no result from it is evidence for this record")
    if failed:
        status, reasons = C.decide_status(False, None)
        rec = {"record_id": rid, "status": status, "reasons": reasons, "failed_check": failed,
               "scope": "no probe ran; no active-mixer NF number; no row-10/row-12 claim",
               "environment": env}
        print(json.dumps(rec, indent=2))
        if not no_write:
            write_excl(RECORDS / f"{rid}-{status}.json", json.dumps(rec, indent=2) + "\n")
            write_excl(RECORDS / f"{rid}-{status}.md", render_unavailable_md(rid, status, failed))
            print(f"wrote records/{rid}-{status}.md")
        return 0

    env["ngspice"] = info
    env["pdk"] = pdk_info()
    # Integrity gate (issue #107): the installed models must match sim/pdk-artifact.json BEFORE any
    # simulator run. A mismatch is a capability blocker, not an interface result.
    integ = pdk_integrity(info["version"])
    env["pdk_integrity"] = integ
    if not integ["ok"] and not args.allow_unpinned:
        failed = "PDK model integrity gate failed (sim/harness/pdkartifact.py): " + "; ".join(integ["problems"])
        status, _ = C.decide_status(False, None)
        # The simulator IS present here; the blocker is the models, so say that (not "simulator
        # not available", which is decide_status's missing-tool wording).
        reasons = [INTEGRITY_REASON]
        rec = {"record_id": rid, "status": status, "reasons": reasons, "failed_check": failed,
               "scope": "no probe ran; no active-mixer NF number; no row-10/row-12 claim",
               "environment": env}
        print(json.dumps(rec, indent=2))
        if not no_write:
            write_excl(RECORDS / f"{rid}-{status}.json", json.dumps(rec, indent=2) + "\n")
            write_excl(RECORDS / f"{rid}-{status}.md",
                       render_unavailable_md(rid, status, failed, cause="model-integrity"))
            print(f"wrote records/{rid}-{status}.md")
        return 0
    deck = compose_deck(env["pdk"]["model_lib"], args.sabotage)
    work = PROBE_LOGS / rid if not no_write else HERE / "_build" / rid
    work.mkdir(parents=True, exist_ok=False)
    (work / "deck.spice").write_text(deck)
    proc = subprocess.run([exe, "-b", "deck.spice"], cwd=work, capture_output=True, text=True,
                          timeout=args.timeout, check=False)
    (work / "stdout.txt").write_text(proc.stdout)
    (work / "stderr.txt").write_text(proc.stderr)
    env["ngspice_exit"] = proc.returncode

    parsed = C.parse_log(proc.stdout, proc.stderr)
    matrix, ctl, status, reasons = decide_and_describe(parsed)
    if args.sabotage:
        print(json.dumps({"sabotage": args.sabotage, "control": ctl}, indent=2, default=str))
        if ctl["pass"]:
            print(f"ERROR: sabotaged control '{args.sabotage}' PASSED; the control cannot discriminate",
                  file=sys.stderr)
            return 2
        print(f"sabotage '{args.sabotage}': control FAILED as required")
        return 0
    (work / "inventory.json").write_text(json.dumps({"parsed": parsed, "interface_matrix": matrix},
                                                    indent=2, default=str) + "\n")
    rec = {"record_id": rid, "status": status, "reasons": reasons,
           "scope": "interface-feasibility evidence only; no row-10/row-12 claim; no active-mixer NF number",
           "nominal_point": {"corner": "hbt_typ", "temp_c": 27, "vdd_v": 2.5, "lo_hz": C.F_LO,
                             "if_hz": C.F_IF, "note": "LO drive is a probe setting, not a design selection"},
           "interface_matrix": matrix, "controls": ctl, "references": REFERENCES,
           "probe_logs": f"sim/{BENCH}/probe-logs/{rid}/", "environment": env}
    md = render_md(rid, status, reasons, matrix, ctl, env)
    if no_write:
        print(md)
        return 0
    write_excl(RECORDS / f"{rid}-{status}.json", json.dumps(rec, indent=2, default=str) + "\n")
    write_excl(RECORDS / f"{rid}-{status}.md", md)
    print(f"wrote records/{rid}-{status}.md")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except C.ProbeError as exc:
        print(f"parse defect, no record written: {exc}", file=sys.stderr)
        sys.exit(1)
