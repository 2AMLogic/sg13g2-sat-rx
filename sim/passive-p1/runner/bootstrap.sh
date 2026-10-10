#!/usr/bin/env bash
# User-owned, bounded bootstrap of the openEMS toolchain for sim/passive-p1 (issue #46).
#
#   bootstrap.sh build <prefix> [--skip-ngspice] [--skip-pdk]
#   bootstrap.sh clean <prefix> [--caches]
#
# <prefix> is caller-selected, must be OUTSIDE this repository, and must not
# exist, or be empty, or be an earlier runner prefix.  Needs no root, no secrets
# and no container daemon; only public downloads at the pins in LOCK.env.
# System build prerequisites (compilers, headers) are only *checked*
# (probe.sh --build) and never installed; a missing one aborts with its name.
#
# Layout written under <prefix> (nothing is written anywhere else; every
# temporary file lives under <prefix>/tmp):
#   venv/            isolated Python (pinned wheels with hashes + openEMS/CSXCAD/gds2openEMS)
#   openems/         openEMS + CSXCAD C++ install (bin/openEMS, lib/)
#   ngspice/         ngspice 46 install (bin/ngspice)
#   pdk/IHP-Open-PDK/ihp-sg13g2   sparse checkout of the pinned PDK (read-only use)
#   src/ tmp/ dl/    sources, build trees, downloads (removable: `clean <prefix> --caches`)
#   activate.sh      source it to set OPENEMS_PYTHON FIT_PYTHON IHP_PDK_ROOT PATH ...
#   provenance.json  every pin, checksum, tool version and per-phase wall/peak-memory
#   logs/            per-phase logs and limit measurements
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../../.." && pwd)"
# shellcheck disable=SC1091
source "${HERE}/LOCK.env"; source "${HERE}/LIMITS.env"

die() { echo "bootstrap: ABORT: $*" >&2; exit 1; }
usage() { sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 2; }

# ---- limits: the environment may only lower the declared values ----------------
lower() { local name="$1" cap="$2" v; v="${!1:-$2}"; [[ "${v}" =~ ^[0-9]+$ ]] || die "$name='${v}' is not an integer"; (( v <= cap )) || die "$name=${v} exceeds the declared cap ${cap} (LIMITS.env)"; printf -v "$name" '%s' "$v"; }
lower RUNNER_THREADS "${RUNNER_THREADS%%[ #]*}"; lower RUNNER_BUILD_JOBS "${RUNNER_BUILD_JOBS%%[ #]*}"
lower RUNNER_BUILD_TIMEOUT_S "${RUNNER_BUILD_TIMEOUT_S%%[ #]*}"; lower RUNNER_DISK_MAX_PREFIX_GB "${RUNNER_DISK_MAX_PREFIX_GB%%[ #]*}"
(( RUNNER_BUILD_JOBS >= 1 && RUNNER_THREADS >= 1 )) || die "jobs/threads must be >= 1"

