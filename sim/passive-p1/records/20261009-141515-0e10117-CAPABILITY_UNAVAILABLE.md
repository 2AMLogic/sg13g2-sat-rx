# passive-p1 record 20261009-141515-0e10117-CAPABILITY_UNAVAILABLE

- **Status: CAPABILITY_UNAVAILABLE**
- Reason(s): openEMS not found on PATH. ./run_extraction.sh: line 86: /home/ubuntu/opt/openEMS/venv/bin/python: No such file or directory [system python3] ModuleNotFoundError: No module named 'CSXCAD'. 
- Claim scope: feasibility evidence for ONE geometry (p1). Not a passive-family choice, not matching-network sizing, not spec compliance. No qualified-model claim unless the status above is QUALIFIED, and then only for the exact geometry, the 17.7-21.2 GHz tested range and the nominal stackup point.
- Numerical digest (re-run comparison key): `d3fb8b9252e510f4b0b6df9c0e389cd64ac4e2bca96e6c82cfb008b2766fda72`

Stage note: the geometry stage ran before the failure. Regenerated PCell GDS sha256 172404c47a16c0bb3f71e38a9a6625dd150cf2e33ec271fc20145184cf24fbae vs pinned 674090e9e0f520f000d5b220460e3f3647c46dcb4f06e1b7236557d2d3beeceb (bytes differ by header content); per-layer XOR result: GEOMETRY_IDENTICAL (run_log/geometry_xor.txt). This confirms the pinned input only; it is not an EM result.

## Provenance

- Source method: `2AMLogic/sg13g2-vco` @ `ee69f8529df347b871f52067f6f054821ac75b32`, `sim/inductor-model/em-extraction` (pinned; inputs hashed in `../INPUTS.json`, reproduced below).
- This repo commit: `0e101173cd2348124b565ea24add62dd05bf49ea`
- Host: loom-worker-3 (Linux-7.0.0-1013-aws-x86_64-with-glibc2.39); python 3.12.3, numpy None, scipy None
- ngspice: ** ngspice-42 : Circuit level simulation program
- klayout: KLayout 0.28.16
- openEMS binary: absent; `import CSXCAD`: ModuleNotFoundError: No module named 'CSXCAD'
- PDK: `/home/ubuntu/share/pdk/ihp-sg13g2` (.fetched-version: 0.3.0)
- Stages requested: `geometry em convergence post fit compare`
- Commands: `EM_STAGES="geometry em convergence post fit compare" FIT_PYTHON=/tmp/p1venv/bin/python OPENEMS_PYTHON=/home/ubuntu/opt/openEMS/venv/bin/python sim/passive-p1/run_extraction.sh`

## Failed capability check

- Failed command/check: `command -v openEMS; /home/ubuntu/opt/openEMS/venv/bin/python -c 'import openEMS, CSXCAD, gds2openEMS'; python3 -I -c 'import CSXCAD'`
- Detail: openEMS not found on PATH. ./run_extraction.sh: line 86: /home/ubuntu/opt/openEMS/venv/bin/python: No such file or directory [system python3] ModuleNotFoundError: No module named 'CSXCAD'. 

