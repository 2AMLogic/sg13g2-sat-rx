#!/usr/bin/env bash
# Cold-start invocation:
#
#   sim/inductor-model/em-extraction/run_extraction.sh
#
# WHAT IT DOES
# ------------
# EM-extracts the IHP SG13G2 spiral-inductor PCell with openEMS (FDTD) for the
# three PDK LVS-testcase geometries, fits a lumped `.subckt inductor la lb sub`
# to the extraction, and records the extraction-vs-analytic delta against
# ../sg13g2_inductor_analytic.spice.
#
# Stages, each skippable via EM_STAGES:
#   geometry     instantiate the PDK's own inductor PCell -> gds/
#   em           openEMS 2-port solve per geometry        -> results/
#   convergence  mesh + boundary-margin convergence runs  -> results/convergence/
#   post         de-embed ports, extract L/Q/SRF          -> results/*.csv
#   fit          fit the lumped subckt                    -> fit/, ../sg13g2_inductor_em.spice
#   compare      EM vs analytic, via ngspice              -> records/
#
#   EM_STAGES="geometry em post fit compare" sim/.../run_extraction.sh
#
# REQUIREMENTS (all verified up front, and named with versions in the record):
#   * klayout             -- to instantiate the PDK PCell headlessly
#   * an openEMS python   -- $OPENEMS_PYTHON, default ~/opt/openEMS/venv/bin/python
#   * python3 with numpy+scipy -- for the fit (does NOT need openEMS)
#   * ngspice             -- for the analytic-vs-EM comparison
#   * an IHP-Open-PDK install -- $PDK_ROOT/ihp-sg13g2 or $IHP_PDK_ROOT
#
# The openEMS solve is skipped automatically when the CSX model hash matches a
# previous run's, so re-running this script after only changing the fit or the
# comparison costs seconds rather than the full FDTD time.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INDDIR="$(cd "${HERE}/.." && pwd)"
# shellcheck disable=SC2034 # kept for parity with sibling run_*.sh preambles; not consumed in this script
REPO_ROOT="$(cd "${INDDIR}/../.." && pwd)"

EM_STAGES="${EM_STAGES:-geometry em convergence post fit compare}"
stage() { [[ " ${EM_STAGES} " == *" $1 "* ]]; }

GEOMS=(p1 p13 p11)

# --- extraction settings (also recorded into every run_meta.json) -----------
FSTOP="${EM_FSTOP:-30e9}"          # issue #9 asks for at least 0.1 .. 30 GHz
NUMFREQ="${EM_NUMFREQ:-601}"       # 50 MHz grid
CELLSIZE="${EM_CELLSIZE:-1.0}"     # refined mesh cell size at conductor edges, um
MARGIN="${EM_MARGIN:-200}"         # distance from GDS bbox to the PEC box, um
ENERGY="${EM_ENERGY:--50}"         # residual-energy end criterion, dB
CPW="${EM_CPW:-20}"                # cells per wavelength in the coarse mesh
THREADS="${EM_THREADS:-$(nproc 2>/dev/null || echo 4)}"

OPENEMS_PYTHON="${OPENEMS_PYTHON:-$HOME/opt/openEMS/venv/bin/python}"
FIT_PYTHON="${FIT_PYTHON:-python3}"

# --- resolve the PDK --------------------------------------------------------
if [[ -n "${IHP_PDK_ROOT:-}" ]]; then
  PDK="${IHP_PDK_ROOT}"
elif [[ -n "${PDK_ROOT:-}" && -d "${PDK_ROOT}/ihp-sg13g2" ]]; then
  PDK="${PDK_ROOT}/ihp-sg13g2"
elif [[ -d "$HOME/share/pdk/ihp-sg13g2" ]]; then
  PDK="$HOME/share/pdk/ihp-sg13g2"
else
  echo "error: cannot find an IHP-Open-PDK install; set IHP_PDK_ROOT" >&2
  exit 1
fi
PDK_KLAYOUT="${PDK}/libs.tech/klayout"

need() { command -v "$1" >/dev/null 2>&1 || { echo "error: $1 not on PATH" >&2; exit 1; }; }
if stage geometry; then need klayout; fi
if stage em || stage convergence; then
  need openEMS
  [[ -x "${OPENEMS_PYTHON}" ]] || { echo "error: no openEMS python at ${OPENEMS_PYTHON}" >&2; exit 1; }
  "${OPENEMS_PYTHON}" -c 'import openEMS, CSXCAD, gds2openEMS' \
    || { echo "error: ${OPENEMS_PYTHON} cannot import openEMS/CSXCAD/gds2openEMS" >&2; exit 1; }
fi
if stage compare; then need ngspice; fi
"${FIT_PYTHON}" -c 'import numpy, scipy' >/dev/null 2>&1 \
  || { echo "error: ${FIT_PYTHON} lacks numpy/scipy (needed by the fit)" >&2; exit 1; }

mkdir -p "${HERE}"/{gds,results,fit,run_log,stackup}

