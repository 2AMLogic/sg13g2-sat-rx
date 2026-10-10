#!/usr/bin/env bash
# Negative controls for the openEMS known-answer smoke (issue #46).
#
#   negative_controls.sh            (run with the runner environment active)
#
# Each control sabotages exactly one thing and PASSES only if the smoke is REJECTED with
# the specific exit status below.  A control that "passes" the smoke is a failure here.
#
#   missing binding      OPENEMS_PYTHON without CSXCAD/openEMS          -> 14
#   missing executable   PATH without the openEMS executable            -> 10
#   solver failure       stub `openEMS` that exits 1                    -> 11
#   solver failure #2    solver input XML truncated                     -> 11
#   timeout              --timeout 1 (real run needs several seconds)   -> 124
#   memory limit         --rss-max-mb 20                                -> 125
#   wrong expectation    analytic values scaled by 1.02 (tol is 0.5 %)  -> 13
#
# After every control it checks that no solver process is left running and that the
# repository work tree is unchanged.  Needs the positive control to pass first
# (it is run as the baseline, exit 0).  Exits 0 only if every control was rejected correctly.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../../.." && pwd)"
SMOKE="${HERE}/smoke.sh"
OUT="$(mktemp -d "${TMPDIR:-/tmp}/p1-negctl.XXXXXX")"
trap 'rm -rf -- "${OUT:?}"' EXIT
STUB="${OUT}/stub-bin"; mkdir -p "${STUB}"
printf '#!/bin/sh\n[ "$1" = "--version" ] && { echo " | openEMS 64bit -- version STUB"; exit 0; }\necho "stub solver: deliberate failure" >&2\nexit 1\n' > "${STUB}/openEMS"
chmod +x "${STUB}/openEMS"
BARE_PATH="/usr/bin:/bin"          # no prefix bin dirs -> no openEMS
before="$(git -C "${REPO_ROOT}" status --porcelain --untracked-files=all)"
fails=0; n=0
run() {  # run <name> <expected rc> <env assignments or -> -- smoke args...
  local name="$1" want="$2"; shift 2
  local envs=(); while [[ "$1" != "--" ]]; do envs+=("$1"); shift; done; shift
  n=$((n+1))
  local d="${OUT}/c${n}"; local rc=0
  env "${envs[@]}" "${SMOKE}" --log-dir "${d}" --work-dir "${d}/work" "$@" >"${OUT}/c${n}.out" 2>&1 || rc=$?
  local ok=1 why=""
  (( rc == want )) || { ok=0; why="exit ${rc}, wanted ${want}"; }
  local verdict; verdict="$(python3 -I -c 'import json,sys;print(json.load(open(sys.argv[1]))["verdict"])' "${d}/smoke_log.json" 2>/dev/null || echo NO_LOG)"
  [[ "${verdict}" != PASS ]] || [[ "${want}" == 0 ]] || { ok=0; why+=" (smoke wrongly reported PASS)"; }
  if pgrep -f "openEMS .*${d}" >/dev/null 2>&1; then ok=0; why+=" (solver process left running)"; fi
  local after; after="$(git -C "${REPO_ROOT}" status --porcelain --untracked-files=all)"
  [[ "${after}" == "${before}" ]] || { ok=0; why+=" (repository work tree changed)"; }
  local how="rejected with"; (( want == 0 )) && how="accepted with"
  if (( ok )); then printf 'PASS  %-22s %s exit %-3s verdict=%s\n' "${name}" "${how}" "${rc}" "${verdict}"
  else printf 'FAIL  %-22s %s\n' "${name}" "${why}"; tail -3 "${OUT}/c${n}.out" | sed 's/^/        /'; fails=$((fails+1)); fi
}

echo "baseline (must pass):"
run "baseline-honest" 0 NEG_CONTROL=1 -- 
echo "negative controls (each must be rejected):"
# a python that cannot import the bindings: the system interpreter, never the venv
run "missing-binding" 14 "OPENEMS_PYTHON=/usr/bin/python3" -- 
run "missing-executable" 10 "PATH=${BARE_PATH}" -- 
run "solver-failure-stub" 11 "PATH=${STUB}:${PATH}" -- 
run "solver-failure-xml"  11 NEG_CONTROL=1 -- --inject corrupt-xml
run "timeout"             124 NEG_CONTROL=1 -- --timeout 1
run "memory-limit"        125 NEG_CONTROL=1 -- --rss-max-mb 20
run "wrong-expectation"   13  NEG_CONTROL=1 -- --expect-scale 1.02

probe_ctl() {  # probe_ctl <name> <must-mention> <env...>: probe.sh must exit 1 and name the missing item
  local name="$1" mention="$2"; shift 2; n=$((n+1)); local rc=0
  env "$@" "${HERE}/probe.sh" >"${OUT}/p${n}.out" 2>"${OUT}/p${n}.err" || rc=$?
  if (( rc == 1 )) && grep -q -- "${mention}" "${OUT}/p${n}.err"; then printf 'PASS  %-22s probe exit 1, names: %s\n' "${name}" "${mention}"
  else printf 'FAIL  %-22s probe exit %s (wanted 1 naming %s)\n' "${name}" "${rc}" "${mention}"; fails=$((fails+1)); fi
}
echo "probe controls (dependency probe must fail nonzero and name the gap):"
probe_ctl "probe-missing-binding"  "cannot import openEMS, CSXCAD, gds2openEMS" "OPENEMS_PYTHON=/usr/bin/python3"
probe_ctl "probe-missing-exec"     "executable 'openEMS' not on PATH"           "PATH=${BARE_PATH}"
echo
if (( fails )); then echo "NEGATIVE CONTROLS FAILED: ${fails} of ${n} did not behave as declared" >&2; exit 1; fi
echo "NEGATIVE CONTROLS OK: ${n} runs (1 baseline acceptance + $((n-1)) correct rejections)"