cmd="${1:-}"; shift || true
PREFIX_ARG="${1:-}"; shift || true
[[ -n "${cmd}" && -n "${PREFIX_ARG}" ]] || usage
[[ "${PREFIX_ARG}" = /* ]] || PREFIX_ARG="$PWD/${PREFIX_ARG}"
PREFIX="$(realpath -m -- "${PREFIX_ARG}")"
[[ -n "${PREFIX}" && "${PREFIX}" != "/" && "${PREFIX}" != "${HOME}" ]] || die "refusing prefix '${PREFIX}'"
case "${PREFIX}/" in "${REPO_ROOT}/"*) die "prefix '${PREFIX}' is inside the repository '${REPO_ROOT}'; choose a directory outside it";; esac

case "${cmd}" in
clean)
  [[ -f "${PREFIX}/.passive-p1-runner" ]] || die "'${PREFIX}' is not a runner prefix (marker .passive-p1-runner missing); nothing removed"
  if [[ "${1:-}" == "--caches" ]]; then
    rm -rf -- "${PREFIX:?}/src" "${PREFIX:?}/tmp" "${PREFIX:?}/dl"; echo "removed build caches under ${PREFIX}"
  else
    rm -rf -- "${PREFIX:?}"; echo "removed ${PREFIX}"
  fi
  exit 0;;
build) ;;
*) usage;;
esac

SKIP_NGSPICE=0; SKIP_PDK=0
for a in "$@"; do case "$a" in --skip-ngspice) SKIP_NGSPICE=1;; --skip-pdk) SKIP_PDK=1;; *) die "unknown option $a";; esac; done

# ---- preflight (before anything is created) -------------------------------------
PRE_ERR="$(mktemp)"
"${HERE}/probe.sh" --build >/dev/null 2>"${PRE_ERR}" || { cat "${PRE_ERR}" >&2; rm -f "${PRE_ERR}"; die "system prerequisites missing (listed above); this script never installs them"; }
rm -f "${PRE_ERR}"
if [[ -e "${PREFIX}" ]] && [[ -n "$(ls -A "${PREFIX}" 2>/dev/null)" ]] && [[ ! -f "${PREFIX}/.passive-p1-runner" ]]; then
  die "prefix '${PREFIX}' exists, is non-empty and is not a runner prefix"
fi
mkdir -p -- "${PREFIX}"
free_gb=$(( $(df -Pk -- "${PREFIX}" | awk 'NR==2{print $4}') / 1048576 ))
if (( free_gb < RUNNER_DISK_MIN_FREE_GB )); then rmdir "${PREFIX}" 2>/dev/null || true; die "only ${free_gb} GiB free on the prefix filesystem; need >= ${RUNNER_DISK_MIN_FREE_GB} GiB (LIMITS.env)"; fi
touch "${PREFIX}/.passive-p1-runner"
mkdir -p "${PREFIX}"/{src,tmp,dl,bin,logs}
export TMPDIR="${PREFIX}/tmp"
# bound every thread pool the build or numpy could spawn
export OMP_NUM_THREADS="${RUNNER_THREADS}" OPENBLAS_NUM_THREADS="${RUNNER_THREADS}" MAKEFLAGS="-j${RUNNER_BUILD_JOBS}"

START=$SECONDS
PHASES_JSON="${PREFIX}/logs/phases.jsonl"; touch "${PHASES_JSON}"
# Resume: a phase that finished under the SAME pins (LOCK.env + both requirement locks + build_ngspice.sh) is skipped on re-run.
PIN_HASH="$(cat "${HERE}/LOCK.env" "${HERE}/requirements-lock.txt" "${HERE}/requirements-sdist-lock.txt" "${HERE}/build_ngspice.sh" | sha256sum | cut -d' ' -f1)"
check_budget() {
  local used=$(( SECONDS - START ))
  (( used < RUNNER_BUILD_TIMEOUT_S )) || die "build wall-clock budget ${RUNNER_BUILD_TIMEOUT_S}s exhausted (used ${used}s)"
  local gb=$(( $(du -sk "${PREFIX}" | cut -f1) / 1048576 ))
  (( gb <= RUNNER_DISK_MAX_PREFIX_GB )) || die "prefix is ${gb} GiB, above the ${RUNNER_DISK_MAX_PREFIX_GB} GiB cap"
}
phase() {  # phase <name> <cmd...>: timeout = remaining budget; records wall + peak memory
  local name="$1"; shift
  local marker="${PREFIX}/logs/${name}.done"
  if [[ -f "${marker}" && "$(cat "${marker}")" == "${PIN_HASH}" ]]; then echo "== phase ${name}: already done under these pins (resume), skipped"; return 0; fi
  check_budget
  local remaining=$(( RUNNER_BUILD_TIMEOUT_S - (SECONDS - START) ))
  echo "== phase ${name} (budget left ${remaining}s)"
  local j="${PREFIX}/logs/${name}.limits.json" rc=0
  python3 -I "${HERE}/limited_run.py" --timeout "${remaining}" --json "${j}" -- "$@" > "${PREFIX}/logs/${name}.txt" 2>&1 || rc=$?
  if (( rc != 0 )); then tail -25 "${PREFIX}/logs/${name}.txt" >&2; die "phase '${name}' failed (exit ${rc}); full log ${PREFIX}/logs/${name}.txt"; fi
  printf '%s' "${PIN_HASH}" > "${marker}"
  python3 -I -c 'import json,sys;d=json.load(open(sys.argv[2]));d["phase"]=sys.argv[1];print(json.dumps(d))' "${name}" "${j}" >> "${PHASES_JSON}"
  echo "   done: $(python3 -I -c 'import json,sys;d=json.load(open(sys.argv[1]));print("wall %.0fs peak_tree_rss %.0f MB" % (d["wall_s"], d["peak_tree_rss_mb"]))' "${j}")"
}

# ---- 1. isolated Python with hash-pinned wheels -----------------------------------
phase venv bash -c '
  set -euo pipefail
  python3 -m venv "$1/venv"
  "$1/venv/bin/python" -m pip install --quiet --disable-pip-version-check --require-hashes --only-binary=:all: -r "$2/requirements-lock.txt"
  # gdspy publishes only an sdist: build it against the already-pinned numpy/setuptools (no build isolation, still hash-checked)
  "$1/venv/bin/python" -m pip install --quiet --disable-pip-version-check --require-hashes --no-build-isolation --no-deps --no-binary=gdspy -r "$2/requirements-sdist-lock.txt"
' _ "${PREFIX}" "${HERE}"

# ---- 2. openEMS + CSXCAD (C++), pinned commit + verified submodule gitlinks --------
SRC="${PREFIX}/src/openEMS-Project"
phase openems-fetch bash -c '
  set -euo pipefail
  source "$2/LOCK.env"
  git init -q "$1"; git -C "$1" remote add origin "$OPENEMS_PROJECT_REPO" 2>/dev/null || git -C "$1" remote set-url origin "$OPENEMS_PROJECT_REPO"
  git -C "$1" fetch -q --depth 1 origin "$OPENEMS_PROJECT_COMMIT" && git -C "$1" checkout -q FETCH_HEAD
  test "$(git -C "$1" rev-parse HEAD)" = "$OPENEMS_PROJECT_COMMIT"
  git -C "$1" submodule update --init --depth 1 fparser CSXCAD openEMS
  chk() { got="$(git -C "$1/$2" rev-parse HEAD)"; [ "$got" = "$3" ] || { echo "submodule $2: got $got want $3" >&2; exit 1; }; }
  chk "$1" fparser "$OPENEMS_SUBMODULE_FPARSER"
  chk "$1" CSXCAD "$OPENEMS_SUBMODULE_CSXCAD"
  chk "$1" openEMS "$OPENEMS_SUBMODULE_OPENEMS"
' _ "${SRC}" "${HERE}"

phase openems-build bash -c '
  set -euo pipefail
  source "$2/venv/bin/activate"
  cd "$1"
  ./update_openEMS.sh "$2/openems" --python --disable-GUI --njobs="$3" --skip-dep-check \
      --python-venv-mode=auto --python-use-network=disable
' _ "${SRC}" "${PREFIX}" "${RUNNER_BUILD_JOBS}"
[[ -x "${PREFIX}/openems/bin/openEMS" ]] || die "openEMS binary missing after build"

# ---- 3. gds2openEMS (pinned IHP helper), without its GUI dependency ------------------
phase gds2openems bash -c '
  set -euo pipefail
  source "$3/LOCK.env"; source "$2/venv/bin/activate"
  git init -q "$1"; git -C "$1" remote add origin "$GDS2OPENEMS_REPO" 2>/dev/null || git -C "$1" remote set-url origin "$GDS2OPENEMS_REPO"
  git -C "$1" fetch -q --depth 1 origin "$GDS2OPENEMS_COMMIT" && git -C "$1" checkout -q FETCH_HEAD
  test "$(git -C "$1" rev-parse HEAD)" = "$GDS2OPENEMS_COMMIT"
  python -m pip install --quiet --disable-pip-version-check --no-deps --no-build-isolation "$1"
' _ "${PREFIX}/src/openems_ihp_sg13g2" "${PREFIX}" "${HERE}"

# ---- 4. ngspice (same pin as CI) -----------------------------------------------------
if (( SKIP_NGSPICE == 0 )); then
  phase ngspice "${HERE}/build_ngspice.sh" "${PREFIX}" "${RUNNER_BUILD_JOBS}"
fi

# ---- 5. pinned IHP-Open-PDK subtrees (sparse; never modified) ------------------------
if (( SKIP_PDK == 0 )); then
  phase pdk bash -c '
    set -euo pipefail
    source "$2/LOCK.env"
    d="$1/pdk/IHP-Open-PDK"; mkdir -p "$d" && cd "$d"
    git init -q .; git remote add origin "$IHP_PDK_REPO" 2>/dev/null || git remote set-url origin "$IHP_PDK_REPO"
    git sparse-checkout init --cone && git sparse-checkout set $IHP_PDK_SPARSE
    git fetch -q --depth 1 --filter=blob:none origin "$IHP_PDK_COMMIT"
    git checkout -q FETCH_HEAD
    test "$(git rev-parse HEAD)" = "$IHP_PDK_COMMIT"
  ' _ "${PREFIX}" "${HERE}"
fi

# ---- 6. activation script and provenance ------------------------------------------------
q() { printf '%q' "$1"; }
cat > "${PREFIX}/activate.sh" <<ACT
# Source this file (bash/zsh):   source <prefix>/activate.sh
# Generated by sim/passive-p1/runner/bootstrap.sh; safe to source repeatedly.
export PASSIVE_P1_RUNNER_PREFIX=$(q "${PREFIX}")
export OPENEMS_PYTHON=$(q "${PREFIX}/venv/bin/python")
export FIT_PYTHON=$(q "${PREFIX}/venv/bin/python")
export IHP_PDK_ROOT=$(q "${PREFIX}/pdk/IHP-Open-PDK/ihp-sg13g2")
export OPENEMS_INSTALL_PATH=$(q "${PREFIX}/openems")
export EM_THREADS=\${EM_THREADS:-${RUNNER_THREADS}}
export OMP_NUM_THREADS=\${EM_THREADS} OPENBLAS_NUM_THREADS=\${EM_THREADS}
case ":\${PATH}:" in *:$(q "${PREFIX}/venv/bin"):*) ;; *) export PATH=$(q "${PREFIX}/venv/bin"):$(q "${PREFIX}/openems/bin"):$(q "${PREFIX}/ngspice/bin"):\${PATH};; esac
case ":\${LD_LIBRARY_PATH:-}:" in *:$(q "${PREFIX}/openems/lib"):*) ;; *) export LD_LIBRARY_PATH=$(q "${PREFIX}/openems/lib")\${LD_LIBRARY_PATH:+:\${LD_LIBRARY_PATH}};; esac
ACT
if (( SKIP_PDK )); then sed -i '/IHP_PDK_ROOT/d' "${PREFIX}/activate.sh"; fi

(
  # shellcheck disable=SC1091
  source "${PREFIX}/activate.sh"
  python3 -I "${HERE}/make_provenance.py" --prefix "${PREFIX}" --lock "${HERE}/LOCK.env" \
     --requirements "${HERE}/requirements-lock.txt" --phases "${PHASES_JSON}" \
     --limits "${HERE}/LIMITS.env" --total-wall-s "$(( SECONDS - START ))" > "${PREFIX}/provenance.json"
)
check_budget
echo "bootstrap OK in $(( SECONDS - START ))s; prefix ${PREFIX}"
echo "next:   source '${PREFIX}/activate.sh' && sim/passive-p1/runner/probe.sh && sim/passive-p1/runner/smoke.sh"
