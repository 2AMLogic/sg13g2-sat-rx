#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Write / check ../INPUTS.json: pinned source commit + sha256 of every copied
or adapted input.

  hash_inputs.py --write [--source-repo PATH]   regenerate from the pinned commit
  hash_inputs.py --check                        verify files still match

`verbatim`  : byte-identical to the file at the pinned source commit
`original`  : the unmodified source file an adapted file derives from (kept
              under upstream/ for diffing)
`adapted`   : new file derived from an `original`; source_sha256 is the hash of
              that original
`new`       : written for this campaign, no sibling source
The source blob is read with `git show <commit>:<path>`, so a sibling checkout
at a different HEAD does not matter as long as the pinned object exists.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys

CAMPAIGN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMMIT = "ee69f8529df347b871f52067f6f054821ac75b32"
SRC = "sim/inductor-model/em-extraction/"
REPO = "2AMLogic/sg13g2-vco"

# local path -> (role, source path relative to SRC or None, derived-from original)
FILES = [
    ("gds/inductor_p1.gds", "verbatim", "gds/inductor_p1.gds"),
    ("gds/inductor_p1.json", "verbatim", "gds/inductor_p1.json"),
    ("stackup/SG13G2.xml", "verbatim", "stackup/SG13G2.xml"),
    ("scripts/emlib.py", "verbatim", "scripts/emlib.py"),
    ("scripts/gen_geometry.py", "verbatim", "scripts/gen_geometry.py"),
    ("scripts/run_openems.py", "verbatim", "scripts/run_openems.py"),
    ("scripts/setup_pdk_overlay.sh", "verbatim", "scripts/setup_pdk_overlay.sh"),
    ("upstream/run_extraction.sh", "original", "run_extraction.sh"),
    ("upstream/postprocess.py", "original", "scripts/postprocess.py"),
    ("upstream/fit_lumped.py", "original", "scripts/fit_lumped.py"),
    ("upstream/compare_analytic.py", "original", "scripts/compare_analytic.py"),
    ("run_extraction.sh", "adapted", "run_extraction.sh"),
    ("scripts/postprocess_p1.py", "adapted", "scripts/postprocess.py"),
    ("scripts/fit_p1.py", "adapted", "scripts/fit_lumped.py"),
    ("scripts/compare_p1.py", "adapted", "scripts/compare_analytic.py"),
    ("scripts/p1chain.py", "new", None),
    ("scripts/limits.py", "new", None),
    ("scripts/make_record.py", "new", None),
    ("scripts/freeze_package.py", "new", None),
    ("scripts/reanalyze_frozen.py", "new", None),
    ("scripts/make_synthetic.py", "new", None),
    ("scripts/controls.py", "new", None),
    ("scripts/hash_inputs.py", "new", None),
    ("scripts/gds_xor.py", "new", None),
    ("fixtures/lossless_L_100pH.s2p", "new", None),
]


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


def source_sha(repo, rel):
    b = subprocess.run(["git", "-C", repo, "show", "%s:%s%s" % (COMMIT, SRC, rel)],
                       capture_output=True, check=True).stdout
    return hashlib.sha256(b).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--source-repo", default=os.path.expanduser("~/GitHub/sg13g2-vco"))
    args = ap.parse_args()
    man_path = os.path.join(CAMPAIGN, "INPUTS.json")
    if args.write:
        files = []
        for path, role, src in FILES:
            full = os.path.join(CAMPAIGN, path)
            if not os.path.isfile(full):
                print("skip (absent): %s" % path)
                continue
            files.append({"path": path, "role": role, "sha256": sha(full),
                          "source_path": (SRC + src) if src else None,
                          "source_sha256": source_sha(args.source_repo, src) if src else None})
        man = {"source_repo": REPO, "source_commit": COMMIT,
               "note": "sha256 over file bytes; `verbatim` must equal source_sha256", "files": files}
        with open(man_path, "w") as fh:
            json.dump(man, fh, indent=2)
            fh.write("\n")
        print("wrote %s (%d files)" % (man_path, len(files)))
        return 0
    man = json.load(open(man_path))
    bad = 0
    for e in man["files"]:
        h = sha(os.path.join(CAMPAIGN, e["path"]))
        ok = h == e["sha256"] and (e["role"] not in ("verbatim", "original") or h == e["source_sha256"])
        if not ok:
            bad += 1
            print("MISMATCH %s" % e["path"])
    print("%d files checked, %d mismatches" % (len(man["files"]), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
