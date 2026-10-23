# manifests/

`manifests/artifacts/<bench>-<run-id>.manifest.json` names the evidence bytes of
a harness run that live in the fleet artifact store instead of git (issue #226).
Each entry has `sha256`, `size`, `kind` (`evidence`), `producer`, a logical
`artifact:<key>` `uri` that only the artifact broker resolves, and a `name`: the
`sim/<bench>/...` path the file would have had in git (per-point ngspice logs
under `corners/<run-id>/`, the frozen netlist and testbench manifest under
`netlist-snapshots/`).

Evidence bytes are private and manifests are public, so a manifest is safe to
commit. A manifest names no storage location, and nothing in this repo does:
the broker URL comes from the environment (`$KLT_ARTIFACT_BROKER`, set for agent
sessions on fleet workers; optionally `$KLT_ARTIFACT_REPO`), never from a file.

- Written by `python3 -m harness.cli run <bench>` (and `sim/lna-sparam-nf/run.py
  ingest`) through `sim/harness/evidence_store.py`: stage in the git-ignored
  `sim/.work/.stage/`, `klt artifact put`, commit only the manifest and
  `sim/<bench>/records/<run-id>.md` (its `## Stored evidence` table lists name,
  size and sha256 per object).
- **Fail closed**: no broker, a `klt` without `artifact put` or older than the
  `artifact:<key>` contract, or an unreachable broker exits 10 before anything is
  simulated; a failed put exits 10, writes no manifest or record and keeps the
  staged bytes. There is no flag that commits bytes instead.
- Check a manifest against the store from a fleet worker:
  `klt artifact verify manifests/artifacts/<bench>-<run-id>.manifest.json`.
- CI (`.github/scripts/check_evidence_formats.py`, module
  `evidence_checks/artifact_manifests.py`) validates the schema, accepts only
  `artifact:` URIs, refuses any text naming a bucket or account under this
  directory, fails if a stored object's bytes are also committed under `sim/`,
  and treats manifests as append-only. It never contacts the broker.

Evidence committed before this change stays where it is (manifest-forward only).

Known tool gap: `klt artifact` has no delete/prune verb, so unreferenced objects (such as
the synthetic test objects from #226) cannot be removed from the store;
tracked at `2AMLogic/klayout-tools#4101`.
