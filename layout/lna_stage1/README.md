# layout/lna_stage1 — LNA stage-1 device-group layout study (issue #198)

**NON-CLAIMING. This is not the LNA stage-1 layout, and it cites no T1 item.**
`signoff/block-manifest.json` and `signoff/tier-report.json` are unchanged by
this directory: T1 items 2 (Layout), 3 (DRC clean), 4 (LVS clean) and 11 (Power
delivery) all stay `unmet` / `no_evidence`. The reason is the whole point of
this record and is derived below, not asserted.

Recorded results here are append-only evidence. A later run supersedes one of
these by adding a record that says why — never by editing or deleting one.

## The result, first

Issue #198 set out to draw "only the elements that have PDK primitives" and
cite items 2 and 3 from the result, with the three ideal inductors named as the
one gate. **Measured against the netlist and the pinned PDK, the drawable set
is far smaller than that premise assumed, and the gate is far wider than the
inductors.** Of the stage's 18 elements:

| | elements | verdict |
|---|---|---|
| 3 | `Xq1`, `Xq2`, `Xqr` | a PDK primitive is named in the design (`npn13G2`) |
| 8 | `Rref`, `Rbr`, `Rer`, `Rbias`, `Rd`, `Re1`, `R1b`, `R2b` | **no PDK primitive is selected** — generic `res.sym` |
| 4 | `Cb2`, `Cshunt`, `Cblk_in`, `Cm` | **no PDK primitive is selected** — generic `capa.sym` |
| 3 | `Lin`, `Lfeed`, `Le1` | **no PDK model exists at all** — generic `ind.sym` |

and of the three that *do* name a primitive, only one (`Xqr`, `Nx=1`) is
drawable at its designed value.

