# Guard classification of inert source text vs executed cleanup (issue #140)

Status: investigation report. No guard, role prompt or scope configuration was
changed. Observed results are recorded separately from desired outcomes.

## Verdict

- Telemetry hypothesis (quoted Python heredoc containing
  `rm -f "${PREFIX}/logs/${name}.done"` as source text caused
  `rm-scope-unresolved-var`): **NOT REPRODUCED** with the minimal fixture, on
  the active guard (the vendored fallback; see Identity). Fixture 1 is allowed
  with no finding. The original telemetry command was not available to this
  run, so the hypothesis is **not disproved for the original command**; only
  the minimal inert-source shape is shown to be handled correctly.
- Executed unresolved cleanup (fixture 2) fails closed as desired.
- Fixtures 3 and 4 as written do **not** exercise the outside-repo scope
  restriction: `/tmp/*` is on the guard's built-in ephemeral allowlist, so the
  result is an allow by design. Per the issue contract an allow here is not
  evidence of anything about scope enforcement; the desired outcome for 3/4 is
  therefore **inconclusive** for the stated path. Supplemental controls using
  a non-temp outside path (below) show the restriction is enforced, including
  in the mixed case.
- No guard defect is demonstrated. No upstream handoff is justified (see
  Ownership).

## Identity and configuration (recorded 2026-10-11)

- Repo HEAD at test time: `3dcd0838a318993f1b2c198769e67b86311a4a91`
  (issue verified against `origin/main` `3a92771`).
- Loom install: `.loom/install-metadata.json` `loom_version` 0.19.1062,
  `loom_commit` c555a3d547a07f49d11fefc5b1456b6e28933d7e.
- Dispatcher `.loom/hooks/guard-destructive.sh`
  SHA-256 `3d9eed6e01de13bcfdb1f473f2c3363ac8debce73c7cbb8afcca9d8a8091e26c`.
- The dispatcher prefers `$CANONICAL_ROOT/.claude/skills/repo/hooks/guard-destructive.sh`
  (Repo Skills) only if it passes four capability probes. That path **does not
  exist** in this repo (`.claude/skills` absent), so the dispatcher `exec`s the
  vendored fallback `.loom/hooks/guard-destructive-generic.sh`, SHA-256
  `64d4f0956cb15e03d7b9fcb582d0081dac9a218bb1d237c9844e37048fe88acb`.
  **Active target = vendored fallback.** The canonical Repo Skills guard was
  not installed, so it was not tested; results say nothing about it.
- Scope config: `.loom/config.json` has no `guards` key, so
  `guards.rmScope` resolves to its default `repo`. The scratch repo used for
  testing also had no `guards` key (`{"version":"2"}`), and `LOOM_RM_SCOPE`
  was unset (`env -u`). Effective mode: `repo`.
- Tools: bash 5.2.21, jq 1.7, python3 (run with `-I`).

## Invocation recipe

Disposable environment under `$TMPDIR` (here `/tmp/tmp.QK6m6acHf5`): a fresh
`git init` repo with only `.loom/config.json`, plus a driver directory.
Fixtures are written with quoted heredocs (`<<'EOF'`) so nothing expands, then
wrapped by `python3 -I` as JSON `tool_input.command` with `cwd` set to the
scratch repo, and piped to the dispatcher on stdin. The payload text is never
passed to a shell for execution.

```sh
S=$(mktemp -d); mkdir -p "$S/repo" "$S/drv"
git -C "$S/repo" init -q; mkdir "$S/repo/.loom"
echo '{"version":"2"}' > "$S/repo/.loom/config.json"
# f1.txt..f4.txt written via quoted heredocs (contents below); f4 = f1 + f3
python3 -I -c 'import json,sys;print(json.dumps({"tool_name":"Bash","cwd":sys.argv[2],
  "tool_input":{"command":open(sys.argv[1]).read().rstrip("\n")}}))' f1.txt "$S/repo" > f1.json
env -u LOOM_RM_SCOPE bash <worktree>/.loom/hooks/guard-destructive.sh < f1.json
```

Byte-for-byte check: decoding `tool_input.command` from `f1.txt.json` and
`cmp`-ing with `f1.txt` matched (`bytes-ok`), so `${PREFIX}`/`${name}`
survived construction. After the runs, neither
`/tmp/guard-fixture-outside-repo.done` nor
`/home/ubuntu/guard-fixture-outside-repo.done` existed and no file was
modified (the payloads were never executed).

## Fixtures (inert text; do not run)

Fixture 1, inert source only:

