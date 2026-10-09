#!/usr/bin/env bash
# Cold-start invocation (bounded p1-only campaign, issue #25):
#
#   sim/passive-p1/run_extraction.sh
#
# Adapted from 2AMLogic/sg13g2-vco @ ee69f8529df3 sim/inductor-model/em-extraction/
# run_extraction.sh (original kept in upstream/).  Differences: p1 only; the
# convergence stage is the declared 1.0 vs 0.5 um mesh and 200 vs 400 um
# margin pair; every outcome that is not a completed run writes an append-only
# `CAPABILITY_UNAVAILABLE` record (failed command + detail) instead of a bare
# error; no analytic-model dependency; nothing outside this directory is written.
#
# Stages (EM_STAGES, space separated, default: all):
#   geometry     regenerate the PCell GDS into results/geometry_regen/ and compare
#                its hash with the pinned gds/inductor_p1.gds (pinned file untouched)
#   em           baseline openEMS 2-port solve (1.0 um mesh, 200 um margin)
#   convergence  mesh 0.5 um (margin 200) and margin 400 um (mesh 1.0) solves
#   post         de-embed, L/Q/Z/SRF at 17.7/19.45/21.2 GHz, convergence deltas
#   fit          lumped .subckt fit to the baseline run
#   compare      ngspice fitted model vs de-embedded Touchstone; writes the record
#
#   EM_STAGES="post fit compare" sim/passive-p1/run_extraction.sh   # from saved outputs
#
# PREREQUISITES (checked up front; a missing one ends in CAPABILITY_UNAVAILABLE)
#   geometry:        klayout on PATH; git + network (setup_pdk_overlay.sh clones two
#                    pinned IHP helper repos into $TMPDIR; the PDK install is not modified)
#   em, convergence: openEMS on PATH and an openEMS python ($OPENEMS_PYTHON, default
#                    ~/opt/openEMS/venv/bin/python) that imports openEMS, CSXCAD and
#                    gds2openEMS
#   post/fit/compare: $FIT_PYTHON (default python3) with numpy + scipy; ngspice (compare)
#   all:             an IHP-Open-PDK v0.3.0 tree: $IHP_PDK_ROOT, or $PDK_ROOT/ihp-sg13g2,
#                    or ~/share/pdk/ihp-sg13g2
# Host provisioning is out of scope: nothing is installed by this script.
#
# Publication (issue #58): each record is preceded by an exclusively created, hashed
# copy of the solver artifacts it was derived from, sim/passive-p1/solver-artifacts/<id>/
# (see scripts/freeze_package.py).  results/ fit/ run_log/ stay mutable scratch for the
# next run.  Publication is refused (exit 2, no record) if a needed stage output is missing.
#
# Exit status: 0 completed (the record's STATUS is the scientific verdict);
# 2 malformed data; 3 capability unavailable (record written); 4 fit failed.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EM_STAGES="${EM_STAGES:-geometry em convergence post fit compare}"
stage() { [[ " ${EM_STAGES} " == *" $1 "* ]]; }

FSTOP="${EM_FSTOP:-30e9}"; NUMFREQ="${EM_NUMFREQ:-601}"; ENERGY="${EM_ENERGY:--50}"
CPW="${EM_CPW:-20}"; THREADS="${EM_THREADS:-2}"
BASE_CELL=1.0; FINE_CELL=0.5; BASE_MARGIN=200; BIG_MARGIN=400   # declared, not tunable

OPENEMS_PYTHON="${OPENEMS_PYTHON:-$HOME/opt/openEMS/venv/bin/python}"
FIT_PYTHON="${FIT_PYTHON:-python3}"
CMDS="EM_STAGES=\"${EM_STAGES}\" FIT_PYTHON=${FIT_PYTHON} OPENEMS_PYTHON=${OPENEMS_PYTHON} sim/passive-p1/run_extraction.sh"
NOTE=""
# Recorded in the frozen package's settings.json (issue #58); the declared cells/margins are fixed above.
SETTINGS_JSON="{\"EM_FSTOP\": \"${FSTOP}\", \"EM_NUMFREQ\": \"${NUMFREQ}\", \"EM_ENERGY\": \"${ENERGY}\", \"EM_CPW\": \"${CPW}\", \"EM_THREADS\": \"${THREADS}\", \"base_cell_um\": ${BASE_CELL}, \"fine_cell_um\": ${FINE_CELL}, \"base_margin_um\": ${BASE_MARGIN}, \"big_margin_um\": ${BIG_MARGIN}}"
mkdir -p "${HERE}"/{results,fit,run_log,records}

