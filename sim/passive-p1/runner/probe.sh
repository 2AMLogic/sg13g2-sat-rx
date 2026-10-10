#!/usr/bin/env bash
# Dependency probe for sim/passive-p1/run_extraction.sh (issue #46).
#
#   probe.sh            runtime check: every executable / import / path the driver uses
#   probe.sh --build    system prerequisites for bootstrap.sh (compilers, headers); no network
#
# Prints one line per item (ok / MISSING + the exact thing that is missing) and a
# final summary.  Exit 0 only if everything is present; otherwise exit 1.
# It installs nothing and writes nothing.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${HERE}/LOCK.env"
MODE=runtime; [[ "${1:-}" == "--build" ]] && MODE=build

missing=()
ok()   { printf 'ok       %s\n' "$1"; }
miss() { printf 'MISSING  %s\n' "$1" >&2; missing+=("$1"); }
need_cmd() {  # need_cmd <command> [hint]
  if p="$(command -v "$1" 2>/dev/null)"; then ok "$1 -> ${p}"; else miss "executable '$1' not on PATH${2:+ ($2)}"; fi
}
need_hdr() {  # need_hdr <header> <package>
  for d in /usr/include /usr/local/include /usr/include/hdf5/serial /usr/include/python3*; do
    for f in ${d}/$1; do [[ -e "$f" ]] && { ok "header $1"; return; }; done
  done
  miss "header '$1' (apt: $2)"
}

if [[ "${MODE}" == build ]]; then
  for c in gcc g++ make cmake git curl pkg-config bison flex; do need_cmd "$c" "apt: build-essential cmake git curl pkg-config bison flex"; done
  if python3 -c 'import venv, ensurepip' 2>/dev/null; then ok "python3 venv+ensurepip"; else miss "python3 'venv'/'ensurepip' module (apt: python3-venv)"; fi
  need_hdr Python.h python3-dev
  need_hdr boost/version.hpp libboost-all-dev
  need_hdr tinyxml.h libtinyxml-dev
  need_hdr hdf5.h libhdf5-dev
  need_hdr H5Cpp.h libhdf5-dev
  need_hdr CGAL/version.h libcgal-dev
  need_hdr readline/readline.h libreadline-dev
  if compgen -G "/usr/include/vtk-*/vtkVersion.h" >/dev/null || compgen -G "/usr/local/include/vtk-*/vtkVersion.h" >/dev/null; then ok "header vtkVersion.h"; else miss "header 'vtk-*/vtkVersion.h' (apt: libvtk9-dev)"; fi
  need_cmd klayout "apt: klayout; headless KLayout is a system prerequisite, not built by the runner"
else
  # --- PDK resolution: same order as run_extraction.sh -----------------------
  if [[ -n "${IHP_PDK_ROOT:-}" ]]; then PDK="${IHP_PDK_ROOT}"
  elif [[ -n "${PDK_ROOT:-}" && -d "${PDK_ROOT}/ihp-sg13g2" ]]; then PDK="${PDK_ROOT}/ihp-sg13g2"
  elif [[ -d "$HOME/share/pdk/ihp-sg13g2" ]]; then PDK="$HOME/share/pdk/ihp-sg13g2"
  else PDK=""; fi
  if [[ -n "${PDK}" && -d "${PDK}/libs.tech/klayout/python" ]]; then ok "IHP PDK tree ${PDK}"
  else miss "IHP-Open-PDK tree (IHP_PDK_ROOT='${IHP_PDK_ROOT:-}' resolved to '${PDK}'; need <root>/libs.tech/klayout/python)"; fi

  need_cmd openEMS "export PATH to include <prefix>/openems/bin, or source <prefix>/activate.sh"
  need_cmd ngspice
  need_cmd klayout
  need_cmd git
  need_cmd python3

  OPENEMS_PYTHON="${OPENEMS_PYTHON:-$HOME/opt/openEMS/venv/bin/python}"
  FIT_PYTHON="${FIT_PYTHON:-python3}"
  if out="$("${OPENEMS_PYTHON}" -c 'import openEMS, CSXCAD, gds2openEMS; from gds2openEMS import gds_reader, simulation_setup, stackup_reader, utilities; from openEMS import openEMS as _o; import numpy, h5py' 2>&1)"; then ok "OPENEMS_PYTHON=${OPENEMS_PYTHON} imports openEMS, CSXCAD, gds2openEMS (+ the submodules run_openems.py uses)"
  else miss "OPENEMS_PYTHON='${OPENEMS_PYTHON}' cannot import openEMS, CSXCAD, gds2openEMS: $(printf '%s' "${out}" | tail -1)"; fi
  # run_extraction.sh also runs `python3 -I -c 'import CSXCAD'` (isolated mode ignores PYTHONPATH),
  # so the python3 first on PATH must itself be the openEMS venv interpreter.
  if out="$(python3 -I -c 'import CSXCAD' 2>&1)"; then ok "python3 -I (PATH) imports CSXCAD"
  else miss "python3 -I -c 'import CSXCAD' on PATH python3: $(printf '%s' "${out}" | tail -1) (activate the runner prefix so its venv python3 is first on PATH)"; fi
  if out="$("${FIT_PYTHON}" -c 'import numpy, scipy' 2>&1)"; then ok "FIT_PYTHON=${FIT_PYTHON} imports numpy, scipy"
  else miss "FIT_PYTHON='${FIT_PYTHON}' cannot import numpy, scipy: $(printf '%s' "${out}" | tail -1)"; fi
  if command -v klayout >/dev/null 2>&1; then
    kv="$(klayout -v 2>&1 | head -1)"; ok "klayout version: ${kv}"
  fi
  if command -v openEMS >/dev/null 2>&1; then
    ok "openEMS version: $(openEMS --version 2>&1 | grep -i 'version' | head -1 | sed 's/^[ |]*//')"
  fi
fi

echo
if (( ${#missing[@]} )); then
  echo "PROBE FAILED (${MODE}): ${#missing[@]} missing prerequisite(s):" >&2
  printf '  - %s\n' "${missing[@]}" >&2
  exit 1
fi
echo "PROBE OK (${MODE})"
