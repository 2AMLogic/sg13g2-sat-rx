#!/usr/bin/env python3
"""Capability probe + record writer for the mixer SSB-NF method (issue #27).

    python3 sim/mixer-nf-method/run_probe.py            # probe once, write a record
    python3 sim/mixer-nf-method/run_probe.py --no-write # probe once, print only
    python3 sim/mixer-nf-method/run_probe.py --reparse probe-logs/<id>
                                                        # re-derive inventory from a
                                                        # committed log (no simulator)

Runs ONE ngspice process locally (a single nominal capability smoke probe:
hbt_typ / 27 C / 2.50 V, the existing placeholder mixer). No grid, no seed
campaign: a campaign only exists past the coverage gate, and would go through
`klt sim` (README.md "Campaign path").

Writes, append-only (exclusive create; an existing record is never touched):
  probe-logs/<id>/deck.spice      the composed deck exactly as run
  probe-logs/<id>/stdout.txt      full ngspice stdout
  probe-logs/<id>/stderr.txt      full ngspice stderr
  probe-logs/<id>/inventory.json  parsed marks + mechanism inventory
  records/<id>-<STATUS>.md/.json  the record

Exit status 0 when a record (any status) was produced or --no-write printed;
1 on an estimator/parse defect (no record is written then).
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
sys.path.insert(0, str(SIM_DIR))
sys.path.insert(0, str(HERE))

import nfmethod as M  # noqa: E402

TEMPLATE = HERE / "probe" / "capability_probe.spice"
PLACEHOLDER = SIM_DIR / "mixer-conversion-iip3" / "testbench" / "mixer_ce_placeholder.spice"
RECORDS = HERE / "records"
PROBE_LOGS = HERE / "probe-logs"

# Official references (pinned; see README.md "Capability inventory").
MANUAL = {
    "title": "ngspice User's Manual, version 46",
    "url": "https://ngspice.sourceforge.io/docs/ngspice-46-manual.pdf",
    "sha256": "b5bc7c4f3aac00e670b01b1d1ab64ec87055a491014af1de828764bf98faf766",
    "sections": {
        "4.1.7": "Transient noise source (TRNOISE): 'The noise generators are implemented "
                 "into the independent voltage (vsrc) and current (isrc) sources.'",
        "11.3.11": "Transient noise analysis: noise 'added to your circuits' via vsrc/isrc; "
                   "open questions listed by the manual include 'how to generate noise from a "
                   "transistor model' and 'calibration of noise spectral density'.",
        "11.3.12": ".PSS: 'Experimental code, not yet made publicly available.'",
        "1.2.8": "PSS is the basis of 'periodical large-signal analyses like PAC or PNoise' "
                 "(neither exists).",
    },
}
SOURCE = {
    "repo": "https://git.code.sf.net/p/ngspice/ngspice",
    "tag": "ngspice-46",
    "commit": "ebdaf58ec76a06ffaac7e0f138360dd1cf5ee4b6",
    "findings": [
        "src/spicelib/devices/vbic/vbicnoise.c: VBICnoise() defines 13 generators "
        "(_rc _rci _rb _rbi _re _rbp _rs thermal; _ic _ib _ibep _iccp shot; "
        "_1overfbe _1overfbep flicker), each evaluated independently (no ib/ic correlation).",
        "VBICnoise is reached only through DEVnoise, called only from "
        "src/spicelib/analysis/cktnoise.c (via noisean.c, .noise) and span.c/noisesp.c "
        "(.sp noise) -- never from the transient load path.",
        "src/spicelib/devices/vbic/vbicload.c and src/spicelib/devices/res/resload.c "
        "(the .tran/.dc load routines) contain no noise or random term.",
        "TRNOISE is implemented only in src/spicelib/devices/vsrc/ and isrc/.",
        "src/spicelib/analysis/dcpss.c is compiled only with configure --enable-pss "
        "(WITH_PSS, 'experimental'); there is no pnoise implementation in the tree.",
        "Same structure at tag ngspice-47 (a80f6e3e95d51534905b1f23410a951802666656), "
        "checked by source only; the ngspice-47 binary was NOT run.",
    ],
}

MARK_RE = re.compile(r"^MARK\s+(.*)$")
KV_RE = re.compile(r"(\w+)=(\S*)")
ONOISE_RE = re.compile(r"^(onoise_total\S*)\s*=\s*(\S+)\s*$")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _float(s: str | None) -> float | None:
    if s is None or s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_log(stdout: str, stderr: str) -> dict:
    """Extract MARK key=value pairs, per-generator integrated noise, pss reply."""
    marks: dict[str, float | None] = {}
    noise: dict[str, float] = {}
    for line in stdout.splitlines():
        m = MARK_RE.match(line.strip())
        if m:
            for k, v in KV_RE.findall(m.group(1)):
                marks[k] = _float(v)
            continue
        n = ONOISE_RE.match(line.strip())
        if n:
            val = _float(n.group(2))
            if val is not None:
                noise[n.group(1)] = val
    both = stdout + "\n" + stderr
    pss_missing = "pss: no such command" in both
    return {"marks": marks, "noise_totals_v_rms": noise, "pss_command_missing": pss_missing,
            "completed": "MARK done" in stdout}


def _hbt(noise: dict, suffixes) -> float:
    """Root-sum-square of the named VBIC generators (all instances)."""
    tot = 0.0
    for k, v in noise.items():
        if ".qnpn13g2_" in k and k.rsplit("_", 1)[-1] in suffixes:
            tot += v * v
    return math.sqrt(tot)


def build_inventory(parsed: dict) -> dict:
    """Mechanism -> {tran, noise_analysis, evidence}. Pure function of the log."""
    mk = parsed["marks"]
    nz = parsed["noise_totals_v_rms"]
    if not parsed.get("completed"):
        raise M.MethodError("probe log incomplete (no 'MARK done')")
    a_diff = mk.get("A_coll_seed_diff_max")
    a_n1, a_n2 = mk.get("A_points_seed1"), mk.get("A_points_seed2")
    b_pp = mk.get("B_coll_pp_lo_off")
    r_pp = mk.get("B_rdiv_pp")
    c1, c2 = mk.get("C_tnl_rms_seed1"), mk.get("C_tnl_rms_seed2")
    c1a, c2a = mk.get("C_tnl_at21n_seed1"), mk.get("C_tnl_at21n_seed2")
    c3a = mk.get("C_tnl_at21n_seed1_repeat")
    for name, v in (("A_coll_seed_diff_max", a_diff), ("B_coll_pp_lo_off", b_pp),
                    ("B_rdiv_pp", r_pp), ("C_tnl_rms_seed1", c1)):
        if v is None:
            raise M.MethodError(f"probe mark {name} missing or non-numeric")

    groups = {
        "hbt_shot_collector": ("ic", "iccp"),
        "hbt_shot_base": ("ib", "ibep"),
        "hbt_terminal_resistor_thermal": ("rb", "rbi", "rbp", "rc", "rci", "re", "rs"),
        "hbt_flicker": ("1overfbe", "1overfbep"),
    }
    hbt_all = _hbt(nz, tuple(s for g in groups.values() for s in g))
    if hbt_all <= 0:
        raise M.MethodError("no HBT generator found in the .noise output; cannot size the probe")
    # bandwidth of the comparison: one bin of the 4 ns window .. Nyquist of 1 ps
    bw = 500e9 - 250e6
    r_expected = math.sqrt(4 * M.K_B * M.T0_K * 500.0 * bw)  # 1k||1k = 500 ohm, no capacitance

    deterministic = (a_diff == 0.0 and a_n1 == a_n2)
    trnoise_ok = (c1 is not None and c1 > 0 and c2 is not None and c2 > 0 and c1a != c2a)

    inv: dict[str, dict] = {}
    for mech, sfx in groups.items():
        expected = _hbt(nz, sfx)
        # Unsupported needs BOTH: LO-on run-to-run determinism and an LO-off
        # flat collector far below what .noise says this mechanism alone gives.
        # A mechanism too small to resolve on its own is still called absent
        # when the run is bit-deterministic (any RNG-driven generator, however
        # small, changes the waveform) AND the HBT as a whole is resolved.
        size_note = ""
        if deterministic and expected > 0 and b_pp < 0.01 * expected:
            tran = M.UNSUPPORTED
        elif deterministic and b_pp < 0.01 * hbt_all:
            tran = M.UNSUPPORTED
            size_note = ("; below this probe's amplitude resolution on its own -- absence "
                         "rests on run-to-run determinism and the source reference")
        else:
            tran = M.UNKNOWN
        inv[mech] = {
            "tran": tran,
            "noise_analysis": M.SUPPORTED if expected > 0 else M.UNKNOWN,
            "noise_analysis_v_rms_at_coll": expected,
            "evidence": (
                f"LO-driven .tran, two runs, max abs diff of v(coll) = {a_diff:g} V over "
                f"{a_n1:g}/{a_n2:g} points; LO-off settled p-p = {b_pp:g} V vs this "
                f"mechanism's .noise output {expected:.4g} V rms in {bw:.4g} Hz{size_note}"),
        }
    inv["resistor_thermal"] = {
        "tran": M.UNSUPPORTED if (r_pp == 0.0 and deterministic) else M.UNKNOWN,
        "noise_analysis": M.SUPPORTED if any(k.endswith("_thermal") and v > 0
                                              for k, v in nz.items()) else M.UNKNOWN,
        "evidence": (f"1k/1k divider .tran settled p-p = {r_pp:g} V vs expected thermal "
                     f"{r_expected:.4g} V rms (500 ohm, {bw:.4g} Hz, T0)"),
    }
    inv["hbt_noise_correlation"] = {
        "tran": M.UNSUPPORTED,
        "noise_analysis": M.UNSUPPORTED,
        "evidence": "VBICnoise() evaluates every generator independently (source "
                    "reference); no correlated ib/ic pair exists in any analysis.",
    }
    inv["external_trnoise_injection"] = {
        "tran": M.SUPPORTED if trnoise_ok else M.UNKNOWN,
        "noise_analysis": "n/a",
        "evidence": (f"TRNOISE(1m 1p) into 50/50 ohm: window rms {c1} / {c2} V in two runs; "
                     f"v(21 ns) = {c1a} / {c2a} V; re-issued setseed 1 gave {c3a} V "
                     f"({'reproduced' if c3a == c1a else 'NOT reproduced'} by setseed)"),
        "setseed_reproduces_draw": (c3a == c1a),
    }
    inv["pss_pnoise"] = {
        "tran": "n/a",
        "noise_analysis": M.UNSUPPORTED if parsed["pss_command_missing"] else M.UNKNOWN,
        "evidence": ("binary replies 'pss: no such command available in ngspice'"
                     if parsed["pss_command_missing"] else "pss reply not recognised"),
    }
    sizing = {
        "hbt_all_generators_v_rms_at_coll": hbt_all,
        "noise_total_v_rms_at_coll": nz.get("onoise_total"),
        "lo_off_tran_pp_v": b_pp,
        "pp_over_expected_rms": b_pp / hbt_all,
        "pp_over_expected_rms_db": 20 * math.log10(b_pp / hbt_all) if b_pp > 0 else -math.inf,
        "comparison_band_hz": [250e6, 500e9],
        "resistor_expected_v_rms": r_expected,
        "lo_on_settled_pp_v": mk.get("A_coll_pp_lo_on_window"),
        "lo_off_dc_v": mk.get("B_coll_dc"),
        "trnoise_expected_rms_v": 0.5e-3,
        "trnoise_linear_interp_rms_v": 0.5e-3 * math.sqrt(2.0 / 3.0),
    }
    return {"mechanisms": inv, "sizing": sizing}


def controls_from_inventory(inv: dict) -> M.Controls:
    """The step-4 controls this probe can evaluate without a campaign.

    (a) analytic known-answer: evaluated on the estimator itself (no
        simulator): attenuator + ideal mixer, image included.
    (b) LO-off HBT control: .tran collector noise vs .noise in the same band.
        The .tran side is bounded by the settled peak-to-peak, so the error is
        at least -20 log10(pp/rms) dB (a lower bound; rms <= pp/2 for any record).
    (c) omission: .tran already behaves as 'intrinsic noise omitted', so the
        omission control cannot discriminate -> not demonstrated.
    """
    s = inv["sizing"]
    f_true = M.attenuator_ideal_mixer_f_ssb(10 ** 0.6, M.T0_K, 1.0, 1.0)
    budget = M.NoiseBudget(
        bandwidth_hz=1e6, gain_wanted=1.0 / 10 ** 0.6, gain_image=1.0 / 10 ** 0.6,
        n_out_w=M.K_B * M.T0_K * 1e6 * 2 * (1.0 / 10 ** 0.6) * 10 ** 0.6,
        contributions={"source_wanted": M.K_B * M.T0_K * 1e6 / 10 ** 0.6,
                       "source_image": M.K_B * M.T0_K * 1e6 / 10 ** 0.6,
                       "dut": 2 * M.K_B * M.T0_K * 1e6 * (1 - 1 / 10 ** 0.6),
                       "load": 0.0})
    analytic_err = abs(M.db(M.ssb_noise_factor(budget)) - M.db(f_true))
    pp, rms = s["lo_off_tran_pp_v"], s["hbt_all_generators_v_rms_at_coll"]
    lo_off_err = math.inf if pp == 0 else -20 * math.log10(pp / 2 / rms)
    return M.Controls(analytic_error_db=analytic_err, lo_off_hbt_error_db=lo_off_err,
                      omission_detected=False, periodic_coverage=False)


def ngspice_info(exe: str) -> dict:
    out = subprocess.run([exe, "-v"], capture_output=True, text=True, check=False).stdout
    line = next((l.strip(" *") for l in out.splitlines() if "ngspice-" in l), "unknown")
    return {"path": exe, "version": line.strip(), "sha256": sha256(Path(exe))}


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


def git_info() -> dict:
    def g(*a):
        r = subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True)
        return r.stdout.strip()
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


def render_md(rid: str, status: str, reasons: list, inv: dict, controls: M.Controls,
              env: dict) -> str:
    s = inv["sizing"]
    mech = inv["mechanisms"]
    rows = "\n".join(
        f"| `{k}` | {v['tran']} | {v['noise_analysis']} | {v['evidence']} |"
        for k, v in mech.items())
    return f"""# mixer-nf-method record {rid}-{status}

