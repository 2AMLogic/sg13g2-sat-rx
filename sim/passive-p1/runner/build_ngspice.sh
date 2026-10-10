#!/usr/bin/env bash
# Build the pinned ngspice into <prefix>/ngspice (called by bootstrap.sh).   Issue #46.
#   build_ngspice.sh <prefix> <jobs>
#
# autoconf refuses a source/prefix path containing whitespace, so the build and a first install
# happen in a throw-away staging directory under /tmp (removed on exit) and the installed tree is
# then relocated into <prefix>/ngspice:
#   * bin/ngspice is a small wrapper that sets SPICE_LIB_DIR and execs bin/ngspice.bin;
#   * scripts/spinit has the staging path rewritten to the final one.  spinit cannot quote a path, so when
#     <prefix> contains whitespace the code-model/OSDI `codemodel`/`osdi` lines are commented out
#     (plain R/L/C/diode/MOS/BJT netlists, which every passive-p1 control uses, are unaffected) and the
#     fact is printed.  Use a whitespace-free prefix to keep the code models.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${HERE}/LOCK.env"
PREFIX="${1:?prefix}"; JOBS="${2:?jobs}"
STAGE="$(mktemp -d /tmp/p1-ngspice.XXXXXX)"
trap 'rm -rf -- "${STAGE:?}"' EXIT
mkdir -p "${PREFIX}/dl"
curl -fsSL --retry 3 -o "${PREFIX}/dl/ngspice.tar.gz" "${NGSPICE_URL}"
echo "${NGSPICE_SHA256}  ${PREFIX}/dl/ngspice.tar.gz" | sha256sum -c -
mkdir -p "${STAGE}/src" "${STAGE}/build"
tar -xzf "${PREFIX}/dl/ngspice.tar.gz" -C "${STAGE}/src"
cd "${STAGE}/build"
# shellcheck disable=SC2086
"${STAGE}/src/ngspice-46/configure" --prefix="${STAGE}/inst" ${NGSPICE_CONFIGURE_FLAGS}
make -j"${JOBS}"
make install
rm -rf -- "${PREFIX:?}/ngspice"
cp -a "${STAGE}/inst" "${PREFIX}/ngspice"
SPINIT="${PREFIX}/ngspice/share/ngspice/scripts/spinit"
sed -i "s|${STAGE}/inst|${PREFIX}/ngspice|g" "${SPINIT}"
if [[ "${PREFIX}" =~ [[:space:]] ]]; then
  sed -i -E 's/^( *(codemodel|osdi) )/* disabled (prefix path contains whitespace): \1/' "${SPINIT}"
  echo "NOTE: prefix contains whitespace -> ngspice code models/OSDI disabled in spinit (plain devices unaffected)"
fi
mv "${PREFIX}/ngspice/bin/ngspice" "${PREFIX}/ngspice/bin/ngspice.bin"
cat > "${PREFIX}/ngspice/bin/ngspice" <<'WRAP'
#!/bin/sh
d="$(cd "$(dirname "$0")/.." && pwd)"
SPICE_LIB_DIR="$d/share/ngspice" exec "$d/bin/ngspice.bin" "$@"
WRAP
chmod +x "${PREFIX}/ngspice/bin/ngspice"
