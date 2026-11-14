#!/usr/bin/env bash
# Export the SPICE netlist from the committed xschem sources (T1 item 1:
# "the netlist derived from them, regenerated on design change").
#
#   design/export_netlist.sh            # rewrite design/netlist/lna_stage1.spice
#   design/export_netlist.sh --check    # fail if the committed netlist is stale
#
# The xschem invocation is owned by `klt netlist --block` (headless, bounded,
# real exit status). Two klt flags keep the committed file byte-reproducible
# from any checkout, so this wrapper only prepends the header comments:
#   --relative-paths        xschem's `** sch_path:` / `** sym_path:` lines
#                           carry the ABSOLUTE path of the schematic, which
#                           makes a regeneration from another checkout look
#                           "drifted"; klt writes them git-toplevel-relative
#                           instead (klayout-tools#5046).
#   --no-provenance-header  omits klt's own `** klt-netlist-inputs:` line
#                           (klayout-tools#5085). It is tool provenance, not
#                           circuit content, so including it would (a) make
#                           every committed netlist look stale after a klt
#                           version roll and (b) record a `pdk_variant`
#                           resolved by first-match-wins over $PDK_ROOT, which
#                           on a host with several IHP PDKs installed is not
#                           the PDK this run netlisted against. This netlist is
#                           hash-pinned by the signoff inventory and by several
#                           study declarations; a wrong fact in it is worse
#                           than no fact.
#
# Needs: klt, xschem, and an IHP-Open-PDK checkout for the sg13g2_pr symbol
# library (default $HOME/share/pdk/ihp-sg13g2, override with SG13G2_PDK).
# No simulator is run here.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/.." && pwd)"
pdk="${SG13G2_PDK:-$HOME/share/pdk/ihp-sg13g2}"
rc="$pdk/libs.tech/xschem/xschemrc"
[ -f "$rc" ] || { echo "export_netlist: no xschemrc at $rc (set SG13G2_PDK)" >&2; exit 2; }
check=0; [ "${1:-}" = "--check" ] && check=1
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
( cd "$root" && PDK_ROOT="$(dirname "$pdk")" klt netlist --block design/lna_stage1.sch \
    -o "$tmp/raw.spice" --rcfile "$rc" --relative-paths --no-provenance-header \
    --format json >"$tmp/klt.json" ) \
  || { cat "$tmp/klt.json" >&2; exit 1; }
ver="$(xschem --version 2>/dev/null | head -1 | tr -d '\r')"
klt_ver="$(klt --version | head -1)"
src_hash="$(cat "$here/lna_stage1.sch" "$here/lna_stage1.sym" | sha256sum | cut -d' ' -f1)"
{
  echo "* lna_stage1 subcircuit, exported by xschem from design/lna_stage1.sch via 'klt netlist --block'"
  echo "* tools: $ver; $klt_ver; sources sha256 (lna_stage1.sch then lna_stage1.sym concatenated): $src_hash"
  echo "* DERIVED FILE: regenerate with design/export_netlist.sh, never edit by hand."
  echo "* Matching elements (Cshunt, Lin, Lfeed, Cm) and the emitter-degeneration inductor Le1 are IDEAL lossless L/C: no PDK inductor model exists."
  sed -e '/^$/d' "$tmp/raw.spice"
} > "$tmp/lna.spice"
dst="$here/netlist/lna_stage1.spice"
if [ "$check" = 1 ]; then
  # the tool-version words in the header are provenance, not content: compare the sources hash and the body
  strip() { grep -v '^\* tools:' "$1"; }
  diff -u <(strip "$dst") <(strip "$tmp/lna.spice") >/dev/null \
    || { echo "export_netlist: design/netlist/lna_stage1.spice is stale (or sources hash differs)" >&2; exit 1; }
  grep -q "$src_hash" "$dst" || { echo "export_netlist: netlist header names different sources" >&2; exit 1; }
  echo "export_netlist: committed netlist matches the xschem sources"
else
  mkdir -p "$here/netlist"
  cp "$tmp/lna.spice" "$dst"
  echo "export_netlist: wrote design/netlist/lna_stage1.spice"
fi