No L, Q, SRF, convergence or fit number is reported in this record, and no number from any other source (including the sibling VCO's historical extraction) is substituted. Mesh convergence at 21.2 GHz, the fit, and the model qualification are therefore NOT established by this record.

## Limitations (stated beside the claims)

- p1 geometry only; fit/EM agreement holds only inside the tested band and for this exact geometry.
- Nominal stackup point only: metal thickness, dielectric and conductivity come from `stackup/SG13G2.xml` (hash in the input table). Process spread, temperature coefficients and Monte Carlo are UNSUPPORTED; no corner labels are inherited from the HBT corner set.
- Fit agreement is separate from solver convergence; neither is silicon validation.
- Transmission lines, MIM capacitors, other geometries and validated corners are follow-on work.

## Input hashes (`../INPUTS.json`)

| file | role | sha256 | manifest ok | verbatim==source |
|---|---|---|---|---|
| gds/inductor_p1.gds | verbatim | `674090e9e0f520f000d5b220460e3f3647c46dcb4f06e1b7236557d2d3beeceb` | True | True |
| gds/inductor_p1.json | verbatim | `91448ce5643ca9ad19062433e6a5316966dffb8597f826afaffca9f66e0c673c` | True | True |
| stackup/SG13G2.xml | verbatim | `e0a9762bd85e15b2b173d2bfb509a0e97568a5de53b149935a3ae6913682fea1` | True | True |
| scripts/emlib.py | verbatim | `8ff1307463a4586678837f7f8755beff88d05a60fc00f8c94df56584adea09fa` | True | True |
| scripts/gen_geometry.py | verbatim | `cdec40d59394c480a8ceb0f0a7b939c20b0534524f2d2f8e392d32f85d0e9ef3` | True | True |
| scripts/run_openems.py | verbatim | `e77e73a1922c6e4754780c5289688b1e0821295729cf2f6c37172209bdd0fc23` | True | True |
| scripts/setup_pdk_overlay.sh | verbatim | `f95e4637d3586a6623de26c8ecac4af370cf7f2e6491d931d1872328052ad272` | True | True |
| upstream/run_extraction.sh | original | `145ecee4554f21320f28d1a3b3f93955a6c396ec3f541fc669419c905fa3dd1c` | True | None |
| upstream/postprocess.py | original | `a18fc89c6ca5245c43304942913b6f403a9617bba95141d4ffe604afa3107fcf` | True | None |
| upstream/fit_lumped.py | original | `15dcdf64eda16a036259434d49fcf8945ea9bfde2d0dbc86c8534adbc60e9536` | True | None |
| upstream/compare_analytic.py | original | `568fe8c606069899bb8b00d9fd35430f32cef19ae5c10e7f9ef8aa3e5844e40c` | True | None |
| run_extraction.sh | adapted | `b6d4fb6a5ae95b3bce9a39b44226613da3cace9f28bcf02834be4cf7e817f4f0` | True | None |
| scripts/postprocess_p1.py | adapted | `a9fd38998f1044659418d42cfbc029bdde52231a8f43c076d3e664fd795e9e59` | True | None |
| scripts/fit_p1.py | adapted | `2cd0f45271a9d7e201369f84e47848329f919c51ab1d2cfd949af5e381e818c4` | True | None |
| scripts/compare_p1.py | adapted | `8ea81d5a97a379f0e1bffe039640085d5d24124baecd329cda823d24ab59d947` | True | None |
| scripts/p1chain.py | new | `354003da9244abc07858438f619c32a30bf48456edbe6bbeacfe58960c0b21d5` | True | None |
| scripts/limits.py | new | `078249e1db6454b2ac8db016505db540ae1aacb2c8b0b50d7f7cb2550be43bf7` | True | None |
| scripts/make_record.py | new | `9cbbdde6b280e76acfe56729353f94e06753198a5a268dd0413450196310fd4d` | True | None |
| scripts/make_synthetic.py | new | `9fba8ac60c8c14b113e78ce1f4cabe151871e553a4423a363ca49480e725440a` | True | None |
| scripts/controls.py | new | `8394da3d8859cf06cccffab4dbb07026c06c5ed89f8b58dffd7eda0cdc652e57` | True | None |
| scripts/hash_inputs.py | new | `5f385aebdd59bd30bc6b4c77a3d797c8cc64ca481186e2f866664c4fc7c70589` | True | None |
| scripts/gds_xor.py | new | `d57e4852da54729e6f4939c5da931460b3514df136d5348164e9e617e80e9818` | True | None |
| fixtures/lossless_L_100pH.s2p | new | `985c585b8df74bf6c5b4f79f74edde91c22140686799b9246fa94c5ef09e346d` | True | None |
