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
T1: 2/11 items met
```

**Items 1 (Design sources) and 10 (Repo hygiene) are `met`; items 2-9 and 11 are
`unmet` with `reason: "no_evidence"`.** Item 1 cites `evidence/item1-design-sources.json`, an
artifact-anchored `generic` attestation (issue #28): it declares `t1_item: 1`,
binds the derived netlist `design/netlist/lna_stage1.spice` by path and content
hash, lists the xschem sources (`design/lna_stage1.sch`, `.sym`) with their
hashes in `metrics`, and is `pass` only if `design/export_netlist.sh --check`
says the committed netlist is what those sources export now. Regenerate it
with `python3 signoff/make_item1_evidence.py` (it prints the manifest entry to
paste, including the pinned `content_hash`) whenever the schematic or netlist
changes; a stale pin renders `stale_evidence`, never a false pass. The graded
`met` is "the item is bound to an audited artifact", not a judgment that the
design is any good. Item 10 cites `evidence/item10-repo-hygiene.json` (issue #71), a `generic`
attestation that is `pass` only if `README.md`, `LICENSE` and
`spec/target-spec.md` exist, the README's Reproduce section links
`sim/README.md` and names `sim/characterize.sh`, and the non-comment lines of
`.github/workflows/ci.yml` invoke `check_evidence_formats.py` and
`sim/characterize.sh smoke`. It binds the CI workflow by content hash;
regenerate with `python3 signoff/make_item10_evidence.py` (exits non-zero if
any check fails, e.g. LICENSE removed). These are presence/invocation checks,
not a quality judgment. **Item 9 (Testbenches shipped) is still deliberately not
attested.** Issue #85 removed the first blocker: every `sim/<bench>/` holding
`records/` now has a cold-start README (`.github/scripts/check_evidence_formats.py`
fails CI if one is missing or has no invocation section with a fenced command
block; negative controls in `.github/scripts/tests/test_check_evidence_formats.py`).
The second blocker remains: the newest `sim/lna-sparam-nf` record
(`20261010-012923-6cad7fc.md`) was written after the model artifact was pinned
(`sim/pdk-artifact.json`) yet still names the PDK `unknown`, because the
harness's `Pdk.version` reads a `SOURCES` file that IHP-Open-PDK does not ship
(`.fetched-version` instead). Records are append-only, so it cannot be edited;
the checker grandfathers exactly four legacy records by id
(`LEGACY_UNKNOWN_PDK`) and rejects any other record naming the PDK `unknown`.
Item 9 can honestly be attested once a later record of each harness-native
bench carries a pinned PDK revision (fix `Pdk.version` to read `.fetched-version`
or have `report.py` print the `pdk-artifact.json` commit, then re-run the bench),
at which point a `make_item9_evidence.py` in the item-10 pattern can bind the
README set and that record. Until then no envelope exists and the report stays
`unmet`/`no_evidence`. The remainder is the correct, honest result for a block
whose layout and verification evidence has not started. The per-item *human*
context stays in the gap-to-T1 tracker
([#4](https://github.com/2AMLogic/sg13g2-sat-rx/issues/4)); this report carries
the machine verdict.

`klt signoff` exit codes for `--manifest` mode: `0` = every rendered T1 item
met (tier T1), `3` = report rendered successfully with at least one unmet
item (this block's expected exit today), `1`/`2` = the manifest, a cited
evidence file, or the tiers doc could not be read/parsed. Exit `3` is a
rendered, usable report — not an error.

**Grader pin: `klayout-tools==0.7.0`** (`.github/workflows/signoff.yml`),
raised from 0.5.0 in the same change that cited item 1: klt 0.5.0 has no
artifact-anchored generic evidence and renders such a citation
`unmet`/`wrong_kind`, so the pin had to move for the item-1 citation to grade.
Regenerate the report with the pinned release, not a dev build (a dev build
writes its commit into the report's `build` block and would not compare equal
to CI's re-grade). A throwaway venv does it without touching host tools:
`uv venv /tmp/klt070 && uv pip install --python /tmp/klt070/bin/python
klayout-tools==0.7.0 && /tmp/klt070/bin/klt signoff ...` (checked: `uvx --from
klayout-tools==0.7.0` resolved to the host's already-installed dev build, whose
`build` block differs).

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

T1 grew an **eleventh item** ("Power delivery (structural)",
[klayout-tools#2025](https://github.com/2AMLogic/klayout-tools/issues/2025))
on 2026-09-19 — after the released `klt` 0.5.0, which bundles the ten-item
checklist. `--tiers-doc` is the supported override: pinning the checklist
here makes the rendered item set deterministic regardless of the installed
`klt` release, and keeps item 11 in the report as the issue requires.

`klt` 0.5.0 parses this 11-item doc correctly but has **no grading rules for
item 11** — an *uncited* item 11 renders honestly as
`unmet`/`no_evidence` either way. When evidence for item 11 eventually
exists (a `klt erc` supply-spec run plus an LVS report whose reference
carried the supply nets), upgrade the `klt` pin in
`.github/workflows/signoff.yml` to a release that grades item 11, regenerate
the report, and update the pinned checklist in the same change.

Provenance of the pinned copy:

- Source: `2AMLogic/klayout-tools` — `docs/design-evidence-tiers.md`
- Commit: `b15edf5e3a2e56467a3406c98a2555eb1a5ae45c` (2026-09-21)
- SHA-256: `c7a1e7e10627fae396007e0ff951734f37d95028b8f49f2e21e802e9f552f318`
- License: MIT (klayout-tools); copied verbatim, unmodified.

Re-pin deliberately: update the doc, the commit/SHA lines, and the tier
report together, so the verdict of record always states which checklist
graded it (`source_doc` in the report names this path).

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
