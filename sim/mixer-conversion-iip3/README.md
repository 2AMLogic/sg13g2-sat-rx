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
(workstation only). The FFT-bin metrics USED to depend on the ngspice FFT
build -- the fleet's ngspice-46 does not zero-pad a non-power-of-two `fft`
input, this host's builds do -- so the 20260912 record (old 8001-sample
window) is not comparable across the two backends. Since issue #135 the
window is exactly 65536 = 2^16 samples over an exactly-80-ns DFT record, so
both builds run the identical transform. pfund_dbm, conversion gain and
lo_rf_leak_dbm then agree across backends within 0.002 dB. pim3_dbm and
iip3_dbm do NOT agree (5.1 / 2.6 dB): they sit on the transient sampler's
floor and are not a device IM3/IIP3. See this experiment's tb.json evidence
notes.

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
