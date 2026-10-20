"""Pure logic for the hbt-mismatch-pair Monte Carlo method probe (issue 186).

Everything here is stdlib-only and side-effect free so the CI tests
(``tests/``) can exercise request shape, report ingestion, statistics and the
status gates without klt, a PDK or a simulator. ``run_probe.py`` owns every
side effect (submits, artifact writes, record writes) and calls into this
module for every decision it records.

METHOD SCOPE (what this probe may and may not claim):

- It qualifies the *method*: can a ``monte_carlo`` request on the pinned PDK
  run at all, on the batch fleet, reproducibly, with per-sample seeds the
  client can predict; do the mismatch/stat cards engage; does a fixed seed
  reproduce; does a local unit agree with the fleet unit drawn from the same
  seed.
- It is NOT evidence for ``spec/target-spec.md`` row 15 (LO leakage) or any
  other row; no verdict in ``spec/row-coverage.json`` moves because of it.
  The pair here is a known-answer method observable, not a mixer.
"""

from __future__ import annotations

import math
from statistics import fmean, stdev

BENCH = "hbt-mismatch-pair"

#: Corner sections, in request order. The ORDER IS LOAD-BEARING: klt derives
#: every sample's seeds from (seed, axis, corner_index, sample_index), so a
#: request that reorders or drops a corner draws different samples. The local
#: agreement leg must therefore use a request built from this same list.
CORNERS: tuple[str, ...] = ("hbt_typ_mismatch", "hbt_typ_stat", "hbt_typ")

#: Sentinels / analysis copied from the harness's own klt_request pattern: the
#: request's trailing analysis exists only so klt grades every unit on a real
#: value; the body's own ``.control`` block does the study (op + print).
SENTINEL_NAME = "harness_rail_v"
SENTINEL_NODE = "v(vdd)"
SENTINEL_SPICE = f".meas tran {SENTINEL_NAME} AVG {SENTINEL_NODE}"
ANALYSIS = {"kind": "tran", "args": "1p 2p"}
TEMPERATURE_C = 27

SEED_DEFAULT = 186
N_DEFAULT = 100
MC_VARY = "both"
RUNNER_VERSION_CHECK_DEFAULT = "warn"

#: The measured quantities the body prints (see bench/pair_body.spice).
MEASURE_NAMES: tuple[str, ...] = ("m_ic1", "m_ic2", "m_ratio", "m_off")

#: klt echoes each sampled unit's seed block under these keys (`seed` is the
#: combined rndseed handed to ngspice's `.options seed=`).
MC_SEED_KEYS: tuple[str, ...] = ("seed", "process_seed", "mismatch_seed")

#: Known-answer gates. The tolerances sit far above solver noise (the nominal
#: offset prints ~3e-14 V) and far below any real spread the mismatch card
#: produces (sigma(ratio) ~ 1e-1), so a gate trip means a broken method, not
#: a marginal measurement.
RATIO_EXACT_TOL = 1e-9          # |ratio - 1| at/below this counts as exactly 1
OFFSET_EXACT_TOL_V = 1e-9       # |offset| in V at/below this counts as exactly 0
MISMATCH_SIGMA_MIN = 1e-3       # sigma(ratio) below this: mismatch not sampled
REPRO_TOL = 1e-12               # per-sample max rel diff batch vs rerun
LOCAL_AGREEMENT_TOL = 1e-4      # rel, batch vs local unit of the same seed
#: The mismatch card's per-instance area sigma is agauss(1, 0.1, 1) = 10% 1 sigma;
#: a current ratio of two independent draws has ~sqrt(2)*10% ~ 14% 1 sigma at
#: fixed-Vbe drive. Not a gate -- the record reports what was measured -- but
#: the classification prints it beside the measurement for the reader.
CARD_AREA_SIGMA = 0.10

STATUSES: tuple[str, ...] = (
    "MC_METHOD_WORKS",
    "MC_METHOD_CONTROL_FAIL",
    "MC_METHOD_REPRODUCIBILITY_FAIL",
    "MC_LOCAL_AGREEMENT_FAIL",
)


