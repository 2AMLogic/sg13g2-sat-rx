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

Full 27-point campaign. A multi-point `harness.cli run` submits the grid as
`klt sim` requests to the batch fleet by default (one request per supply,
all process x temperature corners in each), so it is safe on a shared
dispatch host; a failed submit records nothing and never falls back to a
local loop. `--backend local` runs the old sequential `ngspice -b` loop
(workstation only). Since issue #135 the window is exactly 65536 = 2^16
samples over an exactly-80-ns DFT record (endpoint-aligned, so the saved grid
is uniform), so both builds run the identical transform; pfund_dbm,
conversion gain and lo_rf_leak_dbm agree across backends within 0.002 dB.
Since issue #165 the deck sweeps the two-tone drive and extrapolates IIP3
from the stated 1:3-slope window, with a one-tone floor control and in-deck
slope checks; pim3_dbm/iip3_dbm are measured at least 20 dB above the
one-tone floor at every PVT point. See the experiment's tb.json evidence
notes for the swept method, the tracked-sideband choice and the convergence
study.

Issue-#181 resolution of the #165 method's open backend bound: the published
`iip3_dbm` is no longer the free two-line intersection (measured ~1.4 dB
local-vs-batch; it rotates with the fitted IM3 slope the two ngspice builds
agree to only ~0.10) but the **slope-3-constrained read at the top-of-fit
drive**, `IIP3 = Pin + (Pfund - Pim3)/2`, whose measured backend bound at
hbt_typ/27C/2.50V is **0.0492 dB** (ngspice-42 +3.8513 vs ngspice-46 +3.8021,
within #135's 0.1 dB criterion). The free intersection and the window-centroid
mean (~0.27 dB bound) remain published per-corner diagnostics
(`iip3_free_intersection_dbm`, `iip3_window_centroid_dbm`); the slope gates,
`fit_n = 5` window pin and the >= 20 dB one-tone floor margin are unchanged.
The two open follow-ups from the #165/#180 records stand: the low-drive IM3
reads are still not tolerance-converged (reltol alone fails the slope gate),
and at 6 of 27 PVT corners the static fit window contains no valid 1:3 region
(hot corners compress inside it): the slope gates fail there by design, no
IIP3 is published at those corners, and `characterize.sh smoke` exercises the
temperatures the stated window covers for that reason.

Single local point (debug probe, allowed on a dispatch host):

```
(cd sim && python3 -m harness.cli run mixer-conversion-iip3 --backend local \
   --corners hbt_typ --temperatures 27 --supplies 2.5 \
   --subset-reason "..." [--supersedes <record-id> ...])
```

```
(cd sim && python3 -m harness.cli run mixer-conversion-iip3 --corners hbt)
```

Where the result lands: a new `records/<UTC-date>-<time>-<git>.md` plus
`corners/<id>/*.log` and `netlist-snapshots/<id>.spice`; a re-run mints a new
id and never overwrites. `.github/scripts/check_evidence_formats.py` validates
the layout.
