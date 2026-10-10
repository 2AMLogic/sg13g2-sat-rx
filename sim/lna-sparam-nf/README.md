# sim/lna-sparam-nf — S-parameter, stability and noise-figure bench

Backs spec rows 2-6, 17 and 18 (see `spec/row-coverage.json` for each row's
honest verdict). The DUT is `design/lna_stage1` with **ideal lossless L/C
matching**; no row is claimed met. Method, NF convention and the corrected-T0
history are in [`../README.md`](../README.md) ("lna-sparam-nf"); the bench is
declared in `testbench/tb.json` and `testbench/lna_stage1.spice`.

Records under `records/` are append-only. The two oldest records name the PDK
as `unknown` (the harness reads a `SOURCES` file; IHP ships `.fetched-version`
instead, see "PDK pin" in `../README.md`). They are not edited. The PDK
revision actually used is pinned by `../pdk-artifact.json` and verified before
any simulator starts.

## Cold start

From a clean checkout, repo root:

```
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-test.txt                 # numpy + pytest
# 1. Pins: IHP-Open-PDK v0.3.0 (commit 5cccb161f7492697cfa52eb14dc03beb00bdca9e)
#    and ngspice 46; fetch/build steps are in ../README.md ("Reproducing the
#    hosted sim-smoke job locally"). Then:
export SG13G2_PDK_PATH=<path to the pinned ihp-sg13g2>
python3 -m pytest sim/lna-sparam-nf/tests -q         # no simulator needed
(cd sim && python3 -m harness.cli verify-pdk --require-ngspice)   # model hashes + ngspice major
SG13G2_REQUIRE_NGSPICE=1 sim/characterize.sh smoke    # hbt_typ only, writes nothing
SG13G2_REQUIRE_NGSPICE=1 sim/characterize.sh selftest # negative controls
```

Full 27-point campaign (3 process x 3 temperature x 3 supply). On a
workstation: `(cd sim && python3 -m harness.cli run lna-sparam-nf --corners hbt)`.
On a shared dispatch host the grid goes to the `klt sim` batch fleet instead
(never a local `ngspice -b` loop):

```
python3 sim/lna-sparam-nf/run.py characterize --no-stage-models --runner-version-check warn \
    --supersedes <previous-record-id>
```

Where the result lands: a new `records/<UTC-date>-<time>-<git>.md` plus
`corners/<id>/*.log` and `netlist-snapshots/<id>.spice`. A re-run mints a new
id and never overwrites. `.github/scripts/check_evidence_formats.py` validates
the layout.