- **Status: {status}**
- **Scope: methodology evidence only.** This record is about whether ngspice can
  measure an active mixer's SSB noise figure by transient noise. It is **not** a
  noise figure of the placeholder mixer and makes **no claim about
  `spec/target-spec.md` row 10 (mixer SSB NF) or row 12 (cascade NF)**. No active-mixer
  NF number is reported.
- Nominal point: `hbt_typ` / 27 C / VDD = 2.50 V, placeholder
  `sim/mixer-conversion-iip3/testbench/mixer_ce_placeholder.spice` (included verbatim).
- Sideband convention (would apply to any later number): IEEE SSB, wanted-sideband
  available gain, image noise included with the image termination at T0 = {M.T0_K} K.

## Missing capability (the reason for the status)

{chr(10).join('- ' + r for r in reasons)}

ngspice-46 generates **no** intrinsic HBT noise (shot, terminal-resistance thermal or
flicker) and **no** resistor thermal noise during `.tran`. The only stochastic signal
`.tran` can carry is an explicit independent-source `TRNOISE`/`trrandom`. Its intrinsic
VBIC noise exists only in the small-signal `.noise` (and `.sp` noise) analyses about a
fixed DC operating point, and there is no periodic steady-state / periodic-noise analysis
(`pss` is absent from this binary; there is no pnoise in the source tree). Per the
issue's gate 2, the active-mixer transient NF path stops here. No external surrogate
(e.g. a `TRNOISE` source sized from `.noise`) is substituted: it would be unvalidated
under LO drive, where the generators are cyclostationary.

