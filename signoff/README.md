# signoff/ — machine-graded T1 state

This directory is this block's **verdict of record** for the klayout-tools
design-evidence ladder ("gap to T1" tracker:
[#4](https://github.com/2AMLogic/sg13g2-sat-rx/issues/4)). It replaces a
hand-maintained checkbox list with the one thing that cannot go silently
stale: a block manifest that `klt signoff --manifest` grades mechanically,
re-run by CI on every push (`.github/workflows/signoff.yml`).

## Files

| File | What it is |
|---|---|
| `block-manifest.json` | The **claim**. Block name, block kind, and — per T1 item — the evidence envelope that backs it. Graded by `klt signoff --manifest`. |
| `tier-report.json` | The **verdict of record**. `klt signoff --manifest`'s own JSON output, committed verbatim. Regenerated and re-compared by CI. |
| `design-evidence-tiers.md` | The **governing checklist**, pinned (see below). `klt signoff` parses the T1 item skeleton out of this file — the item list is the doc's, never hand-transcribed. |

## Reading the current verdict

```
block: sg13g2-sat-rx  kind: analog
tier: none
T1: 3/11 items met
```

**Items 1 (Design sources), 9 (Testbenches shipped) and 10 (Repo hygiene) are
`met`; items 2-8 and 11 are
`unmet` with `reason: "no_evidence"`.** Their envelopes are **tool-produced**
by `klt signoff --attest {1,9,10} --inventory <file>` (issue #237), as the
checklist requires, from the versioned inventories in `inventories/`. The
envelope's `status` is derived from the mechanical checks it lists in
`attestation.checks[]`, each with the content hash of the file it ran on:

| Item | Inventory | What is checked |
|---|---|---|
| 1 | `inventories/item1.json` | `design/lna_stage1.sch`, `.sym` and `export_netlist.sh` exist; the derived netlist exists and `design/export_netlist.sh --check` exits 0. **LNA first stage only**; the mixer has no committed design source (#170). The freshness command needs xschem and the PDK, so it is `local_only`: `--attest` runs it, CI's `--check` carries the committed outcome. |
| 9 | `inventories/item9.json` | Every `sim/<bench>/README.md` of a bench with `records/`, `sim/README.md`, `sim/characterize.sh` and `sim/pdk-artifact.json` exist; the cold-start command (`python3 -m pytest sim/lna-sparam-nf/tests -q`, simulator-free) exits 0; the PDK and tool versions are pinned. It does **not** attest that any spec row is met nor that any PVT grid was re-run. |
| 10 | `inventories/item10.json` | README, LICENSE, spec, `sim/README.md`, CI workflow and the evidence checker exist; `check_evidence_formats.py --skip-history` exits 0; `ci.yml` invokes the checker and `sim/characterize.sh smoke`; the README names `sim/characterize.sh`. |

The graded `met` is "bound to an audited artifact", not a judgment that the
design is any good. Regenerate after editing an inventory or any inventoried
file, with the pinned klt and the repo's test dependencies on `PATH` (item 9's
cold start imports numpy and pytest):

```
klt signoff --attest N --inventory signoff/inventories/itemN.json \
            -o signoff/evidence/<item N envelope>.json
```

then copy the envelope's `provenance.input.content_hash` (the inventory hash)
into `block-manifest.json` and re-render the report below. `signoff.yml` runs
`--attest N --check` for each, so an edited member (e.g. `design/lna_stage1.sch`
without a netlist re-export) is drift in CI. Klt 0.8.0's manifest grader
re-hashes only the inventory, not its members; the `--check` steps are what
fence the members. The old `make_item*_evidence.py` generators are removed.
The remainder is the correct, honest result for a block
whose layout and verification evidence has not started. The per-item *human*
context stays in the gap-to-T1 tracker
([#4](https://github.com/2AMLogic/sg13g2-sat-rx/issues/4)); this report carries
the machine verdict.

`klt signoff` exit codes for `--manifest` mode: `0` = every rendered T1 item
met (tier T1), `3` = report rendered successfully with at least one unmet
item (this block's expected exit today), `1`/`2` = the manifest, a cited
evidence file, or the tiers doc could not be read/parsed. Exit `3` is a
rendered, usable report — not an error.

**Grader pin: `klayout-tools==0.8.0`** (`.github/workflows/signoff.yml`),
raised from 0.7.0 (issue #234); history: 0.5.0 -> 0.7.0 was done in the same
change that cited item 1, because klt 0.5.0 has no artifact-anchored generic
evidence and renders such a citation `unmet`/`wrong_kind`. The attestation
inventories need 0.8.0 (`--attest`).
Regenerate the report with the pinned release, not a dev build (a dev build
writes its commit into the report's `build` block and would not compare equal
to CI's re-grade). A throwaway venv does it without touching host tools:
`uv venv /tmp/klt080 && uv pip install --python /tmp/klt080/bin/python
klayout-tools==0.8.0 && /tmp/klt080/bin/klt signoff ...` (checked at 0.7.0:
`uvx --from klayout-tools==0.7.0` resolved to the host's already-installed dev
build, whose `build` block differs).

## Regenerating the verdict of record

```
cd <repo root>
klt signoff --manifest signoff/block-manifest.json \
            --tiers-doc signoff/design-evidence-tiers.md \
            --format json > signoff/tier-report.json
```

`git diff` on `tier-report.json` then shows exactly which verdicts moved.
Commit a regenerated report **in the same change** that touches the
manifest, any cited evidence artifact, or the pinned tiers doc — CI re-runs
the grade and fails if the committed report does not match what the current
tree grades to (a stale-citation fence: a manifest citing an artifact that
has since changed renders `stale_evidence`, not a false pass, and the
comparison turns that into a red build rather than silent rot).

## Why the checklist is pinned in-repo

`--tiers-doc` pins the checklist so the rendered item set is deterministic
and the report states which checklist graded it. The pinned copy is the
checklist bundled in the klt wheel of the grader pin (11 items, including
item 11 "Power delivery (structural)",
[klayout-tools#2025](https://github.com/2AMLogic/klayout-tools/issues/2025)),
which klt 0.8.0 grades. An *uncited* item 11 renders honestly as
`unmet`/`no_evidence`. A report counts only against current inputs, and that
includes the checklist it was graded against, so `tier-report.json`'s
`source_doc_content_hash` must equal the SHA-256 below.

Provenance of the pinned copy:

- Source: `klayout-tools==0.8.0` wheel, `klayout_tools/data/design-evidence-tiers.md`
- SHA-256: `a26b90262320d0fbd32b3f549a02b6300832706041797a559d8bf6bdb62efdc7`
- License: MIT (klayout-tools); copied verbatim, unmodified.
- Previously: klayout-tools commit `b15edf5` (2026-09-21), SHA-256 `c7a1e7e1…f318`.

Re-pin deliberately with every grader pin bump: update the doc, this
provenance block, and the tier report together.

## Adding a citation (the discipline that keeps the verdict honest)

When a real artifact lands, add an `evidence` entry to
`block-manifest.json`:

```json
"evidence": {
  "3": {"file": "layout/drc.json", "content_hash": "sha256:<the envelope's provenance.input.content_hash>"}
}
```

- **Pin `content_hash` on every citation** — copy it from the cited
  envelope's own `provenance.input.content_hash` (for a `klt yield` report
  entry, the hash `klt signoff` computes over the named samples document).
  An unpinned citation cannot have its freshness verified at all; a pinned
  one that no longer matches renders `stale_evidence` — the report gets
  worse, never falsely better.
- **Cite only evidence that actually backs the item.** Items 1, 2, 9 and 10
  are graded on "some passing envelope was cited", not on topical
  relevance — the grader cannot check that what you cited is about the
  claim you made; this repo's honesty is enforced here, not there.
- **Kind restrictions are load-bearing**: item 3 accepts only a `klt drc`
  report, item 4 only `klt lvs`, item 6 only `klt yield`, item 7 only
  `klt pex` (analog), item 8 the only item that accepts a `generic`
  envelope. Anything else renders `wrong_kind`.
- **Disclose with the claim, not in place of it**: item 3's DRC coverage
  gaps (`coverage.*`) and item 7's device-body bias (`body_bias.*`) are
  reported by the grader but *claimant-enforced* — state them in the gap-to
  T1 tracker update that accompanies the citation, not just in the JSON.

Consult `klt signoff`'s own contract
([docs/cli/signoff.md](https://github.com/2AMLogic/klayout-tools/blob/main/docs/cli/signoff.md))
for the full manifest schema, per-item accepted kinds, and `reason` values.