unavailable() {  # unavailable <failed command> <detail>
  echo "CAPABILITY_UNAVAILABLE: $1 -- $2" >&2
  python3 -I "${HERE}/scripts/make_record.py" --dir "${HERE}" --unavailable \
    --failed-command "$1" --detail "$2" --stages "${EM_STAGES}" --commands "${CMDS}" --note "${NOTE:-}" \
    --solver-settings "${SETTINGS_JSON}"
  exit 3
}
check() {  # check <description/command shown> <command...>; unavailable on failure
  local shown="$1"; shift
  local out
  if ! out="$("$@" 2>&1)"; then unavailable "${shown}" "${out:-exit nonzero}"; fi
}

# --- resolve the PDK --------------------------------------------------------
if [[ -n "${IHP_PDK_ROOT:-}" ]]; then PDK="${IHP_PDK_ROOT}"
elif [[ -n "${PDK_ROOT:-}" && -d "${PDK_ROOT}/ihp-sg13g2" ]]; then PDK="${PDK_ROOT}/ihp-sg13g2"
elif [[ -d "$HOME/share/pdk/ihp-sg13g2" ]]; then PDK="$HOME/share/pdk/ihp-sg13g2"
else PDK=""; fi
if stage geometry || stage em || stage convergence; then
  [[ -n "${PDK}" && -d "${PDK}" ]] || unavailable "resolve IHP-Open-PDK (IHP_PDK_ROOT, PDK_ROOT/ihp-sg13g2, ~/share/pdk/ihp-sg13g2)" "no PDK install found"
fi

# --- preflight --------------------------------------------------------------
if stage geometry; then check "command -v klayout" bash -c 'command -v klayout'; fi
if stage post || stage fit || stage compare; then
  check "${FIT_PYTHON} -c 'import numpy, scipy'" "${FIT_PYTHON}" -c 'import numpy, scipy'
fi
if stage compare; then check "command -v ngspice" bash -c 'command -v ngspice'; fi

# EM prerequisites are checked together, immediately before the first solve (after
# the geometry stage), and ALL failures go into one record.
preflight_em() {
  local fails="" detail="" out
  if ! out="$(command -v openEMS 2>&1)"; then fails+="command -v openEMS; "; detail+="openEMS not found on PATH. "; fi
  if ! out="$("${OPENEMS_PYTHON}" -c 'import openEMS, CSXCAD, gds2openEMS' 2>&1)"; then
    fails+="${OPENEMS_PYTHON} -c 'import openEMS, CSXCAD, gds2openEMS'; "; detail+="${out:-import failed} "
  fi
  if ! out="$(python3 -I -c 'import CSXCAD' 2>&1)"; then
    fails+="python3 -I -c 'import CSXCAD'; "; detail+="[system python3] $(echo "${out}" | tail -1). "
  fi
  [[ -z "${fails}" ]] || unavailable "${fails%; }" "${detail}"
}

XML="${HERE}/stackup/SG13G2.xml"
GDS="${HERE}/gds/inductor_p1.gds"

# ---------------------------------------------------------------- geometry --
if stage geometry; then
  echo "== geometry: instantiate the PDK inductor2 PCell for p1, compare with pinned GDS =="
  OVERLAY="${TMPDIR:-/tmp}/sg13g2-pycell-overlay"; KLTMP="$(mktemp -d)"
  mkdir -p "${HERE}/results/geometry_regen"
  bash "${HERE}/scripts/setup_pdk_overlay.sh" "${PDK}/libs.tech/klayout" "${OVERLAY}" \
    > "${HERE}/results/geometry_regen/pdk_overlay.json" 2> "${HERE}/run_log/geometry_overlay.txt" \
    || unavailable "scripts/setup_pdk_overlay.sh" "$(tail -3 "${HERE}/run_log/geometry_overlay.txt")"
  KLAYOUT_PATH="${KLTMP}" klayout -zz -r "${HERE}/scripts/gen_geometry.py" \
    -rd pdk_klayout="${OVERLAY}" -rd geom=p1 \
    -rd out="${HERE}/results/geometry_regen/inductor_p1.gds" \
    -rd outjson="${HERE}/results/geometry_regen/inductor_p1.json" \
    > "${HERE}/run_log/geometry_p1.txt" 2>&1 \
    || unavailable "klayout -zz -r scripts/gen_geometry.py (geom=p1)" "$(tail -3 "${HERE}/run_log/geometry_p1.txt")"
  rm -rf "${KLTMP}"
  a="$(sha256sum "${GDS}" | cut -d' ' -f1)"; b="$(sha256sum "${HERE}/results/geometry_regen/inductor_p1.gds" | cut -d' ' -f1)"
  echo "pinned gds sha256 ${a}"; echo "regenerated  sha256 ${b}"
  [[ "${a}" == "${b}" ]] && echo "geometry: regenerated GDS is byte-identical to the pinned input" \
                         || echo "geometry: bytes differ from the pinned input (GDS headers carry timestamps); checking geometry per layer"
  klayout -zz -r "${HERE}/scripts/gds_xor.py" -rd a="${GDS}" -rd b="${HERE}/results/geometry_regen/inductor_p1.gds" \
    2>&1 | tee "${HERE}/run_log/geometry_xor.txt" | tail -6
  cmp -s <("${FIT_PYTHON}" -c 'import json,sys;print(json.dumps(json.load(open(sys.argv[1])),sort_keys=True))' "${HERE}/gds/inductor_p1.json") \
         <("${FIT_PYTHON}" -c 'import json,sys;print(json.dumps(json.load(open(sys.argv[1])),sort_keys=True))' "${HERE}/results/geometry_regen/inductor_p1.json") \
    && echo "geometry: regenerated geometry JSON identical to pinned" || echo "geometry: WARNING geometry JSON differs"
  NOTE="Stage note: the geometry stage ran before the failure. Regenerated PCell GDS sha256 ${b} vs pinned ${a} (bytes differ by header content); per-layer XOR result: $(tail -1 "${HERE}/run_log/geometry_xor.txt") (run_log/geometry_xor.txt). This confirms the pinned input only; it is not an EM result."