class ReportError(ValueError):
    """A klt report cannot be ingested (missing corners, malformed units)."""


def build_request(netlist_name: str, *, n: int, seed: int, backend: str, timeout_s: int,
                  runner_version_check: str = RUNNER_VERSION_CHECK_DEFAULT) -> dict:
    """One klt sim request: the three corners x 27 C, expanded by ``monte_carlo``.

    Mirrors ``harness.klt_driver.klt_request`` (sentinel tran + ``.meas`` so
    klt grades every unit on a real value) plus the ``monte_carlo`` block.
    ``stage_model_inputs`` is deliberately NOT set: the fleet runner (klt
    0.5.0, per the #165 record) ignores staged inputs, so the job resolves
    the models baked into its own image and the record states that identity
    from the report's environment instead.
    """
    req = {
        "netlist": netlist_name,
        "backend": backend,
        "models": {"pdk": "ihp-sg13g2", "lib": "libs.tech/ngspice/models/cornerHBT.lib"},
        "corners": {"process": list(CORNERS), "temperature_c": [TEMPERATURE_C]},
        "monte_carlo": {"n": n, "seed": seed, "vary": MC_VARY},
        "analysis": dict(ANALYSIS),
        "measurements": [
            {"name": SENTINEL_NAME, "spice": SENTINEL_SPICE, "unit": "V"},
        ],
        "options": {"timeout_s": timeout_s, "keep_artifacts": True},
    }
    if backend == "batch" and runner_version_check:
        req["batch"] = {"runner_version_check": runner_version_check}
    return req


def expected_units(n: int) -> int:
    """Units a healthy expansion produces: every corner x every sample."""
    return len(CORNERS) * n


def _unit_from_corner(corner: dict, where: str) -> dict:
    if not isinstance(corner, dict):
        raise ReportError(f"{where}: corner entry is not an object")
    mc = corner.get("monte_carlo")
    meas = {}
    for m in corner.get("measurements") or []:
        if isinstance(m, dict) and m.get("name") in MEASURE_NAMES:
            meas[m["name"]] = m.get("value")
    log = (corner.get("artifacts") or {}).get("log")
    return {
        "corner_id": corner.get("corner_id"),
        "process": corner.get("process"),
        "status": corner.get("status"),
        "sample_index": (mc or {}).get("sample_index"),
        "seeds": None if mc is None else {k: mc.get(k) for k in MC_SEED_KEYS},
        "measurements": meas,
        "log": log,
        "diagnostics": corner.get("diagnostics"),
        "runtime_s": corner.get("runtime_s"),
        "where": where,
    }


_MEAS_RE: dict = {}


def _meas_re():
    """`^m_<name> = <finite value>$` -- the shape ngspice's `print m_*` emits.

    Same pattern as ``harness.runner``'s scanner, kept here (stdlib-only) so
    this module imports without the harness.
    """
    if "re" not in _MEAS_RE:
        import re
        _MEAS_RE["re"] = re.compile(
            r"^\s*m_(\w+)\s*=\s*([-+]?[0-9.]+(?:[eE][-+]?[0-9]+)?)\s*$", re.MULTILINE)
    return _MEAS_RE["re"]


def parse_measurements(text: str) -> dict[str, float]:
    """Finite ``m_* = value`` prints from one ngspice log, keyed WITH the m_ prefix."""
    out: dict[str, float] = {}
    for m in _meas_re().finditer(text):
        try:
            v = float(m.group(2))
        except ValueError:
            continue
        if math.isfinite(v):
            out[f"m_{m.group(1)}"] = v
    return out