So the honest outcome is the one issue #198's own acceptance criterion 6 admits
as complete and successful: **items 2 and 3 are not claimed for this stream,
and this is the recorded reason.** What a layout of 1 of 18 elements at its
designed geometry would be claiming item 2 ("committed GDS/OASIS … of the
block") for is a device-placement study, which is what this directory is and
says it is.

Full per-element derivation, machine-readable and regenerable:
[`realizability.json`](realizability.json), written by
[`realizability.py`](realizability.py).

## Why each class is gated

### The resistors: no flavour is selected, and the choice spans ~194× in area

`design/lna_stage1.sch` uses xschem's generic `res.sym` eight times, so
`design/netlist/lna_stage1.spice` carries a resistance and no device. The PDK
ships three poly-resistor flavours, whose typical sheet resistances
(`libs.tech/ngspice/models/cornerRES.lib`) are **`rsil` 7.0 Ω/□**, **`rppd`
260 Ω/□** and **`rhigh` 1360 Ω/□**. At the PDK's own 0.5 µm minimum resistor
width:

| element | value | `rhigh` | `rppd` | `rsil` |
|---|---|---|---|---|
| `Rref` | 8 kΩ | 5.9 □ / 1.5 µm² | 30.8 □ / 7.7 µm² | 1142.9 □ / 285.7 µm² |
| `Rbr` | 60.9 kΩ | 44.8 □ / 11.2 µm² | 234.2 □ / 58.6 µm² | 8700.0 □ / 2175.0 µm² |
| `Rbias` | 10 kΩ | 7.4 □ / 1.8 µm² | 38.5 □ / 9.6 µm² | 1428.6 □ / 357.1 µm² |
| `R2b` | 7 kΩ | 5.1 □ / 1.3 µm² | 26.9 □ / 6.7 µm² | 1000.0 □ / 250.0 µm² |
| `R1b` | 1.5 kΩ | 1.1 □ / 0.3 µm² | 5.8 □ / 1.4 µm² | 214.3 □ / 53.6 µm² |
| `Rd` | 465 Ω | *below min length* | 1.8 □ / 0.4 µm² | 66.4 □ / 16.6 µm² |
| `Rer` | 24 Ω | *below min length* | *below min length* | 3.4 □ / 0.9 µm² |
| `Re1` | 3 Ω | *below min length* | *below min length* | *below min length* |

Two things follow. **The flavour choice is a real design decision**: for the
five elements all three flavours can reach, it moves the resistor body area by
a factor of 194, and area at Ka band is parasitic capacitance to substrate on a
node that sets gain and match. And **no single flavour serves the whole stage**:
`Rbr` is impractical in `rsil` (2175 µm² of body) while `Re1` is below minimum
geometry in every flavour at minimum width, so it needs a deliberately wide,
short body. Nothing in `spec/` records any of these choices.

(The table's model is first-order, `R = rsh · L / W`, and ignores the
drawn-to-electrical correction `rsil_lwd` = 0.04 µm and end/contact resistance.
That is good to the order of magnitude a realizability verdict needs and is not
a device sizing; a sizing comes from the PDK model.)

### The capacitors: two of four exceed the PDK device's own declared maximum

Same shape of gap — generic `capa.sym`, so no primitive is selected — but with
a harder edge. The PDK's `cmim` PCell declares, in
`libs.tech/klayout/python/sg13g2_pycell_lib/sg13g2_tech.json`, an area
capacitance of **1.5 fF/µm²** (`cmim_caspec`; independently confirmed by
`cap_carea = 1.5E-15` in `cornerCAP.lib`, with ±10 % at the corners) and a
**maximum capacitance per device of 8 pF** (`cmim_maxC`). The 3-terminal
`rfcmim` reaches 1.5 nF (`rfcmim_maxC`) but adds a substrate node.

| element | value | plate area at 1.5 fF/µm² | inside `cmim`'s 8 pF max? |
|---|---|---|---|
| `Cm` | 57.8 fF | 38.5 µm² (6.2 µm square) | yes |
| `Cshunt` | 170 fF | 113.3 µm² (10.6 µm square) | yes |
| `Cb2` | 10 pF | 6 666.7 µm² (81.6 µm square) | **no — 1.2× over** |
| `Cblk_in` | 1 nF | 666 666.7 µm² (816.5 µm square) | **no — 125× over** |

`Cblk_in` is the sharp one. At the PDK's own MIM density, 1 nF needs **0.67 mm²
of plate** — about 134× the entire bounding box of the stream in this directory
(4 965 µm²) — and the only PDK primitive whose declared range reaches it is the
3-terminal `rfcmim`, which the 2-terminal schematic element does not have a node
for. This is a **circuit-level** gap, not a layout decision: no choice of
geometry realizes it. `Cb2` at 10 pF needs either `rfcmim` or two parallel
`cmim` devices — again a decision, not a lookup.

### The inductors: unchanged, and already recorded

`spec/target-spec.md` records that the PDK ships **no inductor model and no
transmission-line model**; `inductor.sym`/`inductor3.sym` are symbols with no
backing subcircuit, and the netlist's own header says these elements are ideal.
`spec/decision-records/0001-band-selection-ka-vs-ku.md` records the openEMS
extraction: the single-turn `p1` geometry is 98.5 pH, the multi-turn geometries
self-resonate below the ratified band, and "Multi-turn spirals are dead at Ka
band". `Lin` (1.41 nH) and `Lfeed` (0.962 nH) are an order of magnitude above
the viable single-turn datapoint. Cited, not re-derived here.

### The HBTs: drawable, but not at the designed emitter multiplicity

`Xqr` is `Nx=1` and is drawn exactly. `Xq1` and `Xq2` are `Nx=8` — one HBT with
eight emitter windows inside a single collector/base region. The pinned PDK's
primitive stream (`libs.ref/sg13g2_pr/gds/sg13g2_pr.gds`) ships only the
fixed-geometry `Nx=1` cell, and the PDK's own parametrized `npn13G2` PCell —
which would draw the real multi-emitter device — **is not instantiable in this
environment**: `klt gen --list-pdk-pcells` reports both `sg13g2_pycell_lib` and
`sg13g2_native_pcell_lib` as unavailable for `missing_dependency: "cni"`,
because the PDK vendors that compat shim at
`libs.tech/klayout/python/pycell4klayout-api`, which is present but **empty** in
this install (an uninitialized submodule). So this study draws `Nx=8` as eight
parallel `Nx=1` units — a different structure, with different base resistance
and emitter interconnect parasitics from the designed device. That is why it is
a floorplan study of the right device *count*, and not the designed geometry.

The same missing shim is why no PDK-parametrized `rsil` or `cmim` could be
instanced even once a flavour and geometry were chosen. `klt gen`'s own
built-in `res_array` / `cap_array` generators do support this PDK family (they
draw an `rsil`/`rppd`/`rhigh` body and a MiM stack from base layers), so the
tooling is not the binding constraint — the missing ratified decision is.

## What would unblock item 2

A `spec/` decision record covering **passive realization for the LNA stage**,
not only the inductors:

1. which PDK primitive realizes each resistor, and at what W/L — or that the
   resistors move off-chip;
2. which MIM primitive realizes each capacitor, and what happens to `Cb2` and
   `Cblk_in`, whose values no 2-terminal PDK primitive declares a range for
   (a circuit change, an `rfcmim` with its substrate node admitted into the
   schematic, or the elements moving off-chip);
3. how `Lin`, `Lfeed` and `Le1` are realized — re-designed to
   single-turn-realizable values, moved off-chip with boundary ports, or
   EM-extracted as custom structures.

**Filing or ratifying that decision record is out of scope for issue #198 and
is an operator call.** Each of these changes the circuit, so each would
invalidate the characterization #250 is about to run on the post-#79 core;
#110 (the EM passive campaign) is the evidence half for (3). Per this repo's
own rule, an agent does not pick one to make a result pass.

## What is drawn, and what the chain measured

`lna_stage1_devices.gds` (`sha256:46c6b87e…d98a8`, 15 486 bytes), top cell
`lna_stage1_devices`, regenerated byte-identically by
[`generate.py`](generate.py):

- **17 `npn13G2` unit instances** — `Xq1`×8, `Xq2`×8, `Xqr`×1 — on a 9 µm
  pitch in three rows.
- **A 360-instance `ptap` substrate guard ring** with a Metal1 band tying every
  tap, labelled `gnd`.
- **Per-terminal Metal1/Metal2 buses** making each device group one node per
  terminal, labelled with the netlist's own net names (`c1`, `b1`, `e1`, `oc`,
  `b2`, `nr`, `br`, `er`), including the real cascode connection: `Xq1`'s
  collector and `Xq2`'s emitter are both net `c1` and are strapped together
  through a Via1 column.
