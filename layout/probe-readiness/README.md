# layout/probe-readiness — klt layout-chain readiness probe (issue #185)

**This is NOT the LNA layout and cites nothing.** It is a tiny, throw-away-quality,
**non-claiming** probe cell run through the klt layout chain once to learn — before
the core is chosen (#79) — what actually works. No T1 item 2/3/4/11 citation is
added to `signoff/block-manifest.json` from this probe, and neither
`signoff/block-manifest.json` nor `signoff/tier-report.json` changed. Recorded
results are append-only evidence: later runs supersede these by adding a record,
never by editing one.

## Re-run at the pinned release klt `0.8.0` (2026-11-14, issue #246) — supersedes the tables below

This is the first record taken at the klt pin this repo actually declares
(`layout/toolchain.json` → `klt_install: "klayout-tools==0.8.0"`); the two
earlier records were taken at `0.7.0+gb770c86e0e96` (#185) and the development
build `0.7.1.dev1744+g44cc42323184` (#197), and both are kept unedited as
evidence. The re-run lives in `runs/klt-0.8.0/` (19 files, the same set as the
0.7.1 directory; `exit-codes.txt` lists all eleven exit codes).

**The two questions this record exists to answer:**

- **Does `npn13G2` extract as a device at the pinned release? No.**
  `runs/klt-0.8.0/extract.json` reports `device_count: 2` and
  `device_counts: {"cap_cmim": 1, "rsil": 1}`; the devices list is exactly
  `$1 cap_cmim {a: CB, b: CT}` and `$2 rsil {a: RB, b: RA, w: GND}`. There is
  no bipolar device, and `unsupported_devices` is `[]`. The only signal is
  still the `dantenna` near-miss warning (`warnings[0]`), which at 0.8.0 ends
  with a new sentence naming the family verbatim:
  *"Note: this geometry also matches SiGe HBT (npn13G2/npn13G2l/npn13G2v), a
  device family this deck does not model, so it is probably not a diode at
  all -- see the sg13g2.py docstring section 'SiGe HBTs -- investigated,
  declined (issue #1232)'."*
- **Does `lvs-simform-full` (the 3-terminal `rsil` reference including the HBT)
  report `match`? No — `mismatch`, exit 3.**
  `runs/klt-0.8.0/lvs-simform-full.json`: `status: "mismatch"`,
  `mismatch_count: 9`, `error_count: 3`, `counts.devices` =
  `{layout: 2, reference: 2, matched: 0}`, with the same
  `reference.unresolved_subckt_call` error for `NPN13G2` and two `topology`
  errors the 0.7.1 run recorded.

| Item | Value |
|---|---|
| klt | `0.8.0` — the release pin `klayout-tools==0.8.0`, i.e. klayout-tools tag `v0.8.0` = commit `c572046be644e0407f693f2410f3abb799d68a3a` (the `klt_last_verified_commit` in `layout/toolchain.json`). Run from a throwaway `uv` venv; the **host** tool (`klt 0.9.2.dev1022+g2a9c52b27ce7`) was not used and not modified. |
| deck | `sg13g2`, content hash `sha256:1c95db40596afc5412e216009bcf0b775d1d74895b32738447eccbc76336dd15`, **`released: true`** (was `sha256:08dbffe2…ec01c`, `released: false`, at the 0.7.1 dev build) |
| klayout (bundled) | 0.30.13 (was 0.30.12). klt 0.8.0 declares it was tested against `klayout==0.30.12`, so `drc.json` and the six `lvs-*.json` carry `provenance.klayout_version_mismatch: true` and each run printed the engine-version disclosure warning added by klayout-tools#1490 (`extract.json` and `economy.json` omit that field). Per that warning the **verdict** is unaffected; derived counts may differ. `klayout_package_min` stays `"0.30"` — no floor change. |
| record `schema_version` | `drc` 2 → **3**, `extract` 3 → **4**, `lvs-*` 1 → **2**; `economy` and `ring-check` unchanged at **1**. At `extract` schema 4 the `file` field is an anchored object (`{"path": "layout/probe-readiness/probe.gds", "scope": "repo"}`) rather than the bare string it was at schema 3; `split_net_labels` is new (empty here). Nothing in this repo parses these records, so the bump is a record-keeping note, not a breakage. |
| `probe.gds` | regenerated with `generate_probe.py` under that install (`.venv/bin/python generate_probe.py --out <tmp>`): **byte-identical** to the committed file, sha256 `9759f9ee…db0b` — matching `provenance.input.content_hash` in every record of both earlier runs. No change committed. |
| PDK | ihp-sg13g2 v0.3.0 @ `5cccb161f7492697cfa52eb14dc03beb00bdca9e` (the `sim/pdk-artifact.json` pin), primitives from `libs.ref/sg13g2_pr/gds/sg13g2_pr.gds`, install marker `.fetched-version` = `0.3.0`. **The GDS primitives are not hash-pinned**: `sim/pdk-artifact.json`'s `files` closure covers the ngspice HBT model set only, so the citation here is the pinned commit plus the install marker, not a hash closure. |
| host-path hygiene | `klt env-provenance lint-envelope runs/klt-0.8.0/*.json` → `clean: 0 absolute path(s) in 17 file(s)`. |

| Command | Status at the pinned release | Evidence (`runs/klt-0.8.0/`) |
|---|---|---|
| `klt drc --deck sg13g2` | **works** — `clean`, 0 violations, exit 0, as at 0.7.1. The deck grew: 24 rules checked (was 21) and 38 inapplicable (was 24). The three new checked rules are `psd.area.1`, `psd.space.1`, `psd.width.1`, and `deck_scope` gains `NW` and `pSD` — so the guard ring's pSD layer `14/0` drops out of `layers_in_stream_without_rules` (19 → 18 entries) and is now actually checked, clean. | `drc.json`. **G3 still fixed** (`cont.width.1` is in `coverage.checked` with 0 violations). |
| `klt extract --deck sg13g2` | **works** for `cap_cmim` and `rsil`; **blocked** for `npn13G2`, unchanged. The extracted netlist is byte-identical to the 0.7.1 run (`netlist_sha256` `859630d8…eabe7`, `netlist_normalized_sha256` `462a0909…b022` in both). | `extract.json`, `probe_extracted.spice`. **G1 unchanged — and now declined by ruling, see below.** |
| `klt lvs` | **works** on the recognised subset; **blocked** for a reference containing the HBT. All six runs were repeated and **every verdict-bearing field is identical to the 0.7.1 run** (`status`, `counts`, `mismatch_count`, `error_count`, `category_counts`, `category_error_counts`): `lvs-simform-recognized-cap-rsil3` `match`, exit 0, 8/8 nets, 2/2 devices; the other five `mismatch`, exit 3. | `lvs-simform-recognized-cap-rsil3.json`, `lvs-simform-full.json`, and the four others + their `*.request.json` (copied unchanged from the 0.7.1 run — the layout path is relative to the request's own directory). **G4** still gives the named `reference.unresolved_subckt_call` diagnosis for `NPN13G2`, still caused by G1. |
| `klt ring-check` | **works** — both `continuous`, exit 0, `violation_count: 0`. But **the record carries no `provenance` block at all** (`schema_version: 1`, no `provenance` key) and its `file` field is the bare input string, unlike `drc`/`extract`/`lvs`/`economy` in the same install. So these two records cannot be attributed to a tool build from the record alone — the one thing this run could not satisfy in issue #246's own acceptance criterion "each carrying `provenance.klt_version`". **New gap G5, filed upstream: 2AMLogic/klayout-tools#5650.** | `ringcheck_activ.json`, `ringcheck_m1.json`. |
| `klt economy` | **works** — utilisation 20.95 %, bbox 43.78 × 32.08 µm, byte-identical geometry metrics to the 0.7.1 run. | `economy.json`. |

Exit codes are directly comparable to the 0.7.1 run and are **identical**:
`drc 0`, `extract 0`, `ringcheck_activ 0`, `ringcheck_m1 0`, `economy 0`, then
`lvs-simform-full 3`, `lvs-simform-recognized-only 3`, `lvs-full 3`,
`lvs-recognized-only 3`, `lvs-simform-recognized-cap-rsil 3`,
`lvs-simform-recognized-cap-rsil3 0`. Each exit code agrees with its own
record's `status` field (`clean` / `extracted` / `continuous` / `match` → 0;
`mismatch` → 3).

**Provenance coverage of this run, stated plainly: 9 of the 11 records carry
`provenance.klt_version` = `0.8.0`** (`drc`, `extract`, `economy` and the six
`lvs-*`). The two `ring-check` records carry **no `provenance` block at all** —
that is a tool limitation, not an omission in this run, and it is the one part
of issue #246's acceptance criterion 2 this run cannot satisfy. See G5 below.

### Gap status at 0.8.0 — G1 is **declined by ruling**, not "open pending a fix"

The 0.7.1 section below says "G1 open (klayout-tools#3137 still open)". That
line is **superseded**: #3137 has closed, but *not* by adding bipolar
recognition. Verified 2026-11-14 against the upstream tracker and the installed
0.8.0 distribution:

- **klayout-tools#3137 was closed by PR #3431, a warning-text change only** —
  "feat(extract): name unmodelled device family in diode near-miss warning".
  Its own acceptance-criteria verification records that `device_count` is still
  0 and that native HBT recognition stays out of scope. PR #3431 is an ancestor
  of the `v0.8.0` tag, which is why the near-miss warning quoted above now names
  the SiGe HBT family — that sentence *is* the whole of #3137's fix, and this
  run's `extract.json` is the local confirmation that the device count did not
  move with it.
- **The 0.8.0 `sg13g2` extraction deck says so itself.** In the installed
  `klayout_tools/decks/sg13g2.py` there is no `bipolars=` field anywhere; the
  docstring carries a section "SiGe HBTs -- investigated, declined (issue
  #1232)" (line 365), and line 2795 declares
  `unmodelled_families=(UnmodelledDeviceFamily(name="SiGe HBT (npn13G2/npn13G2l/npn13G2v)", …))`.
- **Both upstream *routes* to a curated-deck HBT are closed by ruling**:
  klayout-tools#1232 (investigated, declined), #2864 (closed 2026-10-16 as a
  docs correction to that operator ruling), #3137 (closed by PR #3431, warning
  text only) and #2849 — the PDK-own-runset device-aware LVS path — closed
  2026-10-17 as `not_planned` with no PR.

So **no new upstream issue was filed for G1**: it would duplicate a closed,
operator-ruled decision, which is noise on the tool tracker rather than
friction-protocol signal. The ruling is recorded here instead, which is what a
reader of this directory needs.

**One upstream item on the HBT question is still open**, recorded here because
it bears on what a later reader can expect: klayout-tools#4397 ("Live-verify
SG13G2 runset recognises `npn13G2`") is open and parked, and would record
whether the **PDK's own** runset — `klt lvs --engine klayout-runset` against
`ihp-sg13g2/libs.tech/klayout/tech/lvs/sg13g2.lvs`, a different path from the
curated deck this probe exercises — recognises the device. Its park reason is a
host-capability gap: it needs a standalone KLayout ≥ 0.29 and its worker had
0.28.16. Observation, not a claim about this probe: on *this* repo's dispatch
worker today `/usr/bin/klayout` reports 0.30.12, so that premise does not hold
here. Running that experiment is upstream's, and out of scope for this record.

**Summary of gap status at 0.8.0.** **G1 declined by ruling** (#1232 / #2864 /
#3137-via-#3431 / #2849 `not_planned`); the curated-deck route to an LVS-clean
bipolar flow in this repo is closed, and a later reader should not wait on it.
**G2 fixed** for `rsil` (`rppd`/`rhigh` are still not in the probe and still
untested). **G3 fixed**, and the deck now additionally checks the pSD layer this
probe draws. **G4** still a named diagnosis caused by G1. **G5 new** — no
`provenance` block on `klt ring-check` records
(2AMLogic/klayout-tools#5650, filed generically per the friction protocol). No
other new gap: every other verdict-bearing field in this run reproduces the
0.7.1 record exactly.

This is still a **non-claiming** probe. `signoff/block-manifest.json` and
`signoff/tier-report.json` are byte-unchanged, no T1 item is cited from it, and
nothing under `runs/klt-0.7.1.dev1744+g44cc42323184/` or `runs/*.json` was
edited — those earlier records are superseded by this addition, never by a
rewrite.

## Re-run at klt `0.7.1.dev1744+g44cc42323184` (issue #197) — supersedes the v0.7.0 table below

The v0.7.0 records in `runs/*.json` are kept unedited as evidence. The re-run
lives in `runs/klt-0.7.1.dev1744+g44cc42323184/` (every record carries
`provenance.klt_version`; `exit-codes.txt` lists exit codes).

| Item | Value |
|---|---|
| klt | `0.7.1.dev1744+g44cc42323184` = klayout-tools commit `44cc42323184a2f3a440b89789bf174488a6b1e4` (main on 2026-10-17), run via a throwaway `uvx --from "git+https://github.com/2AMLogic/klayout-tools@44cc423…" klt …` (host tool untouched). **No tagged release contains the #3138/#3139 fixes** (latest tag `v0.7.0`, 2026-10-08, predates both; fixes merged in klayout-tools PRs #3330 and #3359). |
| deck | `sg13g2`, content hash `sha256:08dbffe2400474b268e2095c80dd8dbd4297ce71cca7a55ee373b4f9499ec01c` (unreleased; v0.7.0 was `bf483105…`) |
| `probe.gds` | regenerated with `generate_probe.py` under that install: **byte-identical** (sha256 `9759f9ee…db0b`), no change committed |

| Command | Status at the new version | Evidence (`runs/klt-0.7.1.dev1744+g44cc42323184/`) |
|---|---|---|
| `klt drc --deck sg13g2` | **works** — `clean`, 0 violations, exit 0 (was 4 × `cont.width.1`) | `drc.json`. **G3 confirmed fixed.** |
| `klt extract --deck sg13g2` | **works** for `cap_cmim` and `rsil`; **blocked** for `npn13G2` | `extract.json`, `probe_extracted.spice`: `cap_cmim` + `rsil` (24.86 Ω, 3-terminal incl. bulk `GND`). HBT still extracts as no device, with the same misleading `dantenna` warning. **G2 confirmed fixed for `rsil`** (`rppd`/`rhigh` not in the probe, not tested). **G1 still open.** |
| `klt lvs` | **works** on the recognised subset (cap + rsil); **blocked** for a reference containing the HBT | `lvs-simform-recognized-cap-rsil3.json`: `match`, exit 0, 8/8 nets, 2/2 devices. `lvs-simform-full.json`: `mismatch`, exit 3, now with a named `reference.unresolved_subckt_call` error for `NPN13G2` (**G4 diagnosis improved**; the root cause is still G1). |
| `klt ring-check` | **works** | `ringcheck_activ.json`, `ringcheck_m1.json`: both `continuous` (exit 0). |
| `klt economy` | **works** | `economy.json`. |

The four reference-based LVS runs of the original set were repeated as-is
(`lvs-simform-full`, `lvs-simform-recognized-only`, `lvs-full`,
`lvs-recognized-only`): all exit 3. `lvs-simform-recognized-only` (cap only)
now mismatches **by construction**, because `rsil` now extracts and is an extra
layout device. Two new references were added: `reference-simform-recognized-cap-rsil.spice`
(2-terminal `rsil`, copying the original reference's call shape) mismatches —
the `subckt-call` conversion maps it to a 2-terminal `RSIL` class that cannot
pair with the extracted 3-terminal `rsil` — and
`reference-simform-recognized-cap-rsil3.spice` (3-terminal `rsil 1 2 bn`, as
`resistors_mod.lib` defines it) **matches**. The original `reference-simform-full.spice`
therefore carried a 2-terminal `rsil` that was never going to pair; that was
hidden while `rsil` extracted as nothing.

Gap status: **G1 open** (klayout-tools#3137 still open). **G2 fixed** for
`rsil`. **G3 fixed.** **G4** now gives a named diagnosis, still caused by G1.
No new gap was found that is not already tracked; the 2- vs 3-terminal `rsil`
pairing is a reference-authoring issue, not a tool defect. This is still a
non-claiming probe: `signoff/block-manifest.json` and `signoff/tier-report.json`
are unchanged.

The sections below describe the **v0.7.0 run** and are retained as the
historical record; where they conflict with the table above, the table above
is current.

## What the probe cell is

`probe_readiness` (see `probe.gds`, generated by `generate_probe.py`):

- one `npn13G2` HBT — the PDK's own primitive cell, instanced from
  `sg13g2_pr.gds`
- one `cmim` MIM capacitor — PDK primitive cell, wired out on TopMetal1 (`CT`)
  and Metal5 (`CB`)
- one `rsil` poly resistor — PDK primitive cell, wired out on Metal1 (`RA`/`RB`)
- a ptap guard ring (190 abutting `ptap` instances + a Metal1 band, labelled
  `GND`), closed on Activ and on Metal1
- HBT pins wired out: emitter `E` / base `B` on Metal1, collector `C` on Metal2
- pin-name labels on the curated deck's label layers (Metal1/Metal2/Metal5
  `labels(n,25)` text, TopMetal1 `labels(126,25)`)

Everything except the guard ring's Metal1 band and the routing is PDK primitive
geometry; the routing obeys min width/space (2 µm TopMetal1, 2 µm Metal5,
0.6 µm Metal1/Metal2 runs).

## Environment (verbatim provenance in `runs/*.json`)

| Item | Value |
|---|---|
| klt | `0.7.0+gb770c86e0e96` (`klt version`; = response `provenance.klt_version` in every run record) |
| klayout (bundled) | 0.30.12 |
| deck | `sg13g2`, content hash `sha256:bf483105cb17948270f0cad45d9418787654bfc0a5ffd04a2e2413d8c7d3b6e7`, released v0.7.0 |
| PDK | ihp-sg13g2 v0.3.0 @ `5cccb161f7492697cfa52eb14dc03beb00bdca9e` (the `sim/pdk-artifact.json` pin), primitives from `libs.ref/sg13g2_pr/gds/sg13g2_pr.gds` |
| Host tool note | `klt --version`'s banner initially reported a different post-tag suffix than `klt version`; every committed run record carries the engine's own `provenance.klt_version`, which is the identity that matters |

## Per-tool outcome

| Command | Status | Evidence |
|---|---|---|
| `klt drc --deck sg13g2` | **works-with-workaround** | `runs/drc.json` (exit 3): 4 violations, all `cont.width.1`, all inside PDK primitive cells — see gap **G3**. Every hand-drawn shape (routing, ring band, labels) is clean; coverage block honestly lists 20 in-stream layers the deck has no rules for. |
| `klt extract --deck sg13g2` | **blocked** for `npn13G2`; **blocked** for `rsil`; **works** for `cap_cmim` | `runs/extract.json`, `probe_extracted.spice`: exactly one device, `X$1 CB CT cap_cmim` (7.440855e-14 F — the PDK's own 74.6 fF symbol value, independently computed from geometry). HBT and resistor produce **no device at all** — gaps **G1** and **G2**. |
| `klt lvs` | **works** on the recognised subset; **blocked** for a reference containing the HBT/resistor | `runs/lvs-simform-recognized-only.json`: `status: match`, exit 0 (PDK xschem simulation-form reference, `form: "subckt-call"`). `runs/lvs-simform-full.json`: `status: mismatch`, exit 3 — by construction, since two of the three reference devices extract as nothing. |
| `klt ring-check` | **works** | `runs/ringcheck_activ.json` (Activ `1/0`) and `runs/ringcheck_m1.json` (Metal1 `8/0`): both `status: continuous` with `--ignore-enclosed` (the HBT's Activ island sits inside the ring's hole). |
| `klt economy` | **works** | `runs/economy.json`: utilisation 20.95 %, bbox 43.78 × 32.08 µm, no checks enabled. |

## Gaps found (filed per the friction protocol; generic, no design content)

- **G1 — no bipolar recognition in the curated sg13g2 extract deck.**
  The PDK's own `npn13G2` primitive cell extracts as **no device**. The only
  signal is a warning claiming this geometry is a *dantenna candidate* missing
  its `Recog.diode` marker (`runs/extract.json` `warnings[0]`) — a misleading
  diagnosis for an HBT. The PDK's own KLayout LVS decks
  (`bjt_extraction.lvs`, `CustomBJTExtractor`) do extract this device.
  **Filed: 2AMLogic/klayout-tools#3137.**
- **G2 — poly-resistor recognition misses the PDK's own `rsil`/`rppd`/`rhigh`
  primitive cells.** The primitive cells draw the poly only as two head pads
  that *abut* (edge-touch, zero overlap) the `PolyRes` marker square; the deck's
  body derivation is a strict `poly ∩ marker` intersection, so the body region
  is empty and no device is registered — **silently** (no warning; the marker
  is a declared resistor marker, so the unmodelled-marker check does not fire
  either). The upstream IHP decks derive the core with `interacting`
  semantics, which recognises these cells. **Filed: 2AMLogic/klayout-tools#3138.**
- **G3 — `cont.width.1` flags contact rows drawn by the PDK's own primitive
  cells.** The fixed-size check runs on merged Cont regions: rows of abutting
  0.16 µm contacts inside the `npn13G2` base cell (merged 1.65 × 0.16 µm) and
  `rsil` (merged 0.36 × 0.16 µm) violate "fixed 0.16 × 0.16 µm square". Four
  violations on a layout built exclusively from PDK primitives plus clean hand
  routing. **Filed: 2AMLogic/klayout-tools#3139.**
- **G4 — `klt lvs` cannot express a reference containing an unrecognised
  device.** With the xschem-form reference (`XQ1 … npn13G2`), the
  `subckt-call` conversion passes the BJT call through and the run ends in
  un-mappable `topology` errors (`runs/lvs-simform-full.json`) rather than a
  named "this device class is not in the deck" diagnosis. A consequence of G1,
  recorded here because it shapes what an LVS-clean bipolar flow would need.
  Not filed separately; folded into G1's issue.

No other gap was found: label reading, pin promotion, ring annulus checking,
utilisation reporting, deck coverage reporting and the request/response
envelopes all behaved as documented.

## Reference netlists (`LVS` inputs, committed for reproduction)

| File | Form | Content | Verdict |
|---|---|---|---|
| `reference-simform-recognized-only.spice` | xschem sim form | `XC1 CB CT cap_cmim …` only | **match** (exit 0) |
| `reference-simform-full.spice` | xschem sim form | HBT + resistor + cap | mismatch (exit 3) — expected, G1/G2 |
| `reference-full.spice` | hand plain-element | HBT + resistor + cap with values | mismatch (exit 3) — expected, G1/G2 |
| `reference-recognized-only.spice` | hand plain-element | cap only | mismatch (exit 3) — the plain `C1 … cap_cmim <value>` card does **not** pair with the extracted `cap_cmim` device class (reference side reads as generic `CAP3`); use the sim-form + `subckt-call` route above |

## Reproducing

```sh
python3 generate_probe.py                     # regenerates probe.gds (klayout module required)
klt drc --deck sg13g2 probe.gds
klt extract --deck sg13g2 -o probe_extracted.spice probe.gds
klt lvs runs/lvs-simform-recognized-only.request.json
klt ring-check --layers '[[1,0]]' --ignore-enclosed probe.gds
klt economy --top probe_readiness probe.gds
```

## Non-obvious generator gotcha (for the next layout work in this repo)

`kdb.CellInstArray` has **no** micron-space `DTrans` overload: passing one
silently converts through integer DBU, so a `DVector(14.0, 0)` displacement
lands at 14 dbu = 14 nm. Every instance in a generated cell piles up at the
origin and — because device recognition still works on the co-located
geometry — the result can look like a plausible layout while every device is
stacked on top of every other. `generate_probe.py`'s `inst_at()` converts to
integer DBU `Trans` explicitly; keep doing that.

## What this probe does not establish

- Nothing about the LNA: no sizing, no matching, no core topology (#79 owns
  that), no T1 claim, no manifest citation.
- Nothing about layouts drawn any way other than "PDK primitive cells + min-rule
  hand routing"; in particular the `drc` clean-bill for hand-drawn geometry does
  not extend to rule groups the deck explicitly does not transcribe (its own
  coverage block names them).
- `klt lvs`'s match verdict covers the capacitor only, and KLayout's comparer
  does not compare capacitor geometry parameters (`A`/`P` are secondary); the
  disclosed per-run warnings in `runs/lvs-simform-recognized-only.json` are part
  of this record.