fi

run_em() {  # run_em <label> <cellsize> <margin> <outdir>
  local label="$1" cs="$2" mg="$3" out="$4"
  echo "== em: ${label} (cellsize=${cs}um margin=${mg}um) =="
  "${OPENEMS_PYTHON}" "${HERE}/scripts/run_openems.py" --geom p1 --gds "${GDS}" \
    --geom-json "${HERE}/gds/inductor_p1.json" --xml "${XML}" --out "${out}" --s2p "${out}.s2p" \
    --fstop "${FSTOP}" --numfreq "${NUMFREQ}" --cellsize "${cs}" --margin "${mg}" \
    --energy-limit "${ENERGY}" --cells-per-wavelength "${CPW}" --threads "${THREADS}" \
    > "${HERE}/run_log/em_${label}.txt" 2>&1
  local rc=$?
  tail -5 "${HERE}/run_log/em_${label}.txt"
  # solver input traces (regenerable, ~MB each) are dropped; port probes are kept
  rm -f "${out}"/sub-*/et "${out}"/sub-*/ht
  [[ ${rc} -eq 0 ]] || unavailable "run_openems.py ${label} (exit ${rc})" "$(tail -3 "${HERE}/run_log/em_${label}.txt")"
}

if stage em || stage convergence; then preflight_em; fi
if stage em; then run_em p1 "${BASE_CELL}" "${BASE_MARGIN}" "${HERE}/results/inductor_p1"; fi
if stage convergence; then
  mkdir -p "${HERE}/results/convergence"
  run_em conv_p1_mesh0p5 "${FINE_CELL}" "${BASE_MARGIN}" "${HERE}/results/convergence/p1_mesh0p5"
  run_em conv_p1_margin400 "${BASE_CELL}" "${BIG_MARGIN}" "${HERE}/results/convergence/p1_margin400"
fi

# ----------------------------------------------- post / fit / compare / record
rec() {  # rec [extra make_record args]
  "${FIT_PYTHON}" "${HERE}/scripts/make_record.py" --dir "${HERE}" --stages "${EM_STAGES}" --commands "${CMDS}" \
    --solver-settings "${SETTINGS_JSON}" "$@"
}
if stage post || stage fit || stage compare; then
  if stage post; then
    "${FIT_PYTHON}" "${HERE}/scripts/postprocess_p1.py" --dir "${HERE}" 2>&1 | tee "${HERE}/run_log/postprocess.txt"
    rc=${PIPESTATUS[0]}
    [[ ${rc} -eq 3 ]] && unavailable "scripts/postprocess_p1.py (saved solver output)" "$(head -1 "${HERE}/run_log/postprocess.txt")"
    [[ ${rc} -eq 0 ]] || { echo "post failed (exit ${rc}); no record, no metrics" >&2; exit "${rc}"; }
    if ! grep -q '"converged": true' "${HERE}/results/p1_metrics.json"; then
      echo "UNCONVERGED: stopping the bounded campaign (no fit, no model)"; rec || exit $?; exit 0
    fi
  fi
  if stage fit; then
    "${FIT_PYTHON}" "${HERE}/scripts/fit_p1.py" --dir "${HERE}" 2>&1 | tee "${HERE}/run_log/fit.txt"
    rc=${PIPESTATUS[0]}
    if [[ ${rc} -eq 4 ]]; then rec --fit-problem "$(tail -1 "${HERE}/run_log/fit.txt")" || exit $?; exit 4; fi
    [[ ${rc} -eq 0 ]] || exit "${rc}"
  fi
  if stage compare; then
    "${FIT_PYTHON}" "${HERE}/scripts/compare_p1.py" --dir "${HERE}" 2>&1 | tee "${HERE}/run_log/compare.txt"
    rc=${PIPESTATUS[0]}
    [[ ${rc} -eq 0 ]] || exit "${rc}"
    rec || exit $?
  fi
fi
echo "done."