## Probe evidence (single local `ngspice -b`, logs in `../probe-logs/{rid}/`)

| mechanism | in `.tran` | in `.noise` | evidence |
|---|---|---|---|
{rows}

Sizing (why "flat" means "absent", not "too small to see"):

- HBT generators at the collector, `.noise` about the LO-off DC point, integrated
  {s['comparison_band_hz'][0]:.4g}-{s['comparison_band_hz'][1]:.4g} Hz (one bin of the 4 ns
  window to the Nyquist frequency of the 1 ps step): **{s['hbt_all_generators_v_rms_at_coll']:.4g} V rms**
  (all noise sources incl. resistors: {s['noise_total_v_rms_at_coll']:.4g} V rms).
- Same circuit in `.tran` (LO off, no TRNOISE), 20-24 ns settled window: **peak-to-peak
  {s['lo_off_tran_pp_v']:.4g} V**, i.e. {abs(s['pp_over_expected_rms_db']):.1f} dB below the expected
  rms (a Gaussian record of this length would show p-p of roughly 7x rms). The residual
  is deterministic settling/numerics, identical between runs.
- LO on: two consecutive `.tran` runs in one process give **bit-identical** collector
  waveforms (max abs difference 0 over every point) while the LO swings the collector
  {s['lo_on_settled_pp_v']:.4g} V p-p; any RNG-driven generator would make them differ.
