#!/usr/bin/env bash
# Run the klt layout check chain over the LNA stage-1 device-group study and
# write every record plus exit-codes.txt into runs/<klt version>/ (issue #198).
#
# NON-CLAIMING: these records describe lna_stage1_devices.gds, which is not the
# LNA stage-1 layout. See README.md.
#
# Every run is a single layout and a single corner, so all of it stays LOCAL --
# this is not a klt sim grid and must not be expressed as one. The host klt is
# never used: pass --klt pointing at a throwaway environment holding the pin in
# layout/toolchain.json (klt_install), per this worker's tooling rules.
#
#   uv venv /tmp/klt-pin
#   uv pip install --python /tmp/klt-pin/bin/python "klayout-tools==0.8.0"
#   layout/lna_stage1/run_checks.sh --klt /tmp/klt-pin/bin/klt
#
# Re-running overwrites only the directory for that klt version. Records under
# another version's directory are append-only evidence and are never touched.

set -euo pipefail

KLT=""
OUT_ROOT=""
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GDS="lna_stage1_devices.gds"
SPEC="erc-supply-spec.json"
REFERENCE="reference-devices.spice"

usage() {
  cat >&2 <<'EOF'
usage: run_checks.sh --klt PATH [--out DIR]

  --klt PATH   klt executable from an environment holding the pinned release
               (layout/toolchain.json -> klt_install). Required: defaulting to
               the host tool would silently record a different build.
  --out DIR    output directory (default: runs/<the klt --version string>)
EOF
  exit 2
}

while [ $# -gt 0 ]; do
  case "$1" in
    --klt) KLT="${2:?--klt needs a path}"; shift 2 ;;
    --out) OUT_ROOT="${2:?--out needs a path}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown argument: $1" >&2; usage ;;
  esac
done
[ -n "$KLT" ] || usage
[ -x "$KLT" ] || { echo "error: not executable: $KLT" >&2; exit 1; }
# klt writes the path it is given into each record's `file` field, so every
# input is passed RELATIVE from this directory -- an absolute path would commit
# a host path into the evidence (`klt env-provenance lint-envelope` flags it).
cd "$HERE"
[ -f "$GDS" ] || { echo "error: no layout at $HERE/$GDS -- run generate.py first" >&2; exit 1; }
[ -f "$SPEC" ] || { echo "error: no ERC spec at $HERE/$SPEC" >&2; exit 1; }

# Fail loudly if the install is missing a command this chain needs, naming it
# and the fix -- never skip a check silently (layout/toolchain.json's own
# convention, implemented once in layout/toolchain_pin.py).
python3 "$HERE/../toolchain_pin.py" --check --klt "$KLT" --extra erc >/dev/null

KLT_VERSION="$("$KLT" --version | awk '{print $2}')"
OUT="${OUT_ROOT:-runs/klt-$KLT_VERSION}"
mkdir -p "$OUT"
: >"$OUT/exit-codes.txt"

# Record each command's exit status beside its record, so a reader can check
# the two agree rather than trusting the JSON alone.
run() {
  local name="$1"; shift
  local rc=0
  "$@" >"$OUT/$name.json" 2>"$OUT/$name.stderr" || rc=$?
  echo "$name $rc" >>"$OUT/exit-codes.txt"
  # klt prints the engine-version disclosure warning to stderr on drc/lvs at
  # this pin; keep it only when it carries something.
  if [ ! -s "$OUT/$name.stderr" ]; then rm -f "$OUT/$name.stderr"; fi
  printf '  %-28s exit %s\n' "$name" "$rc"
}

echo "klt $KLT_VERSION -> $OUT"

# 1. DRC. The verdict is `clean` only inside the deck's own scope; the claim
#    must quote coverage.{layers_in_stream_without_rules,rules_skipped,deck_scope}.
run drc "$KLT" drc "$GDS" --deck sg13g2 --format json

# 2. Extraction, for the record of which devices the curated deck recognises
#    in this stream (the HBT is known not to be one -- see README.md).
run extract "$KLT" extract "$GDS" --deck sg13g2 --format json \
  -o "$OUT/extracted.spice"

# 3. ERC supply half -- item 11's own artifact. --findings-only: this study
#    draws no gate-role geometry (no MOS, no poly resistor), so the antenna
#    half has nothing to accumulate; the supply/connectivity findings are
#    identical to a full run. Gate on erc_status, not status.
run erc "$KLT" erc "$GDS" "$SPEC" --findings-only --format json

# 4. Guard-ring continuity, on both layers the ring is drawn on.
run ringcheck_activ "$KLT" ring-check "$GDS" --layers '[[1,0]]' --ignore-enclosed --format json
run ringcheck_psd "$KLT" ring-check "$GDS" --layers '[[14,0]]' --ignore-enclosed --format json
run ringcheck_m1 "$KLT" ring-check "$GDS" --layers '[[8,0]]' --ignore-enclosed --format json

# 5. Area/density rows.
run economy "$KLT" economy "$GDS" --format json

# 6. LVS against a reference holding only what this stream draws. Expected to
#    mismatch: the curated deck recognises no bipolar device (G1, declined
#    upstream by ruling -- see layout/probe-readiness/README.md). Recorded so
#    the failure is the measured one rather than an assumed one.
if [ -f "$REFERENCE" ]; then
  # Paths inside a request document resolve against the request's own
  # directory, so they are written relative to $OUT.
  cat >"$OUT/lvs-devices.request.json" <<JSON
{
  "engine": "klayout",
  "layout": {"deck": "sg13g2", "file": "../../$GDS", "top": "lna_stage1_devices"},
  "reference": {"netlist": "../../$REFERENCE", "form": "subckt-call", "deck": "sg13g2"}
}
JSON
  run lvs-devices "$KLT" lvs "$OUT/lvs-devices.request.json" --format json
fi

echo
echo "exit codes:"
sed 's/^/  /' "$OUT/exit-codes.txt"
echo
echo "host-path hygiene:"
"$KLT" env-provenance lint-envelope "$OUT"/*.json || true
