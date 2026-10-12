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
#       harness-native benches that is hbt_typ x the smoke PVT axes, run
#       sequentially with --backend local (hosted CI has no batch
#       credentials) -- lna-sparam-nf: 3 temperatures x 3 supplies = 9 small
#       points; mixer-conversion-iip3: -40/27 C x 3 supplies = 6 points,
#       because its static two-tone fit window has no valid 1:3-slope region
#       at the 125 C corners (the record's measured finding: hot compression
#       inside the window; the slope gates fail there by design and no IIP3
#       is published -- record 20261012-061538-2bdb5be, follow-up #181) and a
#       smoke run cannot express per-corner expected failures; for the
#       Ka-band bench one PVT point (hbt_typ /
#       27 C / nominal supply) on its reduced bias sweep. Seconds, not minutes -- proof that
#       the whole command surface runs from a clean checkout AND produces its
#       measurements (see "smoke failure semantics" below).
#
#   sim/characterize.sh characterize
#       The full PVT campaign behind every measurement: hbt_typ/hbt_bcs/
#       hbt_wcs x (-40, 27, 125) C x (2.25, 2.50, 2.75) V = 27 points per
#       bench. Mints a new, dated, append-only record per bench under
#       sim/<experiment>/records/ -- a genuinely new record, never an
#       overwrite of one already committed. The two harness-native benches
#       submit their 27 points as `klt sim` requests through
#       `harness.cli run --backend` (backend from $HARNESS_BACKEND, default
#       "batch"; "local" is a sequential ngspice loop on this host --
#       workstation only). The Ka-band bench likewise submits its grid as
#       `klt sim` requests (backend from $KABAND_BACKEND, default "batch";
#       see its README.md "Running the full grid"). A failed submit fails the
#       campaign; it never falls back to a local grid.
#
#   sim/characterize.sh selftest
#       The negative controls: `harness.cli selftest` for the two
#       harness-native benches (see sim/harness/corners.py's sabotage()
#       docstring), and run.py selftest for the Ka-band bench (source-noise
#       normalization probe, process sensitivity, sabotage collapse, and a
#       deliberately invalid deck that must be rejected) on its REDUCED bias
#       sweep. `harness.cli selftest` is local-only (a sabotaged corner set
#       has no klt sim form), sequential by default.
#
# lna-sparam-nf is a schematic-backed first-stage feasibility circuit with IDEAL
# lossless matching; mixer-conversion-iip3 is a PLACEHOLDER circuit. Each
# bench's own tb.json "claim" is what a new record carries (characterize passes
# no --claim of its own). The Ka-band bench is DEVICE-LEVEL evidence (a bare
# transistor, not a matched amplifier). No mode's PASS status should be read
# as "the target spec (spec/target-spec.md) is met".
#
# Smoke failure semantics: a harness-native smoke run is a single process
# corner, so the tb.json min_spread_pct_by_axis check on the never-swept
# process axis is structurally unverifiable. `harness.cli run --no-write
# --smoke-subset` skips exactly that (the CLI rejects --smoke-subset on an
# evidence-writing run). Every other failure propagates through the harness
# exit status; this wrapper does not interpret the output. The Ka-band bench
# smoke likewise exits non-zero on a missing measurement or failed check.
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
      # --smoke-subset (requires --no-write) skips ONLY the "axis never swept"
      # sensitivity check (the single process corner). Every other failure --
      # violated bound, stuck swept temperature/supply axis, missing
      # measurement, simulator error -- is the harness's own non-zero exit.
      # mixer-conversion-iip3 drops the 125 C smoke points (--temperatures is
      # legal under --no-write): its static fit window has no valid 1:3
      # region at those corners, the slope gates fail there BY DESIGN (record
      # 20261012-061538-2bdb5be; per-corner-adaptive window is follow-up
      # #181), and a smoke run has no per-corner expected-failure mechanism.
      # This narrows which corners the smoke exercises; it loosens no bound --
      # the full grid still runs every corner in `characterize` mode, where a
      # gate failure refuses the record.
      SMOKE_TEMPS=()
      [ "${exp}" = "mixer-conversion-iip3" ] && SMOKE_TEMPS=(--temperatures=-40.0,27.0)
      python3 -m harness.cli run "${exp}" --corners hbt_typ "${SMOKE_TEMPS[@]}" --no-write --smoke-subset --backend local
      status=$?
      if [ "${status}" -ne 0 ]; then
        echo "--- ${exp}: smoke FAILED (exit ${status}) ---" >&2
        FAILURES=$((FAILURES + 1))
      fi
      continue
      ;;
    characterize)
      # No --claim: harness.cli records the bench own tb.json claim (LNA:
      # ideal-matching feasibility; mixer: PLACEHOLDER disclaimer).
      python3 -m harness.cli run "${exp}" --corners hbt --backend "${HARNESS_BACKEND:-batch}"
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