def attach_log_measurements(legs: dict[str, list[dict]], read_text, label_prefix: str = "") -> None:
    """Parse each unit's ``m_*`` values out of its ngspice log, in place.

    ``read_text(unit) -> str`` is the caller's I/O hook (run_probe resolves
    the report's artifact path; tests pass log text directly). The klt
    report's ``measurements`` array only carries the DECLARED sentinel, so
    the observables come from the logs. A unit whose log is missing or does
    not print every observable raises :class:`ReportError` -- the method
    probe must surface that, not average around it.
    """
    for leg, units in legs.items():
        for u in units:
            try:
                text = read_text(u)
            except OSError as exc:
                raise ReportError(f"{label_prefix}{leg} {u['where']}: cannot read log: {exc}")
            if text is None:
                raise ReportError(f"{label_prefix}{leg} {u['where']}: unit has no log artifact")
            parsed = parse_measurements(text)
            missing = [n for n in MEASURE_NAMES if n not in parsed]
            if missing:
                raise ReportError(
                    f"{label_prefix}{leg} {u['where']}: {u['process']} sample "
                    f"{u['sample_index']} log is missing {missing} "
                    f"(status {u['status']!r}, diagnostics {u['diagnostics']})")
            u["measurements"].update(parsed)


def samples_from_report(report: dict, *, expected_n: int, label: str = "report") -> dict[str, list[dict]]:
    """Per-corner sample lists from a klt sim JSON report, in request order.

    Raises :class:`ReportError` when the report carries no corners, when any
    requested corner is missing entirely, or when a corner returned fewer
    than ``expected_n`` units -- a silently collapsed Monte Carlo (an older
    runner ignoring the ``monte_carlo`` block) must be *detected*, never
    averaged over.
    """
    corners = report.get("corners") if isinstance(report, dict) else None
    if not isinstance(corners, list) or not corners:
        raise ReportError(f"{label}: no corners list in the report")
    by_process: dict[str, list[dict]] = {name: [] for name in CORNERS}
    for i, corner in enumerate(corners):
        unit = _unit_from_corner(corner, f"{label}[{i}]")
        proc = str(unit["process"])
        if proc not in by_process:
            raise ReportError(f"{label}[{i}]: unexpected process {proc!r} (asked for {list(CORNERS)})")
        by_process[proc].append(unit)
    for name, units in by_process.items():
        if not units:
            raise ReportError(f"{label}: corner {name!r} returned no units at all")
        got = len(units)
        if got < expected_n:
            raise ReportError(
                f"{label}: corner {name!r} returned {got} units, expected {expected_n} -- "
                "the monte_carlo expansion collapsed (older runner ignoring the block?); "
                "refusing to compute statistics over a partial sample")
        if any(u["sample_index"] is None for u in units):
            raise ReportError(f"{label}: corner {name!r} has units without monte_carlo sample identity")
        units.sort(key=lambda u: u["sample_index"])
    return by_process


def values(units: list[dict], name: str) -> list[float]:
    """Finite ``name`` values in sample order; a missing/non-finite value raises.

    A unit klt graded ``error`` carries null measurements -- that is a method
    failure this probe must surface, not average around.
    """
    out = []
    for u in units:
        v = u["measurements"].get(name)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
            raise ReportError(
                f"{u['where']}: {u['process']} sample {u['sample_index']} has no finite {name} "
                f"(status {u['status']!r}, diagnostics {u['diagnostics']})")
        out.append(float(v))
    return out


def dist(values_list: list[float]) -> dict:
    """n / mean / sigma (ddof=1) / min / max for one observable."""
    n = len(values_list)
    if n < 2:
        raise ReportError("distribution needs >= 2 samples")
    return {"n": n, "mean": fmean(values_list), "sigma": stdev(values_list),
            "min": min(values_list), "max": max(values_list)}


def max_abs_dev(values_list: list[float], target: float) -> float:
    return max(abs(v - target) for v in values_list)


def rel_diff(a: float, b: float, scale: float) -> float:
    """|a - b| relative to *scale* (the caller pins what 'relative' means)."""
    return abs(a - b) / scale


