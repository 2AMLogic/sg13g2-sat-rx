#!/usr/bin/env bash
#
# sim/characterize.sh -- the one-command entry point for this repo's two
# benches (sim/lna-sparam-nf, sim/mixer-conversion-iip3), built on the
# sim/harness/ generic core (see harness/README.md). It is a thin wrapper
# over `python3 -m harness.cli`, not new harness machinery -- each mode below
# maps directly to an existing `harness.cli` subcommand, run once per
# experiment, with the HBT corner set (sim/harness/corners.py's SG13G2
# extension) named explicitly since it is not this core's global default.
#
#   sim/characterize.sh smoke
#       One nominal PVT point (hbt_typ / 27 C / nominal supply) per bench,
#       writing NO evidence (`--no-write`). Seconds, not minutes -- proof
#       that the whole command surface runs from a clean checkout.
#
#   sim/characterize.sh characterize
#       The full PVT campaign behind every measurement: hbt_typ/hbt_bcs/
#       hbt_wcs x (-40, 27, 125) C x (2.25, 2.50, 2.75) V = 27 points per
#       bench. Mints a new, dated, append-only record per bench under
#       sim/<experiment>/records/ (report.py's format) -- a genuinely new
#       record, never an overwrite of one already committed.
#
#   sim/characterize.sh selftest
#       Runs `harness.cli selftest` (the negative control -- see
#       sim/harness/corners.py's sabotage() docstring) for both benches,
#       explicitly against their own declared "hbt" corner set.
#
# Both benches are PLACEHOLDER circuits (see each tb.json's "claim" field) --
# this script characterizes the harness/methodology, not spec compliance;
# neither "characterize" mode's PASS status should be read as "the DRAFT
# target spec (README.md) is met".
#
# Exit status: 0 if every campaign that ran exited 0; otherwise the number of
# failing campaigns (harness.cli run/selftest exit non-zero on a spec-check
# failure or an incomplete grid -- see cli.py's cmd_run/cmd_selftest).

set -uo pipefail

SIM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SIM_DIR}"

MODE="${1:-}"
EXPERIMENTS=(lna-sparam-nf mixer-conversion-iip3)

case "${MODE}" in
  smoke|characterize|selftest) ;;
  *)
    echo "usage: $0 {smoke|characterize|selftest}" >&2
    exit 64
    ;;
esac

FAILURES=0

for exp in "${EXPERIMENTS[@]}"; do
  echo "=== ${exp}: ${MODE} ==="
  case "${MODE}" in
    smoke)
      # Single corner (hbt_typ only) by design, for speed -- but every
      # tb.json check in this repo is a min_spread_pct_by_axis PVT-sensitivity
      # floor (report.py's evaluate_checks: fewer than 2 process levels makes
      # that axis "unverifiable", a hard FAIL, not a skip -- cli.py exposes no
      # --allow-unswept-axes flag to relax this). A one-corner smoke run is
      # therefore GUARANTEED to fail those checks by construction; smoke's own
      # job is only "does the command surface run at all", so its exit status
      # is reported but never counted against this script's overall result --
      # only "characterize" (the real hbt x T x V grid, checks meaningful) and
      # "selftest" gate FAILURES.
      python3 -m harness.cli run "${exp}" --corners hbt_typ --no-write
      status=$?
      if [ "${status}" -ne 0 ]; then
        echo "--- ${exp}: smoke exited ${status} (expected -- single-corner checks are structurally unverifiable; see comment above). Not counted as a failure. ---"
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

echo
if [ "${FAILURES}" -eq 0 ]; then
  echo "sim/characterize.sh ${MODE}: all ${#EXPERIMENTS[@]} bench(es) OK"
else
  echo "sim/characterize.sh ${MODE}: ${FAILURES}/${#EXPERIMENTS[@]} bench(es) FAILED" >&2
fi
exit "${FAILURES}"