- **A `vdd` Metal1 rail**, deliberately unloaded — every element that would
  connect to it (`Rref`, `Rd`, `R1b`, `Lfeed`) is absent — so that the ERC
  supply spec has a second declared supply to resolve. **It is not evidence
  that the stage's supply distribution works.**
- **Absent: every resistor, capacitor and inductor in the stage.**

Pin identities were measured from the PDK cell's own `E`/`B`/`C` text on layer
63/0: the centre Metal2 stack is the **emitter**, the lower Metal1 strip the
**base**, the upper Metal1 strip the **collector**.
`layout/probe-readiness/generate_probe.py`'s comments assign those three
differently; that probe is non-claiming, extracts no bipolar device, and is not
edited here — but its assignment should not be carried into new work.

### Records, `runs/klt-0.8.0/`

Taken from a throwaway `uv` venv holding `klayout-tools==0.8.0`, this repo's
declared pin (`layout/toolchain.json` → `klt_install`). The **host** tool
(`klt 0.9.2.dev1029+g76f47afa48f1`) was neither used nor modified.
`exit-codes.txt` carries all eight exit codes, and each agrees with its own
record's status.

| Command | Result | Record |
|---|---|---|
| `klt drc --deck sg13g2` | **`clean`**, 0 violations, exit 0 | `drc.json` |
| `klt extract --deck sg13g2` | `extracted`, exit 0 — **`device_count: 0`** | `extract.json`, `extracted.spice` |
| `klt erc` (supply spec) | **`erc_status: clean`**, 0 findings, exit 4 | `erc.json` |
| `klt ring-check` ×3 (Activ, pSD, Metal1) | **`continuous`**, 0 violations, exit 0 | `ringcheck_{activ,psd,m1}.json` |
| `klt economy` | 80.44 × 61.72 µm, 4 964.76 µm² bbox, 29.74 % utilisation, 1 476.34 µm² drawn | `economy.json` |
| `klt lvs` | `mismatch`, exit 3 — expected, see below | `lvs-devices.json` + `.request.json` |

