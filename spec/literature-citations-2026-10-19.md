# Source trail for DR-0008 (LO-drive path after #61)

- **Retrieval date**: 2026-10-19.
- **Issue**: [#68](https://github.com/2AMLogic/sg13g2-sat-rx/issues/68) (`Part of #68`; closure not authorized).
- **Kind**: append-only evidence record supporting [DR-0008](decision-records/0008-lo-drive-path-after-no-acceptable-drive.md). It changes no ratified value and closes no flag.
- **Method and honest limits**: web fetches were attempted from the build host. Several publisher pages timed out, returned HTTP 403, or redirected, and no full paper text was obtained for any journal/conference item. Each entry therefore carries a **verification level**:
  - **V1 — read in full from the primary artifact in this session** (quotable).
  - **V2 — read only as a search-result excerpt or abstract-level summary**; the primary was *not* read. Usable as a *lead* naming what to read, never as evidence of fit.
  - Nothing here is from memory. Items that could not be reached are listed under "Owed".

## V1 — device-model owner documentation

### S1. IHP SG13G2 `sg13g2_hbt_mod.lib` header (model-owner statement of validity)

- Artifact: `ihp-sg13g2/libs.tech/ngspice/models/sg13g2_hbt_mod.lib`, sha256 prefix `ae9288f885dd` (identical to the hash recorded in the #61 records). Copyright 2023 IHP PDK Authors, Apache-2.0. Read from the local PDK checkout on 2026-10-19.
- Verbatim header lines (whitespace collapsed):
  - "Model: VBIC (Rev.1.15)"; "Date: 25.05.18"; "Lot: EDJ802"; "Maximum collector-to-emitter voltage: 1.6"
  - "Meas. Range forward gummel: vbe = (0.3 - 1.04)V"
  - "Meas. Range forward output: vce = (0.4 - 2.0)V"
  - "Meas. Temperature (TEMP): 27 grd C"
  - "Valid range for model: ic: <(0.003*Nx) A vbe :(0.65 - 0.96) V vce :(0.4 - 2.0) V; Temp: -40C - +125C; Valid numbers: NX = 1 - 10"
- **Applicability / what it does and does not say.** The header states a *valid range for the model* of V_BE 0.65–0.96 V. It separately states the forward-Gummel *measurement* range was V_BE 0.3–1.04 V at 27 C. So the card owner measured below 0.65 V but did not declare it valid. The header does **not** say whether the valid range applies to an instantaneous waveform value, to a quasi-static DC operating point, or to the conducting interval only; it says nothing about large-signal switching or the off-going-device case. That interpretation question (DR-0008 option A) can only be answered by the model owner (IHP), not by this repo. No vendor/owner contact is authorized by #68.

## V2 — leads only (primary not read; do not cite as evidence)

### S2. Analog Devices, *The Changing Landscape of Frequency Mixing Components* (2016)

- URL: <https://www.analog.com/en/resources/technical-articles/the-changing-landscape-frequency-mixing-components.html> (also a PDF copy listed under the same title). The direct fetch **timed out twice**; only search-result excerpts were seen.
- Excerpt-level content (V2): passive diode/FET mixers typically need roughly 13–20 dBm LO drive; active mixers roughly 0 dBm; passive mixers have no gain stage so conversion loss ~ noise figure; double-balanced passive mixers described as the best isolation/linearity/NF balance for most applications.
- Applicability limits: a vendor-neutral trade article on *packaged discrete* mixers (diode/FET passive vs active), not on SiGe HBT cores, not at Ka-band, and not under an on-chip device-stress window. **It supports only "drive level and architecture are application tradeoffs".** The 13–20 dBm figure is for discrete diode/FET passive mixers and must not be read as a requirement for an on-chip HBT mixer. Operator-supplied lead; not a design basis.

### S3. Low-LO-drive and passive-V-I SiGe mixers (search-result excerpts, unverified)

Search results (2026-10-19) returned abstract-level summaries for the items below. **None was opened.** Each needs a full read of the paper (LO power, supply, operating frequency, device model used, measurement vs simulation) before it can be cited as practice:

- "Low Power High Linearity 14-23 GHz SiGe HBT Downconversion Mixer" (VDE/TIB proceedings record 455588088; the TIB page returned HTTP 403). Excerpt: passive input network replaces the RF transconductance stage; ~ -3 dB gain; 2.08 mW from 1.5 V. Relevant to a transconductor-less alternative (DR-0008 option D) in a nearby band.
- A V-band 130 nm SiGe mixer with a passive V-I converter and about -10 dBm LO drive (EuMIC 2021/2022 per the search summary; exact title/authors not obtained).
- A 24–30 GHz modified Gilbert downconverter in an IHP 0.13 µm SiGe BiCMOS process (Int. J. Circuit Theory and Applications, 2025, per the search summary; title/authors not obtained), 3.3 V supply, 65 mW. Relevant mainly as evidence that the *same foundry process* has been used for Ka-band Gilbert mixers at supply/power levels **outside** this repo's rows 17/18 (2.5 V, 40 mW LNA+mixer); not comparable as stated.
- "Study and analysis of Gilbert cell-based mixers operating above fMAX/2" (Oulu repository handle 10024/49771).

### S4. IHP VBIC extraction paper

- Fischer et al., *VBIC for HBTs of IHP's 0.13 µm BiCMOS process*, TU Dresden Bipolar Working Group (AKB) 2010. The PDF was fetched but its text was not extractable by the tool, so **nothing was read from it**. Needed to learn the extraction bias range and known accuracy limits of the VBIC card at low V_BE.

## Owed (not obtained; the DR marks every dependent claim unresolved)

1. Full texts of S3 items, with LO power and device-stress practice recorded per paper.
2. The VBIC 1.15 specification and IHP's statement on large-signal validity outside the declared window (source for option A).
3. A textbook-level derivation of the LO swing needed for hard switching of a bipolar quad (Gilbert 1968; Razavi, *RF Microelectronics*; Lee, *Design of CMOS RF ICs*) — cited here as *names to read*, not read.
4. Market-side sources (Ka-band LEO user-terminal element requirements, power/area/cost benchmarks). **None were gathered.**
