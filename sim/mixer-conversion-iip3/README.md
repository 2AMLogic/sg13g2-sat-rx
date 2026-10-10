# sim/mixer-conversion-iip3 — conversion gain, LO leakage, two-tone IIP3

A **placeholder** single-`npn13G2` stage (`testbench/mixer_ce_placeholder.spice`,
declared in `testbench/tb.json`). It proves the transient + coherent-FFT
methodology against the real device model; **its numbers are not spec
evidence** and must not be compared to any `spec/target-spec.md` row. SSB noise
figure is not measured (ngspice has no pnoise); see
[`../README.md`](../README.md) ("mixer-conversion-iip3", "mixer-nf-method").

Records under `records/` are append-only. The only record predates the model
pin and names the PDK as `unknown` (the harness reads a `SOURCES` file; IHP
ships `.fetched-version`). It is not edited. The PDK revision a fresh run uses
is pinned by `../pdk-artifact.json` and verified before any simulator starts.

## Cold start

From a clean checkout, repo root:

```
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-test.txt
# Pins: IHP-Open-PDK v0.3.0 (commit 5cccb161f7492697cfa52eb14dc03beb00bdca9e)
# and ngspice 46; fetch/build steps are in ../README.md ("Reproducing the
# hosted sim-smoke job locally"). Then:
export SG13G2_PDK_PATH=<path to the pinned ihp-sg13g2>
(cd sim && python3 -m harness.cli verify-pdk --require-ngspice)
SG13G2_REQUIRE_NGSPICE=1 sim/characterize.sh smoke      # hbt_typ only, writes nothing
SG13G2_REQUIRE_NGSPICE=1 sim/characterize.sh selftest   # negative controls
```

Full 27-point campaign (workstation only; the transient grid is a local
`ngspice -b` loop, so do not run it on a shared dispatch host):

```
(cd sim && python3 -m harness.cli run mixer-conversion-iip3 --corners hbt)
```

Where the result lands: a new `records/<UTC-date>-<time>-<git>.md` plus
`corners/<id>/*.log` and `netlist-snapshots/<id>.spice`; a re-run mints a new
id and never overwrites. `.github/scripts/check_evidence_formats.py` validates
the layout.