Host-path hygiene: `klt env-provenance lint-envelope runs/klt-0.8.0/*.json` →
`clean: 0 absolute path(s) in 9 file(s)`.

Engine disclosure, as at the probe's 0.8.0 re-run: the bundled klayout is
0.30.13 while klt 0.8.0 declares it was tested against 0.30.12, so `drc.json`
and `lvs-devices.json` carry `provenance.klayout_version_mismatch: true` and
each printed the disclosure warning (kept verbatim in `drc.stderr` /
`lvs-devices.stderr`). Per that warning the **verdict** is unaffected; derived
counts may differ. Deck: `sg13g2`, content hash
`sha256:1c95db40…6dd15`, `released: true` — the same deck hash as
`layout/probe-readiness/runs/klt-0.8.0/`.

### DRC: what "clean" was measured inside

Item 3's text requires the deck's coverage gaps to be enumerated with the
claim, not hidden behind `clean`. No item-3 claim is made here, but the
enumeration is recorded anyway because it is what any later claim would have to
quote — and because this stream's figure is *lower* than the probe's 24, since
it draws fewer layer types (no GatPoly, no MIM, no TopMetal):

- **`coverage.rules_checked` — 15 rules**: `activ.enclosing.cont.1`,
  `activ.space.1`, `activ.width.1`, `cont.space.1`, `cont.width.1`,
  `metal1.enclosing.via1.1`, `metal1.space.1`, `metal1.width.1`,
  `metal2.space.1`, `metal2.width.1`, `psd.area.1`, `psd.space.1`,
  `psd.width.1`, `via1.space.1`, `via1.width.1`.
- **`coverage.rules_skipped` — 47 rules** the deck carries but this run did not
  evaluate, every one of them for a layer this stream does not draw (the
  `gatpoly.*`, `metal3/4/5.*`, `nwell.*`, `mim.*`, `topmetal*.*`, `topvia*.*`
  and `via2/3/4.*` families).
- **`coverage.deck_scope` — 19 chapters**: `Act`, `Cnt`, `Gat`, `M1`, `M2`,
  `M3`, `M4`, `M5`, `MIM`, `NW`, `TM1`, `TM2`, `TV1`, `TV2`, `V1`, `V2`, `V3`,
  `V4`, `pSD`. The foundry DRM is larger than this; `coverage.unmodeled_rules`
  names 14 rules the deck knows it does not model at all (the `LU.*`
  latch-up and `Pad.*` families).
- **`coverage.layers_in_stream_without_rules` — 9 layers** drawn here that the
  deck has no rule for: `7/21`, `8/2`, `8/25`, `10/2`, `10/25`, `26/0`, `33/0`,
  `51/0`, `63/0` (pin, label and device-recognition layers).

A `clean` verdict from 15 rules inside a 19-chapter scope is a much narrower
statement than "this layout meets the SG13G2 DRM", and nothing in this
directory says otherwise.

### ERC: the supply half, and what it does and does not prove

[`erc-supply-spec.json`](erc-supply-spec.json) declares `vdd` and `gnd` as
`"kind": "supply"` with `islands: 1`, a three-level stackup
(GatPoly → Metal1 → Metal2) with Via1 between the metals, and one `ties[]`
entry for the substrate tap ring. The run (`erc.json`) reports:

- **both supplies resolve to exactly one electrical island each**
  (`matched_islands: 1`, `expected_islands: 1`);
- **`erc_findings: []`** — zero `erc.unconnected_net`, zero `erc.supply_short`,
  zero `erc.missing_tie`;
- **`erc_coverage.skipped: []`** — no degenerate-tie reasons, so all three
  checks were real work: `erc_coverage.checked` is
  `erc.missing_tie:["psub_ring_tap"]`, `erc.net_connectivity:["gnd"]`,
  `erc.net_connectivity:["vdd"]`;
- **`erc_coverage.layers_in_stream_without_declaration` — 9 layers**: `1/20`,
  `6/0`, `7/21`, `8/2`, `10/2`, `26/0`, `33/0`, `51/0`, `63/0`. Note `6/0` is
  **Cont**: contacts are outside this spec's declared stackup, so vertical
  connectivity between Activ and Metal1 inside the PDK cells is not modelled by
  this run — the tie check reaches the tap through the `connect_to: "Metal1"`
  declaration, not through a modelled contact.