# ---------------------------------------------------------------- geometry --
if stage geometry; then
  echo "== geometry: instantiating the PDK's own inductor PCell =="
  OVERLAY="${TMPDIR:-/tmp}/sg13g2-pycell-overlay"
  bash "${HERE}/scripts/setup_pdk_overlay.sh" "${PDK_KLAYOUT}" "${OVERLAY}" \
    > "${HERE}/gds/pdk_overlay.json"
  cat "${HERE}/gds/pdk_overlay.json"
  KLTMP="$(mktemp -d)"; trap 'rm -rf "${KLTMP}"' EXIT
  for g in "${GEOMS[@]}"; do
    KLAYOUT_PATH="${KLTMP}" klayout -zz -r "${HERE}/scripts/gen_geometry.py" \
      -rd pdk_klayout="${OVERLAY}" -rd geom="${g}" \
      -rd out="${HERE}/gds/inductor_${g}.gds" \
      -rd outjson="${HERE}/gds/inductor_${g}.json" \
      2>&1 | grep -v "psutil" | tee "${HERE}/run_log/geometry_${g}.txt" | head -2
  done
fi

# --- copy IHP's own openEMS stackup next to the evidence, for provenance ----
if [[ ! -f "${HERE}/stackup/SG13G2.xml" ]]; then
  cp "${PDK}/libs.tech/openems/openems_ihp_sg13g2/workflow/SG13G2.xml" "${HERE}/stackup/"
fi
XML="${HERE}/stackup/SG13G2.xml"

run_em() {  # run_em <label> <geom> <cellsize> <margin> <outdir>
  local label="$1" g="$2" cs="$3" mg="$4" out="$5"
  echo "== em: ${label} (geom=${g} cellsize=${cs}um margin=${mg}um) =="
  "${OPENEMS_PYTHON}" "${HERE}/scripts/run_openems.py" \
    --geom "${g}" \
    --gds "${HERE}/gds/inductor_${g}.gds" \
    --geom-json "${HERE}/gds/inductor_${g}.json" \
    --xml "${XML}" \
    --out "${out}" \
    --s2p "${out}.s2p" \
    --fstop "${FSTOP}" --numfreq "${NUMFREQ}" \
    --cellsize "${cs}" --margin "${mg}" \
    --energy-limit "${ENERGY}" --cells-per-wavelength "${CPW}" \
    --threads "${THREADS}" \
    2>&1 | tee "${HERE}/run_log/em_${label}.txt" | tail -20
  # The Gaussian excitation trace (et) and its magnetic counterpart (ht) are
  # solver INPUTS, regenerable and ~2.5 MB each; the port voltage/current
  # probes that the S-parameters are actually computed from are kept.
  rm -f "${out}"/sub-*/et "${out}"/sub-*/ht
}

# --------------------------------------------------------------------- em --
if stage em; then
  for g in "${GEOMS[@]}"; do
    run_em "${g}" "${g}" "${CELLSIZE}" "${MARGIN}" "${HERE}/results/inductor_${g}"
  done
fi

# ------------------------------------------------------------ convergence --
# Two one-variable-at-a-time checks on the smallest geometry, because both
# knobs bias the answer in a known direction and the record should show by how
# much rather than assert that the default was fine:
#   * refined_cellsize: the FDTD mesh through the 3 um TopMetal2 sets how much
#     of the skin effect is resolved; too coarse => R too low => Q too high.
#   * margin: the domain is a closed PEC box, whose walls image the coil's
#     current and pull L down; too small => L too low.
if stage convergence; then
  mkdir -p "${HERE}/results/convergence"
  run_em "conv_p1_mesh0p5" p1 0.5 "${MARGIN}" "${HERE}/results/convergence/p1_mesh0p5"
  run_em "conv_p1_margin400" p1 "${CELLSIZE}" 400 "${HERE}/results/convergence/p1_margin400"
fi

# ------------------------------------------------------------------- post --
if stage post; then
  echo "== post: de-embedding ports and extracting L/Q/SRF =="
  "${FIT_PYTHON}" "${HERE}/scripts/postprocess.py" --dir "${HERE}" \
    2>&1 | tee "${HERE}/run_log/postprocess.txt"
fi

# -------------------------------------------------------------------- fit --
if stage fit; then
  echo "== fit: lumped .subckt inductor fitted to the extraction =="
  "${FIT_PYTHON}" "${HERE}/scripts/fit_lumped.py" --dir "${HERE}" \
    --model-out "${INDDIR}/sg13g2_inductor_em.spice" \
    2>&1 | tee "${HERE}/run_log/fit.txt"
fi

# ---------------------------------------------------------------- compare --
if stage compare; then
  echo "== compare: EM extraction vs analytic screening model =="
  "${FIT_PYTHON}" "${HERE}/scripts/compare_analytic.py" --dir "${HERE}" \
    --analytic "${INDDIR}/sg13g2_inductor_analytic.spice" \
    --fitted "${INDDIR}/sg13g2_inductor_em.spice" \
    2>&1 | tee "${HERE}/run_log/compare.txt"
fi

echo "done."