- Positive control: an explicit `TRNOISE(1m 1p)` source IS visible to the same probe
  statistics (window rms near the {s['trnoise_linear_interp_rms_v']:.4g} V expected for a 0.5 mV
  rms sequence linearly interpolated between NT points), and differs run to run.
  `setseed` did {'' if mech['external_trnoise_injection'].get('setseed_reproduces_draw') else 'NOT '}reproduce
  the draw (consistent with 2AMLogic/klayout-tools#2963); irrelevant here because no
  campaign is run.

## Controls (issue step 4)

| control | result | limit | pass |
|---|---|---|---|
| (a) attenuator + ideal mixer, image included, estimator known answer | {controls.analytic_error_db:.2e} dB | {M.CONTROL_TOL_DB} dB | {'yes' if controls.analytic_error_db <= M.CONTROL_TOL_DB else 'no'} |
| (b) LO-off HBT: `.tran` collector noise vs `.noise`, same band | >= {controls.lo_off_hbt_error_db:.1f} dB low (bounded via p-p) | {M.CONTROL_TOL_DB} dB | no |
| (c) intrinsic-noise omission makes (b) fail | not demonstrable: `.tran` already equals the omitted case | must fail | no |
| LO-driven internal-noise coverage | none available | required | no |

Control (a) exercises the estimator on analytic numbers only (also with a stochastic
numpy fixture and the Y-factor route in `tests/test_nfmethod.py`); it says nothing about
the simulator. Seed / duration / timestep convergence gates were **not run**: they apply
only after coverage passes, so there is no seed count, bandwidth or interval to report.

## Provenance

- ngspice: `{env['ngspice']['path']}` -- {env['ngspice']['version']}, sha256 `{env['ngspice']['sha256']}`
- PDK: `{env['pdk']['path']}` (.fetched-version {env['pdk']['fetched_version']}), section `hbt_typ`;
  cornerHBT.lib `{env['pdk']['sha256']['cornerHBT.lib']}`, sg13g2_hbt_mod.lib
  `{env['pdk']['sha256']['sg13g2_hbt_mod.lib']}`; {env['pdk']['device']}
- Placeholder sha256 `{env['placeholder_sha256']}`; probe template sha256 `{env['template_sha256']}`
- Repo commit `{env['git']['commit']}` (dirty: {env['git']['dirty']}); host {env['host']}
- Official reference: {MANUAL['title']} ({MANUAL['url']}, sha256 `{MANUAL['sha256']}`),
  sections 4.1.7, 11.3.11, 11.3.12, 1.2.8 (quoted in the JSON sidecar).
- Source reference: {SOURCE['repo']} tag `{SOURCE['tag']}` @ `{SOURCE['commit']}` (findings in the JSON sidecar).
- Command: `python3 sim/mixer-nf-method/run_probe.py`

## What would change this status

A simulator that generates intrinsic device noise during large-signal transient
(or a PSS + pnoise / harmonic-balance noise analysis) with the VBIC generators, plus
the controls above. Upstream gap (ngspice capability vs `klt sim` orchestration
distinguished there): 2AMLogic/klayout-tools#2985; see README.md "Upstream".
"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--ngspice", default=os.environ.get("NGSPICE", "ngspice"))
    ap.add_argument("--reparse", type=Path, help="probe-logs/<id> directory to re-derive")
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args(argv)

    if args.reparse:
        d = args.reparse if args.reparse.is_absolute() else HERE / args.reparse
        parsed = parse_log((d / "stdout.txt").read_text(), (d / "stderr.txt").read_text())
        inv = build_inventory(parsed)
        status, reasons = M.decide_status(True, inv["mechanisms"], controls_from_inventory(inv))
        print(json.dumps({"status": status, "reasons": reasons, "inventory": inv}, indent=2, default=str))
        return 0

    git = git_info()
    exe = shutil.which(args.ngspice)
    env = {"host": platform.node(), "platform": platform.platform(), "python": sys.version.split()[0],
           "git": git, "placeholder_sha256": sha256(PLACEHOLDER), "template_sha256": sha256(TEMPLATE)}
    rid = new_record_id((git["commit"] or "unknown")[:7])

    if exe is None:
        status, reasons = M.decide_status(False, None)
        rec = {"record_id": rid, "status": status, "reasons": reasons,
               "failed_check": f"shutil.which({args.ngspice!r}) is None", "environment": env,
               "claims": "none; CAPABILITY_UNAVAILABLE cannot establish model absence"}
        print(json.dumps(rec, indent=2))
        if not args.no_write:
            write_excl(RECORDS / f"{rid}-{status}.json", json.dumps(rec, indent=2) + "\n")
            write_excl(RECORDS / f"{rid}-{status}.md",
                       f"# mixer-nf-method record {rid}-{status}\n\n- **Status: {status}**\n"
                       f"- Failed check: `{rec['failed_check']}`\n- No noise number of any kind; "
                       "this status cannot establish model absence.\n")
        return 0

    env["ngspice"] = ngspice_info(exe)
    env["pdk"] = pdk_info()
    deck = (TEMPLATE.read_text()
            .replace("{model_lib}", env["pdk"]["model_lib"])
            .replace("{placeholder}", str(PLACEHOLDER)))
    work = PROBE_LOGS / rid if not args.no_write else HERE / "_build" / rid
    work.mkdir(parents=True, exist_ok=False)
    (work / "deck.spice").write_text(deck)
    proc = subprocess.run([exe, "-b", "deck.spice"], cwd=work, capture_output=True, text=True,
                          timeout=args.timeout, check=False)
    (work / "stdout.txt").write_text(proc.stdout)
    (work / "stderr.txt").write_text(proc.stderr)
    env["ngspice_exit"] = proc.returncode

    parsed = parse_log(proc.stdout, proc.stderr)
    inv = build_inventory(parsed)
    controls = controls_from_inventory(inv)
    status, reasons = M.decide_status(True, inv["mechanisms"], controls)
    if status == M.METHOD_VALIDATION:  # cannot happen from a probe; guard anyway
        raise M.MethodError("a capability probe alone can never produce METHOD_VALIDATION")
    (work / "inventory.json").write_text(json.dumps({"parsed": parsed, "inventory": inv},
                                                    indent=2, default=str) + "\n")
    rec = {"record_id": rid, "status": status, "reasons": reasons,
           "scope": "methodology evidence only; no row-10/row-12 claim; no active-mixer NF number",
           "nominal_point": {"corner": "hbt_typ", "temp_c": 27, "vdd_v": 2.5},
           "sideband_convention": "IEEE SSB, wanted-sideband available gain, image at T0",
           "t0_k": M.T0_K, "inventory": inv,
           "controls": {k: (None if v is None else (str(v) if isinstance(v, float) and math.isinf(v) else v))
                        for k, v in vars(controls).items()},
           "convergence": "not run (gated behind coverage)",
           "references": {"manual": MANUAL, "source": SOURCE},
           "probe_logs": f"sim/mixer-nf-method/probe-logs/{rid}/", "environment": env}
    md = render_md(rid, status, reasons, inv, controls, env)
    if args.no_write:
        print(md)
        return 0
    write_excl(RECORDS / f"{rid}-{status}.json", json.dumps(rec, indent=2, default=str) + "\n")
    write_excl(RECORDS / f"{rid}-{status}.md", md)
    print(f"wrote records/{rid}-{status}.md")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except M.MethodError as exc:
        print(f"estimator/parse defect, no record written: {exc}", file=sys.stderr)
        sys.exit(1)