Two disclosures the run makes about itself, and this record repeats rather than
buries:

- The tie is graded in **both** `erc_coverage.checked_by_assertion` and
  `checked_by_well_assertion`: its tap geometry and its substrate region are
  the *caller's* word (`tap_boxes` naming the three ring sides,
  `well_boxes` naming the substrate region), not geometry derived from a PDK
  marker. SG13G2 draws no tap-only marker layer — a `ptap`'s tap is
  `Activ ∩ pSD`, and so is an HBT's outer region — so a marker-derived
  narrowing would have removed nothing and graded as skipped work.
  `well_assertion_coverage` records `extent_uncovered_fraction: 0.1416`, i.e.
  the asserted substrate region deliberately leaves the stream's northern
  strip (above y = 45 µm, holding the top ring row and the `vdd` rail) outside
  the claim; see the gap note below for why it had to.
- `status` is **`not_checked`** (exit 4) because the run used
  `--findings-only`: this stream draws no gate-role geometry at all (no MOS, no
  poly resistor), so the antenna half has nothing to accumulate. Gate on
  `erc_status`, which is `clean`. The supply/connectivity findings are
  identical to a full run.

**What this does not prove.** These are the rails of a stream holding 3 of the
stage's 18 elements. `vdd` is an unloaded rail. So this is *not* item 11
evidence for the block, and item 11 is not cited: it stays `unmet` /
`no_evidence` rather than being rendered `lvs_did_not_pass`, which would have
required citing an ERC + LVS pair for a stream that is not the block's layout.

### LVS: `mismatch`, and the reason is the known declined gap

`lvs-devices.json`: `status: "mismatch"`, exit 3, `mismatch_count: 21`,
`error_count: 19`, `counts.devices` = `{layout: 0, reference: 0, matched: 0}`,
`category_counts` = `{reference.unresolved_subckt_call: 17, topology: 4}`.

The curated `sg13g2` extraction deck recognises **no device at all** in this
stream (`extract.json`: `device_count: 0`, `device_counts: {}`), and
`extract.json`'s own warning names why: all 17 HBT regions "match every other
drawn-layer predicate" of the `dantenna` class but lack its
`Recog.diode (99/31)` marker, "so this geometry extracted as no device at all".
That is gap **G1**, which `layout/probe-readiness/README.md` records as
**declined upstream by ruling** for the curated deck
(klayout-tools#1232 / #2864 / #3137-via-#3431 / #2849 `not_planned`) — so no
new upstream issue is filed for it here either. The 17
`reference.unresolved_subckt_call` errors are one per `npn13G2` call in
`reference-devices.spice`, the same diagnosis the probe recorded.

`power_connectivity.status` is `"unchecked"`, with the report's own reason: the
reference form is `subckt-call`, whose netlist carries its own power/ground
pins, so the check that exists for signal-only `gate-level-verilog` references
does not apply. Per T1 item 4's text, `"unchecked"` means the question was never
asked — never "verified".

Item 4 is out of scope for issue #198 (it is #260's, which bumps the klt pin to
0.9.0 for the runset-backed route). This record does not advance or refute
#260: it measures what the **curated deck at the current pin** does with the
real device set, which is what the probe measured with one HBT, now confirmed
with seventeen.

## Gaps found

**Already filed upstream, not re-filed.** `klt ring-check`'s JSON record
carries no `provenance` block at all — confirmed again here: none of
`ringcheck_activ.json` / `ringcheck_psd.json` / `ringcheck_m1.json` has one, so
those three records cannot be attributed to a tool build from the record alone.
That is gap G5, 2AMLogic/klayout-tools#5650.

**G6 — declined upstream by ruling; recorded here, not re-filed.** `klt erc`'s
two tie-degeneracy tests are jointly unsatisfiable for a native-substrate block
whose guard ring defines the top cell's extent. A tie with `well_layer: null`
is well-degenerate unless its `well_boxes` leave >1 % of the top-cell extent
uncovered, and tap-degenerate unless its narrowing removes some drawn
`tap_layer` geometry *inside* that well region. When the guard ring **is** the
outermost geometry, any region containing every tap covers ~99.8 % of the
extent, so the first test forces the asserted substrate region to be clipped —
and the clip must still contain non-tap diffusion for the second test to pass.
That is why the claim recorded above is shaped by the constraint rather than by
the layout: `extent_uncovered_fraction` is 0.1416 because the northern strip
was excluded to clear the threshold, not because that strip's substrate is
unclaimed for any physical reason.

