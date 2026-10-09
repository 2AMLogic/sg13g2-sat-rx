#!/usr/bin/env bash
#
# sim/characterize.sh -- the one-command entry point for this repo's benches,
# built on the sim/harness/ generic core (see harness/README.md):
#
#   sim/lna-sparam-nf, sim/mixer-conversion-iip3
#       harness-native benches: each mode maps directly to an existing
#       `python3 -m harness.cli` subcommand, run once per experiment, with the
#       HBT corner set (sim/harness/corners.py's SG13G2 extension) named
#       explicitly since it is not this core's global default.
#   sim/hbt-kaband-characterization
#       a bench-local driver (hbt-kaband-characterization/run.py) on top of
#       the same harness pieces: it sweeps Nx x VCE x VBE INSIDE every PVT
#       point, which harness.cli's scalar-measure interface cannot express
#       (see that bench's README.md).
#
#   sim/characterize.sh smoke
#       The hbt_typ process corner only, writing NO evidence: for the two
#       harness-native benches that is hbt_typ x 3 temperatures x 3 supplies
#       (9 small points each -- harness.cli has no temperature/supply subset
#       flag); for the Ka-band bench one PVT point (hbt_typ / 27 C / nominal
#       supply) on its reduced bias sweep. Seconds, not minutes -- proof that
#       the whole command surface runs from a clean checkout AND produces its
#       measurements (see "smoke failure semantics" below).
#
#   sim/characterize.sh characterize
#       The full PVT campaign behind every measurement: hbt_typ/hbt_bcs/
#       hbt_wcs x (-40, 27, 125) C x (2.25, 2.50, 2.75) V = 27 points per
#       bench. Mints a new, dated, append-only record per bench under
#       sim/<experiment>/records/ -- a genuinely new record, never an
#       overwrite of one already committed. The Ka-band bench submits its
#       grid as `klt sim` requests (backend from $KABAND_BACKEND, default
#       "batch"; see its README.md "Running the full grid").
#
#   sim/characterize.sh selftest
#       The negative controls: `harness.cli selftest` for the two
#       harness-native benches (see sim/harness/corners.py's sabotage()
#       docstring), and run.py selftest for the Ka-band bench (source-noise
#       normalization probe, process sensitivity, sabotage collapse, and a
#       deliberately invalid deck that must be rejected) on its REDUCED bias
#       sweep.
#
# The two harness-native benches are PLACEHOLDER circuits (see each tb.json's
# "claim" field); the Ka-band bench is DEVICE-LEVEL evidence (a bare
# transistor, not a matched amplifier). No mode's PASS status should be read
# as "the target spec (spec/target-spec.md) is met".
#
# Smoke failure semantics: a harness-native smoke run is a single corner, so
# every tb.json min_spread_pct_by_axis check is structurally unverifiable and
# `harness.cli run` exits non-zero BY CONSTRUCTION. That structural exit is
# reported but not counted. What IS counted: any smoke whose simulation did
# not complete ("<n>/<m> points ok" with n != m, or no such line at all), and
# any non-zero exit of the Ka-band bench's smoke (which has no structural
# exemption: it exits non-zero only when a measurement is missing or a check
# fails).
#
# Exit status: 0 if every campaign that ran passed; otherwise the number of
# failing campaigns.

set -uo pipefail

SIM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SIM_DIR}" || exit 1

MODE="${1:-}"
HARNESS_EXPERIMENTS=(lna-sparam-nf mixer-conversion-iip3)
KABAND=hbt-kaband-characterization
TOTAL=$(( ${#HARNESS_EXPERIMENTS[@]} + 1 ))

case "${MODE}" in
  smoke|characterize|selftest) ;;
  *)
    echo "usage: $0 {smoke|characterize|selftest}" >&2
    exit 64
    ;;
esac

# Integrity gate: the installed IHP models must be the pinned artifact
# (sim/pdk-artifact.json) BEFORE any simulator process is launched. A missing
# PDK/model or a hash mismatch aborts here (exit 2), never a skip. Set
# SG13G2_REQUIRE_NGSPICE=1 (hosted CI does) to also fail on a missing or
# non-tested-major ngspice.
VERIFY_ARGS=()
[ "${SG13G2_REQUIRE_NGSPICE:-0}" = "1" ] && VERIFY_ARGS+=(--require-ngspice)
if ! python3 -m harness.cli verify-pdk "${VERIFY_ARGS[@]}"; then
  echo "sim/characterize.sh ${MODE}: refusing to simulate -- IHP model artifact not verified" >&2
  exit 2
fi

FAILURES=0

for exp in "${HARNESS_EXPERIMENTS[@]}"; do
  echo "=== ${exp}: ${MODE} ==="
  case "${MODE}" in
    smoke)
      out="$(python3 -m harness.cli run "${exp}" --corners hbt_typ --no-write 2>&1)"
      status=$?
      printf '%s\n' "${out}"
      counts="$(printf '%s\n' "${out}" | sed -n 's/^\([0-9]*\)\/\([0-9]*\) points ok$/\1 \2/p' | tail -1)"
      if [ -z "${counts}" ]; then
        echo "--- ${exp}: smoke FAILED (exit ${status}): the run never reported a point count -- the harness or simulator did not run ---" >&2
        FAILURES=$((FAILURES + 1))
      elif [ "${counts% *}" != "${counts#* }" ]; then
        echo "--- ${exp}: smoke FAILED: only ${counts% *}/${counts#* } points simulated (simulator/measurement failure, not a structural check) ---" >&2
        FAILURES=$((FAILURES + 1))
      elif [ "${status}" -ne 0 ]; then
        echo "--- ${exp}: smoke exited ${status} with every point simulated (expected -- single-corner sensitivity checks are structurally unverifiable). Not counted as a failure. ---"
      fi
      continue
      ;;
    characterize)
      python3 -m harness.cli run "${exp}" --corners hbt \
        --claim "sim/characterize.sh characterize -- full HBT PVT campaign. PLACEHOLDER circuit; see tb.json claim for the spec-compliance disclaimer."
      ;;
    selftest)
      python3 -m harness.cli selftest "${exp}" --corners hbt
      ;;
  esac
  status=$?
  if [ "${status}" -ne 0 ]; then
    echo "--- ${exp}: ${MODE} FAILED (exit ${status}) ---" >&2
    FAILURES=$((FAILURES + 1))
  fi
done

echo "=== ${KABAND}: ${MODE} ==="
case "${MODE}" in
  smoke)        python3 "${KABAND}/run.py" smoke ;;
  characterize) python3 "${KABAND}/run.py" characterize --backend "${KABAND_BACKEND:-batch}" ;;
  selftest)     python3 "${KABAND}/run.py" selftest ;;
esac
status=$?
if [ "${status}" -ne 0 ]; then
  echo "--- ${KABAND}: ${MODE} FAILED (exit ${status}) ---" >&2
  FAILURES=$((FAILURES + 1))
fi

echo
if [ "${FAILURES}" -eq 0 ]; then
  echo "sim/characterize.sh ${MODE}: all ${TOTAL} bench(es) OK"
else
  echo "sim/characterize.sh ${MODE}: ${FAILURES}/${TOTAL} bench(es) FAILED" >&2
fi
exit "${FAILURES}"
