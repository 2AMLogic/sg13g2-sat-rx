#!/usr/bin/env bash
# Export the SPICE netlist from the committed xschem sources (T1 item 1:
# "the netlist derived from them, regenerated on design change").
#
#   design/export_netlist.sh            # rewrite design/netlist/lna_stage1.spice
#   design/export_netlist.sh --check    # fail if the committed netlist is stale
#
# The xschem invocation is owned by `klt netlist --block` (headless, bounded,
# real exit status); this wrapper only normalizes what xschem writes so the
# committed file is the same on every checkout: xschem's `** sch_path:` line
# embeds the ABSOLUTE path of the schematic, which makes `klt netlist --check`
# report "drifted" from any other checkout location. That tool gap is filed
# upstream; until then this wrapper rewrites the line to the repo-relative path.
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
    -o "$tmp/raw.spice" --rcfile "$rc" --format json >"$tmp/klt.json" ) \
  || { cat "$tmp/klt.json" >&2; exit 1; }
ver="$(xschem --version 2>/dev/null | head -1 | tr -d '\r')"
klt_ver="$(klt --version | head -1)"
src_hash="$(cat "$here/lna_stage1.sch" "$here/lna_stage1.sym" | sha256sum | cut -d' ' -f1)"
{
  echo "* lna_stage1 subcircuit, exported by xschem from design/lna_stage1.sch via 'klt netlist --block'"
  echo "* tools: $ver; $klt_ver; sources sha256 (lna_stage1.sch then lna_stage1.sym concatenated): $src_hash"
  echo "* DERIVED FILE: regenerate with design/export_netlist.sh, never edit by hand."
  echo "* Matching elements (Cshunt, Lin, Lfeed, Cm) are IDEAL lossless L/C: no PDK inductor model exists."
  sed -e 's#^\*\* sch_path: .*#** sch_path: design/lna_stage1.sch#' "$tmp/raw.spice" | sed -e '/^$/d'
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