def per_sample_max_rel(units_a: list[dict], units_b: list[dict], name: str,
                       scale: float) -> float:
    """Max relative difference of ``name`` between two legs, per shared sample.

    Units are matched by ``sample_index`` (the seed-contract identity), never
    by position: the local agreement leg carries only sample 0 while the
    batch leg carries all n. If both legs have the same length their index
    sets must be IDENTICAL -- a misaligned pair of same-length legs is a
    reproducibility defect in itself, not a number.
    """
    by_idx_a = {u["sample_index"]: u for u in units_a}
    by_idx_b = {u["sample_index"]: u for u in units_b}
    if len(units_a) == len(units_b) and set(by_idx_a) != set(by_idx_b):
        raise ReportError(
            f"per-sample comparison misaligned: sample sets {sorted(by_idx_b)[:4]}... "
            f"do not match {sorted(by_idx_a)[:4]}...")
    missing = sorted(set(by_idx_b) - set(by_idx_a))
    if missing:
        raise ReportError(f"per-sample comparison: samples {missing[:4]} absent from the batch leg")
    worst = 0.0
    for idx, ub in by_idx_b.items():
        ua = by_idx_a[idx]
        va = ua["measurements"].get(name)
        vb = ub["measurements"].get(name)
        for v in (va, vb):
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
                raise ReportError(f"per-sample comparison: sample {idx} missing finite {name}")
        worst = max(worst, rel_diff(float(va), float(vb), scale))
    return worst


