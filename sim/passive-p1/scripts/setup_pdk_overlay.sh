#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# setup_pdk_overlay.sh -- build a scratch libs.tech/klayout tree in which the
# IHP SG13G2 KLayout PCell library can actually be instantiated headlessly.
#
# WHY THIS EXISTS.  IHP-Open-PDK v0.3.0 ships two of the three things the PCell
# library needs as *git submodules*, and GitHub source tarballs never carry
# submodule contents, so in a tarball install both are empty directories:
#
#   libs.tech/klayout/python/pycell4klayout-api   (IHP-GmbH/pycell4klayout-api)
#   libs.tech/klayout/python/pypreprocessor       (IHP-GmbH/pypreprocessor)
#
# Without them `import sg13g2_pycell_lib` fails at `from cni.dlo import
# PCellWrapper`, and no SG13G2 PCell can be drawn from a script.  This is the
# same empty-submodule failure mode that blocked the openEMS route in #6 --
# see ../README.md.
#
# We do NOT mutate the shared PDK install.  We build a directory of symlinks to
# it with the two submodule directories replaced by real checkouts.
#
# Usage:  setup_pdk_overlay.sh <pdk-libs.tech-klayout-dir> <overlay-dir>
# Prints the resolved submodule revisions on stdout as JSON.

set -euo pipefail

PDK_KLAYOUT="${1:?usage: setup_pdk_overlay.sh <pdk libs.tech/klayout dir> <overlay dir>}"
OVERLAY="${2:?usage: setup_pdk_overlay.sh <pdk libs.tech/klayout dir> <overlay dir>}"

# Revisions pinned here so the geometry is reproducible.  They are the upstream
# HEADs at the time of extraction; IHP-Open-PDK v0.3.0's release tarball records
# no submodule SHAs of its own to pin against (that information lives only in
# the git repository's gitlinks, which the tarball drops).
PYCELL_API_REPO="https://github.com/IHP-GmbH/pycell4klayout-api.git"
PYCELL_API_REV="2ffdf79fe51a7c35b361cc854369b5d434c8d478"
PYPREPROC_REPO="https://github.com/IHP-GmbH/pypreprocessor.git"
PYPREPROC_REV="cf1ff9bad0fb5338cf1c5b990b2b816b1ea01a64"

CACHE="${EM_OVERLAY_CACHE:-${TMPDIR:-/tmp}/sg13g2-pycell-cache}"
mkdir -p "$CACHE"

fetch() {
  local dir="$1" repo="$2" rev="$3"
  if [ ! -d "$dir/.git" ]; then
    rm -rf "$dir"
    git clone --quiet "$repo" "$dir"
  fi
  git -C "$dir" fetch --quiet origin "$rev" 2>/dev/null || git -C "$dir" fetch --quiet origin
  git -C "$dir" checkout --quiet "$rev"
}

fetch "$CACHE/pycell4klayout-api" "$PYCELL_API_REPO" "$PYCELL_API_REV"
fetch "$CACHE/pypreprocessor" "$PYPREPROC_REPO" "$PYPREPROC_REV"

rm -rf "$OVERLAY"
mkdir -p "$OVERLAY/python"
for e in "$PDK_KLAYOUT"/*; do
  b="$(basename "$e")"
  [ "$b" = python ] && continue
  ln -s "$e" "$OVERLAY/$b"
done
for e in "$PDK_KLAYOUT"/python/*; do
  b="$(basename "$e")"
  case "$b" in
    pycell4klayout-api | pypreprocessor) continue ;;
  esac
  ln -s "$e" "$OVERLAY/python/$b"
done
# cni's PCellWrapper derives the "klayout root" as five directories above its own
# __file__ and rglob()s it for parameters.tcl, so the checkout MUST sit at the
# canonical in-PDK path or that rglob walks the whole filesystem.
cp -r "$CACHE/pycell4klayout-api" "$OVERLAY/python/pycell4klayout-api"
cp -r "$CACHE/pypreprocessor" "$OVERLAY/python/pypreprocessor"

cat <<EOF
{
  "pycell4klayout-api": {"repo": "$PYCELL_API_REPO", "rev": "$PYCELL_API_REV"},
  "pypreprocessor": {"repo": "$PYPREPROC_REPO", "rev": "$PYPREPROC_REV"},
  "overlay": "$OVERLAY"
}
EOF
