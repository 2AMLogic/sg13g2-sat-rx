#!/usr/bin/env bash
# Export the SPICE netlist from the committed xschem sources (T1 item 1:
# "the netlist derived from them, regenerated on design change").
#
#   design/export_netlist.sh            # rewrite design/netlist/*.spice
#   design/export_netlist.sh --check    # fail if committed netlists differ
#
# Needs: xschem (>= 3.4) and an IHP-Open-PDK checkout for the sg13g2_pr
# symbol library (default $HOME/share/pdk/ihp-sg13g2, override with
# SG13G2_PDK). No simulator is run here.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pdk="${SG13G2_PDK:-$HOME/share/pdk/ihp-sg13g2}"
rc="$pdk/libs.tech/xschem/xschemrc"
[ -f "$rc" ] || { echo "export_netlist: no xschemrc at $rc (set SG13G2_PDK)" >&2; exit 2; }
check=0; [ "${1:-}" = "--check" ] && check=1
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/out"
( cd "$here" && PDK_ROOT="$(dirname "$pdk")" xschem -n -q --no_x --rcfile "$rc" -o "$tmp/out" tb_lna_stage1.sch >"$tmp/xschem.log" 2>&1 ) \
  || { cat "$tmp/xschem.log" >&2; exit 1; }
if grep -q '^Error' "$tmp/xschem.log"; then cat "$tmp/xschem.log" >&2; exit 1; fi
raw="$tmp/out/tb_lna_stage1.spice"
ver="$(xschem --version 2>/dev/null | head -1 | tr -d '\r')"
src_hash="$(cat "$here/lna_stage1.sch" "$here/lna_stage1.sym" "$here/tb_lna_stage1.sch" | sha256sum | cut -d' ' -f1)"
# machine-local paths out of the committed text
clean() { sed -e "s#$here/##g" -e "s#$tmp/##g" -e '/^\*\* sym_path:/d' -e '/^$/d'; }
{
  echo "* tb_lna_stage1 netlist, exported by xschem from design/{lna_stage1.sch,lna_stage1.sym,tb_lna_stage1.sch}"
  echo "* tool: $ver; sources sha256 (concatenated in that order): $src_hash"
  echo "* DERIVED FILE: regenerate with design/export_netlist.sh, never edit by hand."
  clean < "$raw"
} > "$tmp/tb.spice"
{
  echo "* lna_stage1 subcircuit, exported by xschem from design/lna_stage1.sch"
  echo "* tool: $ver; sources sha256 (lna_stage1.sch, lna_stage1.sym, tb_lna_stage1.sch): $src_hash"
  echo "* DERIVED FILE: regenerate with design/export_netlist.sh, never edit by hand."
  echo "* Matching elements (Cshunt, Lin, Lfeed, Cm) are IDEAL lossless L/C: no PDK inductor model exists."
  awk '/^\.subckt lna_stage1/{p=1} p{print} /^\.ends/{if(p){exit}}' "$tmp/tb.spice" | grep -v '^\*\.\(ipin\|opin\|iopin\)'
} > "$tmp/lna.spice"
if [ "$check" = 1 ]; then
  for f in tb_lna_stage1 lna_stage1; do
    src="$tmp/lna.spice"; [ "$f" = tb_lna_stage1 ] && src="$tmp/tb.spice"
    diff -u "$here/netlist/$f.spice" "$src" >/dev/null || { echo "export_netlist: design/netlist/$f.spice is stale" >&2; exit 1; }
  done
  echo "export_netlist: committed netlists match the xschem sources"
else
  mkdir -p "$here/netlist"
  cp "$tmp/tb.spice" "$here/netlist/tb_lna_stage1.spice"
  cp "$tmp/lna.spice" "$here/netlist/lna_stage1.spice"
  echo "export_netlist: wrote design/netlist/{tb_lna_stage1,lna_stage1}.spice"
fi