def evaluate(*, batch: dict[str, list[dict]], rerun: dict[str, list[dict]] | None,
             local: dict[str, list[dict]] | None) -> dict:
    """Run every method gate and return the findings + overall status.

    ``batch`` is the primary Monte Carlo leg; ``rerun`` (same request, same
    seed, second submit) carries the fixed-seed reproducibility gate; ``local``
    (n=1, local backend, same corners in the same order) carries the
    local-vs-batch agreement gate. ``rerun``/``local`` may be None only when
    the caller explicitly skipped them (``--skip-rerun``/``--skip-local``);
    a status that needs the skipped leg is then reported as ``None`` instead
    of guessed.
    """
    findings: dict = {"gates": {}, "distributions": {}, "notes": []}
    status = "MC_METHOD_WORKS"

    # --- distributions + control gates on the primary leg -------------------
    try:
        ratio_mm = dist(values(batch["hbt_typ_mismatch"], "m_ratio"))
        off_mm = dist(values(batch["hbt_typ_mismatch"], "m_off"))
        ratio_st_units = batch["hbt_typ_stat"]
        ratio_st = dist(values(ratio_st_units, "m_ratio"))
        ic1_st = dist(values(ratio_st_units, "m_ic1"))
        ratio_no = dist(values(batch["hbt_typ"], "m_ratio"))
        off_no = dist(values(batch["hbt_typ"], "m_off"))
    except ReportError as exc:
        return {"status": "MC_METHOD_CONTROL_FAIL", "findings": findings,
                "reason": f"primary leg not gradeable: {exc}"}

    findings["distributions"] = {
        "hbt_typ_mismatch": {"m_ratio": ratio_mm, "m_off": off_mm},
        "hbt_typ_stat": {"m_ratio": ratio_st, "m_ic1": ic1_st},
        "hbt_typ": {"m_ratio": ratio_no, "m_off": off_no},
    }

    dev_no = max_abs_dev(values(batch["hbt_typ"], "m_ratio"), 1.0)
    dev_st = max_abs_dev(values(batch["hbt_typ_stat"], "m_ratio"), 1.0)
    off_dev_no = max_abs_dev(values(batch["hbt_typ"], "m_off"), 0.0)
    nominal_exact = dev_no <= RATIO_EXACT_TOL and off_dev_no <= OFFSET_EXACT_TOL_V
    stat_cancels = dev_st <= RATIO_EXACT_TOL
    mismatch_sampled = ratio_mm["sigma"] >= MISMATCH_SIGMA_MIN
    findings["gates"] = {
        "nominal_exact": nominal_exact,
        "stat_global_cancels": stat_cancels,
        "mismatch_sampled": mismatch_sampled,
        "max_abs_ratio_dev": {"hbt_typ": dev_no, "hbt_typ_stat": dev_st,
                              "hbt_typ_mismatch": max_abs_dev(values(batch["hbt_typ_mismatch"], "m_ratio"), 1.0)},
        "max_abs_offset_dev_v": {"hbt_typ": off_dev_no,
                                 "hbt_typ_mismatch": max_abs_dev(values(batch["hbt_typ_mismatch"], "m_off"), 0.0)},
        "mismatch_sigma_vs_card": {
            "sigma_ratio_measured": ratio_mm["sigma"],
            "card_area_sigma": CARD_AREA_SIGMA,
            "expected_ratio_sigma_order": CARD_AREA_SIGMA * math.sqrt(2.0),
        },
    }
    if not (nominal_exact and stat_cancels and mismatch_sampled):
        status = "MC_METHOD_CONTROL_FAIL"
        findings["notes"].append(
            "control gate failed: nominal_exact=%s stat_global_cancels=%s mismatch_sampled=%s"
            % (nominal_exact, stat_cancels, mismatch_sampled))

    # --- fixed-seed reproducibility (batch vs rerun, same request) ----------
    if rerun is not None:
        repro_worst = 0.0
        for name in CORNERS:
            worst = max(per_sample_max_rel(batch[name], rerun[name], "m_ratio", 1.0),
                        per_sample_max_rel(batch[name], rerun[name], "m_off", 1.0))
            repro_worst = max(repro_worst, worst)
        findings["gates"]["reproducibility_max_rel"] = repro_worst
        if repro_worst > REPRO_TOL and status == "MC_METHOD_WORKS":
            status = "MC_METHOD_REPRODUCIBILITY_FAIL"
            findings["notes"].append(
                f"fixed-seed rerun differs by {repro_worst:.3e} (rel) -- exceeds {REPRO_TOL:.0e}")
    else:
        findings["gates"]["reproducibility_max_rel"] = None

    # --- local-vs-batch agreement (same seed, local unit vs fleet unit) -----
    if local is not None:
        agree_worst = 0.0
        detail = {}
        for name in CORNERS:
            worst = max(per_sample_max_rel(batch[name], local[name], "m_ratio", 1.0),
                        per_sample_max_rel(batch[name], local[name], "m_off", 1.0))
            detail[name] = worst
            agree_worst = max(agree_worst, worst)
        findings["gates"]["local_vs_batch_max_rel"] = agree_worst
        findings["gates"]["local_vs_batch_per_corner_rel"] = detail
        if agree_worst > LOCAL_AGREEMENT_TOL and status == "MC_METHOD_WORKS":
            status = "MC_LOCAL_AGREEMENT_FAIL"
            findings["notes"].append(
                f"local-vs-batch differs by {agree_worst:.3e} (rel) -- exceeds "
                f"{LOCAL_AGREEMENT_TOL:.0e}; cross-build (ngspice local vs fleet) agreement "
                "is the number the record must state")
    else:
        findings["gates"]["local_vs_batch_max_rel"] = None

    return {"status": status, "findings": findings, "reason": None}


def sabotage(legs: dict[str, list[dict]], mode: str) -> dict:
    """Perturb an ingested leg set the way each named defect would.

    ``stat_noise``  -- a stat-corner sample's ratio is nudged off 1 by 1e-3
                       (what real uncorrelated noise or a per-instance draw
                       leaking into the stat corner would look like).
    ``mismatch_flat`` -- every mismatch-corner ratio is forced to exactly 1
                       (what a runner silently ignoring the mismatch card
                       looks like).
    The classification of the sabotaged legs MUST degrade; the tests and
    ``run_probe.py --sabotage <mode> --reparse`` assert that.
    """
    legs = {name: [dict(u) for u in units] for name, units in legs.items()}
    if mode == "stat_noise":
        u = legs["hbt_typ_stat"][0]
        u["measurements"]["m_ratio"] = u["measurements"]["m_ratio"] + 1e-3
    elif mode == "mismatch_flat":
        for u in legs["hbt_typ_mismatch"]:
            u["measurements"]["m_ratio"] = 1.0
            u["measurements"]["m_off"] = 0.0
    else:
        raise ValueError(f"unknown sabotage mode {mode!r}")
    return evaluate(batch=legs, rerun=None, local=None)