This is the gap klayout-tools#4285 ("erc: no falsifiable way to check the
substrate tie on a bulk-substrate standard-cell layout") already describes,
including the "shrinking the box to avoid the degenerate test would make the
claim unfalsifiable in a different way" half — and it was **closed
`not_planned`**. klayout-tools#2427 ("a `ties[].well_boxes` assertion is never
re-checked against the device-bearing area it claims to cover") is closed
`completed` and is the other side of the same trade. So no new upstream issue
was filed: it would duplicate a closed, ruled decision, which is noise on the
tool tracker rather than friction-protocol signal — the same call
`layout/probe-readiness/README.md` made for G1. A later reader should not wait
on it; a native-substrate tie claim in this repo will keep resting on a clipped
caller assertion, and should keep disclosing the clip.

**G7 — new, filed generically**
([2AMLogic/klayout-tools#5733](https://github.com/2AMLogic/klayout-tools/issues/5733)):
`klt lvs` is the only layout verb whose curated deck cannot be named with
`--deck`, and the prefix-matched attempt fails as an argparse *usage* error
(exit 2, `ambiguous option: --deck could match --deck-file, --deck-var`) with
**empty stdout**, rather than the clean exit-1 error envelope the JSON contract
promises. `klt drc`, `klt extract` and `klt erc` all take `--deck <name>` in
the same install. The empty-stdout half is what breaks an evidence-recording
chain: a step written as `cmd > record.json` leaves an invalid-JSON file and
the lint fails on the symptom rather than the cause — which is exactly how it
surfaced while building `run_checks.sh`.

## Reproducing

The host `klt` is never used for these records. From the repository root:

```sh
# 1. a throwaway environment at this repo's declared pin (never the host tool)
uv venv /tmp/klt-pin
uv pip install --python /tmp/klt-pin/bin/python "klayout-tools==0.8.0"

# 2. check the pin, the PDK and the primitive cells are all present
python3 layout/toolchain_pin.py --check --klt /tmp/klt-pin/bin/klt --extra erc

# 3. the element realizability analysis (needs the installed PDK only)
/tmp/klt-pin/bin/python layout/lna_stage1/realizability.py --check

# 4. the layout, byte-identically
/tmp/klt-pin/bin/python layout/lna_stage1/generate.py --out /tmp/regen.gds \
    --reference /tmp/regen.spice
sha256sum /tmp/regen.gds layout/lna_stage1/lna_stage1_devices.gds

# 5. the whole check chain, rewriting runs/klt-0.8.0/
layout/lna_stage1/run_checks.sh --klt /tmp/klt-pin/bin/klt
```

Every run here is a single layout and a single corner, so all of it stays
**local** — it is not a `klt sim` grid and must not be expressed as one.
`generate.py` fails loudly, naming the missing piece, when the pinned PDK is
absent, when a primitive cell is missing from it, or when a labelled net lands
on more than one disconnected conductor (that last check is not decoration: it
caught a 1 µm gap in the cascode strap during this study's development, which
DRC passed and `klt extract` reported only as a `split_net_labels` warning).

## Files

| File | What it is |
|---|---|
| `realizability.py` / `realizability.json` | Per-element PDK-primitive resolution and the geometry each value would need. The derivation behind "items 2 and 3 are not claimed". |
| `generate.py` | Deterministic generator for the drawable subset. Also emits `reference-devices.spice`. |
| `lna_stage1_devices.gds` | The committed stream. Non-claiming. |
| `reference-devices.spice` | **Derived** — the SPICE reference holding exactly the devices the stream draws. Regenerate with `generate.py`. |
| `erc-supply-spec.json` | The `klt erc` supply spec (`vdd`/`gnd`, stackup, `ties[]`). |
| `run_checks.sh` | Runs the whole chain into `runs/<klt version>/` and records every exit code. |
| `runs/klt-0.8.0/` | The records, at this repo's declared pin. Append-only. |
