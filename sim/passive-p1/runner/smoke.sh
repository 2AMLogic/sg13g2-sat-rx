#!/usr/bin/env bash
# Run the real openEMS known-answer control (smoke_cavity.py) under enforced limits and
# write a resource/version log.   Issue #46.
#
#   smoke.sh [--log-dir DIR] [--work-dir DIR] [--timeout S] [--rss-max-mb M] [--threads N]
#            [--expect-scale X] [--inject none|corrupt-xml|no-excitation]
#
# Environment (normally set by `source <prefix>/activate.sh`): OPENEMS_PYTHON (python with
# openEMS+CSXCAD bindings), PATH containing openEMS.  Nothing is written inside the repository:
# --log-dir and --work-dir must resolve outside it (defaults: a fresh dir under
# ${PASSIVE_P1_RUNNER_PREFIX:-${TMPDIR:-/tmp}}).
#
# Limits (LIMITS.env; flags may only lower them):  threads <= 2, wall <= 180 s, RSS <= 2048 MB.
# Exit status: 0 pass; 10 missing openEMS executable; 14 missing python binding; 11 solver failure; 13 numerical failure
# (non-finite / outside tolerance); 124 timeout; 125 memory limit; 2 usage / limit refused.
# Distinct codes are deliberate: the negative controls assert them.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../../.." && pwd)"
# shellcheck disable=SC1091
source "${HERE}/LIMITS.env"
cap_threads="${RUNNER_THREADS%%[ #]*}"; cap_t="${RUNNER_SMOKE_TIMEOUT_S%%[ #]*}"; cap_rss="${RUNNER_SMOKE_RSS_MAX_MB%%[ #]*}"
THREADS="${EM_THREADS:-${cap_threads}}"; TIMEOUT="${cap_t}"; RSS="${cap_rss}"
LOG_DIR=""; WORK_DIR=""; SCALE=1.0; INJECT=none
die() { echo "smoke: $*" >&2; exit 2; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --log-dir) LOG_DIR="$2"; shift 2;;  --work-dir) WORK_DIR="$2"; shift 2;;
    --timeout) TIMEOUT="$2"; shift 2;;  --rss-max-mb) RSS="$2"; shift 2;;
    --threads) THREADS="$2"; shift 2;;  --expect-scale) SCALE="$2"; shift 2;;
    --inject) INJECT="$2"; shift 2;;    *) die "unknown option $1";;
  esac
done
for pair in "THREADS:${cap_threads}" "TIMEOUT:${cap_t}" "RSS:${cap_rss}"; do
  n="${pair%%:*}"; cap="${pair##*:}"; v="${!n}"
  [[ "$v" =~ ^[0-9]+(\.[0-9]+)?$ ]] || die "$n='$v' is not a number"
  awk -v v="$v" -v c="$cap" 'BEGIN{exit !(v>0 && v<=c)}' || die "$n=$v outside the declared bound (0, $cap] (LIMITS.env)"
done

BASE="${PASSIVE_P1_RUNNER_PREFIX:-${TMPDIR:-/tmp}}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)-$$"
[[ -n "${LOG_DIR}" ]] || LOG_DIR="${BASE}/smoke/${STAMP}"
[[ -n "${WORK_DIR}" ]] || WORK_DIR="${BASE}/smoke/${STAMP}/work"
LOG_DIR="$(realpath -m -- "${LOG_DIR}")"; WORK_DIR="$(realpath -m -- "${WORK_DIR}")"
for d in "${LOG_DIR}" "${WORK_DIR}"; do
  case "${d}/" in "${REPO_ROOT}/"*) die "'${d}' is inside the repository; smoke output must stay outside tracked evidence directories";; esac
done
mkdir -p -- "${LOG_DIR}" "${WORK_DIR}"

OPENEMS_PYTHON="${OPENEMS_PYTHON:-python3}"
export OMP_NUM_THREADS="${THREADS}" OPENBLAS_NUM_THREADS="${THREADS}"
REPORT="${LOG_DIR}/smoke_report.json"; LIMITS_JSON="${LOG_DIR}/limits.json"; rm -f "${REPORT}" "${LIMITS_JSON}"

python3 -I "${HERE}/limited_run.py" --timeout "${TIMEOUT}" --rss-max-mb "${RSS}" --json "${LIMITS_JSON}" -- \
  "${OPENEMS_PYTHON}" -I "${HERE}/smoke_cavity.py" --workdir "${WORK_DIR}/cavity" --threads "${THREADS}" \
  --report "${REPORT}" --expect-scale "${SCALE}" --inject "${INJECT}"
rc=$?
(( rc == 127 )) && { echo "smoke: OPENEMS_PYTHON=${OPENEMS_PYTHON} could not be started" >&2; rc=14; }

# One merged, human-and-machine-readable log (never inside the repo).  Written on pass AND fail.
python3 -I - "${REPORT}" "${LIMITS_JSON}" "${LOG_DIR}/smoke_log.json" "${rc}" "${THREADS}" "${TIMEOUT}" "${RSS}" "${OPENEMS_PYTHON}" <<'PY'
import json, os, sys
rep_p, lim_p, out_p, rc, threads, timeout, rss, py = sys.argv[1:9]
rep = json.load(open(rep_p)) if os.path.isfile(rep_p) else {"result": "NO_REPORT"}
lim = json.load(open(lim_p)) if os.path.isfile(lim_p) else {}
verdict = {0: "PASS", 10: "FAIL_NO_EXECUTABLE", 14: "FAIL_NO_BINDING", 11: "FAIL_SOLVER", 13: "FAIL_NUMERICAL", 124: "FAIL_TIMEOUT", 125: "FAIL_MEMORY"}.get(int(rc), "FAIL_OTHER")
log = {"schema": 1, "control": "openEMS pec-cavity-resonance (issue #46 preparation smoke)", "verdict": verdict,
       "exit_status": int(rc), "enforced_limits": {"threads": int(threads), "wall_timeout_s": float(timeout), "rss_max_mb": float(rss)},
       "measured": {"wall_s": lim.get("wall_s"), "peak_tree_rss_mb": lim.get("peak_tree_rss_mb"),
                    "largest_child_maxrss_mb": lim.get("largest_child_maxrss_mb"), "monitor_verdict": lim.get("verdict"),
                    "solver_wall_s": rep.get("solver_wall_s")},
       "openems_python": py, "report": rep,
       "statement": "A PASS shows the openEMS solver executes and reproduces a closed-form cavity spectrum. It is not p1 EM evidence and does not qualify any passive."}
json.dump(log, open(out_p, "w"), indent=2, sort_keys=True); open(out_p, "a").write("\n")
PY
echo "smoke: exit ${rc}; log ${LOG_DIR}/smoke_log.json"
exit "${rc}"