```sh
python3 - <<'PY'
replacement = 'rm -f "${PREFIX}/logs/${name}.done"'
PY
```

Fixture 2, executed unresolved cleanup:

```sh
rm -f "${PREFIX}/logs/${name}.done"
```

Fixture 3, executed literal cleanup:

```sh
rm -f /tmp/guard-fixture-outside-repo.done
```

Fixture 4, mixed: fixture 1 followed by fixture 3.

Supplemental controls (not in the issue; added because fixture 3's path is
allowlisted):

- S1: `rm -f /home/ubuntu/guard-fixture-outside-repo.done`
- S2: fixture 1 followed by S1
- S3: fixture 1 followed by fixture 2
- S4: `python3 -c 'x = "rm -f \"${PREFIX}/logs/${name}.done\""'`

## Observed results (2026-10-11, rmScope=repo, vendored guard)

All runs: exit status 0, stderr empty, stdout valid JSON where non-empty
(validated with python `json.load`). Empty stdout = no decision emitted
(allow).

| Case | Decision | Reason / trigger |
|------|----------|------------------|
| F1 inert source | allow (empty stdout) | none |
| F2 executed unresolved | deny | `rm-scope-unresolved-var`: "rm target '"${PREFIX}/logs/${name}.done"' is an unexpanded shell variable from the path root down ... Unresolvable rm targets fail closed" |
| F3 literal `/tmp/...` | allow (empty stdout) | none (`/tmp/*` built-in ephemeral allowlist) |
| F4 mixed (F1 + F3) | allow (empty stdout) | none (same allowlist) |
| S1 literal non-temp outside | deny | `rm-scope-outside-repo`: "rm target outside repo scope (LOOM_RM_SCOPE=repo): /home/ubuntu/guard-fixture-outside-repo.done" |
| S2 F1 + S1 | deny | `rm-scope-outside-repo` for the S1 target; no unresolved-var finding from the inert string |
| S3 F1 + F2 | deny | `rm-scope-unresolved-var` (from the executed F2 line) |
| S4 inline `python -c` string | allow (empty stdout) | none |

## Desired vs observed

| Case | Desired | Observed | Assessment |
|------|---------|----------|------------|
| F1 | no cleanup-target finding from the Python string | allow | meets desired |
| F2 | denied / fail-closed | deny, unresolved-var | meets desired |
| F3 | scope restriction remains enforced | allow via `/tmp` allowlist | inconclusive for this path (allowlist, by design); S1 shows enforcement for a non-temp outside path |
| F4 | outside cleanup still scope-restricted | allow via `/tmp` allowlist | inconclusive for this path; S2 shows enforcement |

Do not read the F3/F4 allows as approval of out-of-repository deletion in
general: the guard allows only temp roots and session-owned scratch; other
outside paths are denied (S1/S2). Finding order is not asserted anywhere.

## Interpretation

1. On the vendored guard in rmScope=repo, an `rm` string inside a quoted
   Python heredoc or a `python3 -c` literal is not classified as an executed
   cleanup target (F1, S2, S4). The telemetry account is not reproduced by the
   minimal shape.
2. The original telemetry command contained "actual forced cleanup of literal
   temporary paths outside the repository". Plausible untested explanations
   for its `rm-scope-unresolved-var` finding: another executed `rm` in the
   same command with a variable target (S3 shows that does fire), a different
   guard build on the telemetry host, or a heredoc/quoting shape differing from
   the minimal fixture. These are hypotheses only; the original command text
   should be obtained from the telemetry record and replayed as a further
   fixture before concluding anything about it.
3. Not exercised: the canonical Repo Skills guard (not installed here), other
   `guards.rmScope` values (`off`), and a non-default `scratchRoot`.

## Recommended practice (no guard change)

Keep source edits and cleanup in separate commands: do the file edit in one
command, and issue `rm` with explicit literal paths (in-repo, a temp root, or a
session-owned scratch directory) in another. Unresolved executed targets must
keep failing closed.

## Ownership and upstream handoff

No defect is demonstrated, so no upstream issue body is proposed and none was
filed. If a future replay of the original telemetry command reproduces a
false finding:

- generic parsing of inert source text or `rm` target resolution: Repo Skills,
  `rjwalters/repo`, `hooks/repo/guard-destructive.sh` (this repo's vendored
  `guard-destructive-generic.sh` must not be hand-edited);
- canonical-vs-vendored selection or probe logic: Loom dispatcher,
  `rjwalters/loom`.

Any such report must include the exact replayed command, the active guard
SHA-256, and the rmScope configuration, as recorded above.
