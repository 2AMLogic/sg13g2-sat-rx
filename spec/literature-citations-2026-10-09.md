# Literature citations for the (E) / NEEDS-VERIFICATION rows of `target-spec.md`

- **Date**: 2026-10-09
- **Issue**: [#29](https://github.com/2AMLogic/sg13g2-sat-rx/issues/29) — executes the citation half of `target-spec.md` open item 1 and DR-0003's recorded follow-up.
- **Kind**: append-only evidence record. It is **not** a decision record and changes **no ratified value**. A later record supersedes this one (with a stated reason); this file is not edited to remove or soften an entry.
- **Ratification state touched**: none. Rows 2, 3, 9, 10 stay **RATIFIED (target)**; rows 1 and 16 stay **OPEN**; every `(E)` / `NEEDS-VERIFICATION` flag in `target-spec.md` **stays in place**. A flag is closed by a later PR that reads this record, not by this record.

## Method, and what "checked" means here

1. Candidates were found by searching the OpenAlex index (`api.openalex.org`) for SiGe / BiCMOS Ka-, K- and mm-wave LNAs, active mixers, and SATCOM receive front ends.
2. Each kept entry's **DOI was resolved against the Crossref API** (`api.crossref.org/works/<DOI>`) and the title, venue, year and first author matched the table below.
3. The **number quoted is copied from the abstract text** returned for that DOI. **Full texts were not read** (paywalled, or not retrievable from this host). Every figure below is therefore an abstract-level figure; where the abstract omits a condition (temperature, process `fT/fmax`, whether a gain is voltage or power, whether an IP3 is input- or output-referred), this record says "not stated in abstract" and does **not** fill it in.
4. Row 1 uses a primary regulatory source instead: the ITU Radio Regulations footnotes as reproduced in 47 CFR 2.106 (eCFR, retrieved 2026-10-09).
5. Entries that could not be verified, or whose abstract was damaged or lacked the needed number, are **left out** (see "Considered and excluded").

Nothing here was invented or recalled from memory: every author, year, venue, DOI and number below was retrieved and matched in this session.

## Citation table

"Process" is as stated in the abstract. "Block" says what was measured: an LNA alone, or a beamformer / front-end channel that contains an LNA (a channel number is **not** an LNA number and is labelled so).

| ID | Author (first), venue, year | DOI / URL | Block, band, process (as stated) | Exact figures quoted from the abstract |
|---|---|---|---|---|
| C1 | W. Lyu et al., *Electronics Letters*, 2025 | [10.1049/ell2.70472](https://doi.org/10.1049/ell2.70472) | Noise-cancelling LNA, 18-36 GHz, 130 nm SiGe BiCMOS | "peak gain of 21.4 dB at 21 GHz and a minimum noise figure (NF) of 2.9 dB at 26 GHz. The 3-dB bandwidth is 18 GHz, and the input 1-dB compression point is better than -15 dBm." |
| C2 | Z. Hu et al., *IEEE RFIC Symposium*, 2023 | [10.1109/rfic54547.2023.10186157](https://doi.org/10.1109/rfic54547.2023.10186157) | 16-channel dual-beam **receive beamformer channel** (LNA inside the channel), C/X/Ku/Ka SATCOM, 90-nm SiGe BiCMOS | "27.3 dB electronic gain with a 3.4-28.7 GHz 3-dB bandwidth and a 2.1-2.3 dB noise figure (NF) up to 21 GHz." |
| C3 | Z. Hu et al., *IEEE Trans. Microw. Theory Techn.*, 2024 | [10.1109/tmtt.2024.3349518](https://doi.org/10.1109/tmtt.2024.3349518) | Same family, 16-channel RX beamformer **channel**, 3.1-25.5 GHz, 90-nm SiGe BiCMOS | "The measured electronic gain of each channel is 26.6 dB with a 3.1-25.5-GHz 3-dB bandwidth ... The measured noise figure (NF) is <2.0 dB at the C-, X-, and Ku-bands and <2.4 dB at the Ka-band." |
| C4 | F. Tabarani et al., *IET Microw. Antennas Propag.*, 2020 (issued 2020-02-13 per Crossref) | [10.1049/iet-map.2019.0447](https://doi.org/10.1049/iet-map.2019.0447) | Full-duplex K/Ka SATCOM phased-array front end, **receive channel** (19.7-21 GHz RX band), 0.25 um SiGe:C BiCMOS | "In receive mode, 33.7 dB gain is measured with a noise figure of 3.2 dB." "... it consumes 81 and 15.5 mW per transmit and receive channels, respectively." RX band stated as 19.7-21 GHz. |
| C5 | J. Lee, C. Nguyen, *APMC*, 2013 | [10.1109/apmc.2013.6695112](https://doi.org/10.1109/apmc.2013.6695112) | Concurrent dual-band LNA, 24/35 GHz, "BiCMOS" (node not stated in abstract) | "measured peak gains of 21.9/16.6 dB at 23.5/35.7 GHz" ; "best noise figures measured in the passbands are 5.1/7.2 dB at 22/35.6 GHz" ; "IIP3 performances are -10.4/-8.3 dBm at 24/35 GHz" ; low pass-band 3-dB BW "7.7 GHz (18.8-26.5 GHz)". |
| C6 | P. Riemer et al., *IEEE MTT-S IMS*, 2005 | [10.1109/mwsym.2005.1516846](https://doi.org/10.1109/mwsym.2005.1516846) | 3-stage LNA, 35 GHz, "120 GHz ft/fmax SiGe BiCMOS technology (IBM 7HP)" | "At 35 GHz, the 3-stage LNA exhibited 15.1 dB gain, -5.9 dBm output compression (P1dB), 9 dBm third order intercept (IP3), and 5.6 dB noise figure at 25.6 mW DC power. Peak gain and bandwidth ... 19.0 dB and 10.7 GHz respectively at a center frequency of 31.3 GHz." (IP3 reference plane not stated in abstract.) |
| C7 | J. Luo, P. Chen, *Int. J. Numer. Model.*, 2023 | [10.1002/jnm.3137](https://doi.org/10.1002/jnm.3137) | One-stage triple-stacked LNA, 9-23 GHz, 0.18-um SiGe BiCMOS | "peak gain of 13.8 dB at 19.5 GHz, minimum noise figure of 3.1 dB at 14 GHz, 3-dB bandwidth of 14 GHz ... consuming a dc power of 39.6 mW." |
| C8 | Z. Chen et al., *IEEE IWS*, 2022 | [10.1109/iws55252.2022.9977672](https://doi.org/10.1109/iws55252.2022.9977672) | 5-stage cascode LNA, 31.6-38.2 GHz, 0.18-um SiGe BiCMOS | "3-dB bandwidth from 31.6 GHz to 38.2 GHz with a maximum gain of 42.9 dB. The circuit operates from a 2.5 V supply with a DC power consumption of 60 mW." |
| C9 | T. Gathman, J. Buckwalter, *IEEE MTT-S IMS*, 2010 | [10.1109/mwsym.2010.5518190](https://doi.org/10.1109/mwsym.2010.5518190) (a duplicate record, 10.1109/mwsym.2010.5517977, carries the same abstract) | 4-stage high-pass **distributed** amplifier, 21-42.5 GHz, 120 nm SiGe BiCMOS | "gain of 8.3 dB over a 3dB bandwidth from 21 - 42.5 GHz ... The minimum noise figure is 6.9 dB, and output P1dB is 0 dBm." |
| C10 | S. Yang et al., *Sensors*, 2022 | [10.3390/s22103802](https://doi.org/10.3390/s22103802) | Double-balanced **Gilbert-cell down-conversion mixer**, 24-30 GHz (title), 130 nm SiGe BiCMOS | "Under a 1.6 V supply voltage ... IP1dB of +7.2~+10.1 dBm, an average OP1dB of +5.4 dBm ... IF bandwidth of 8 GHz from 3 GHz to 11 GHz ... consumes 19.8 mW." Conversion gain, NF and IIP3 are **not stated in the abstract**. |
| C11 | S.-H. Lee et al., *Microw. Opt. Technol. Lett.*, 2008 | [10.1002/mop.23887](https://doi.org/10.1002/mop.23887) | Double-balanced down-conversion mixer with active baluns, **60 GHz** (out of band; shown as a high-frequency SiGe-mixer data point), 0.25 um SiGe:C BiCMOS | "conversion gain of 12.0-10.7 dB, LO to RF isolation and LO to IF isolation of more than 28 dB, and input P1dB of -17 to -18 dBm" (RF 57-63 GHz). Voltage vs power gain, and LO drive, **not stated in abstract**. |
| C12 | S. Jin et al., preprint (Authorea), 2023 | [10.22541/au.169227806.62750881/v1](https://doi.org/10.22541/au.169227806.62750881/v1) | **Not SiGe**: 65-nm CMOS SOI four-element K-band SATCOM RX; listed only because it is the one hit that covers exactly 17.7-21.2 GHz | "operating from 17.7 to 21.2 GHz ... single-channel gain is 21.48-25.31 dB, and the noise figure is 2.42-2.77 dB over the entire working frequency." Preprint, not peer-reviewed as retrieved. |
| R1 | ITU Radio Regulations footnotes as reproduced in 47 CFR 2.106 (eCFR) | <https://www.ecfr.gov/current/title-47/part-2/section-2.106> (retrieved 2026-10-09) | Satellite band allocations / footnotes | See "Row 1" below. |

## Row-by-row mapping

Rows not listed under a heading below have **no supporting source found** and stay flagged (see the last table).

### Row 1 — receive band 17.7-21.2 GHz (OPEN; DR-0001 proposed)

Source R1 (quotes are verbatim from the retrieved text):

- 5.516B: "The following bands are identified for use by high-density applications in the fixed-satellite service: ... 19.7-20.2 GHz (space-to-Earth) in all Regions ..."
- 5.517A: earth stations in motion with GSO FSS "within the frequency bands 17.7-19.7 GHz (space-to-Earth) and 27.5-29.5 GHz (Earth-to-space)".
- US334: "In the bands between 17.8 GHz and 20.2 GHz, Federal space stations ... in the fixed-satellite service (FSS) (space-to-Earth) may be authorized on a primary basis."
- 5.517: "In Region 2, use of the fixed-satellite (space-to-Earth) service in the band 17.7-17.8 GHz shall not cause harmful interference to nor claim protection from assignments in the broadcasting-satellite service ..."
- 5.524 (additional allocation, listed countries): "the frequency band 19.7-21.2 GHz is also allocated to the fixed and mobile services on a primary basis. This additional use shall not impose any limitation on the power flux-density of space stations in the fixed-satellite service in the frequency band 19.7-21.2 GHz ..."
- G117: "In the bands ... 17.6-21.2 GHz ... the Federal fixed-satellite and mobile-satellite services are limited to military systems."
- US532: "In the bands 21.2-21.4 GHz ... the space research and Earth exploration-satellite services shall not receive protection from the fixed and mobile services ..."

**Finding (does not close the flag).** The retrieved text corroborates a space-to-Earth FSS downlink from 17.7/17.8 GHz up to **20.2 GHz** (5.516B, 5.517A, US334). For the **20.2-21.2 GHz** upper segment the retrieved text shows only that 19.7-21.2 GHz is a band in which FSS space stations exist (5.524) and that 17.6-21.2 GHz is a US Federal military FSS/MSS range (G117); it does **not** show a general civil FSS space-to-Earth allocation up to 21.2 GHz. The allocation table itself was not in the retrieved text, so this is **absence of confirmation, not a contradiction**. Row 1 stays OPEN and `NEEDS-VERIFICATION`; the table-body check of the 20.2-21.2 GHz segment (ITU RR Article 5 table, Regions 1/2/3) is still owed. If that check shows 20.2-21.2 GHz is not a downlink allocation, that is a DR-0001 matter, not an edit here.

### Row 2 — LNA gain S21 >= 20 dB across band, `hbt_wcs` / 125 C / min supply

Supports feasibility of a >= 20 dB multi-stage LNA in this frequency range: C1 (21.4 dB peak at 21 GHz), C5 (21.9 dB peak at 23.5 GHz), C8 (42.9 dB, five stages), C2/C3 (26.6-27.3 dB per beamformer channel, not LNA-only). Counter-weights for what a **few-stage** circuit gives: C6 (15.1 dB at 35 GHz, 3 stages, 7HP), C7 (13.8 dB peak, single stage), C9 (8.3 dB, distributed). **Not comparable on the row's actual condition**: every figure is a peak or a band figure at an unstated (presumably room) temperature, none is a 125 C / worst-process / minimum-supply, in-band-minimum number. Flag **stays**.

### Row 3 — LNA NF50 <= 2.5 dB across band, all corners (highest-risk row)

- Closest SiGe evidence over the actual band: C2, a 2.1-2.3 dB **channel** NF "up to 21 GHz" in a 90-nm SiGe BiCMOS process (channel, not LNA-only; process more advanced than a 0.13 um HBT is not asserted either way, the abstract gives no `fT/fmax`). C3: "<2.4 dB at the Ka-band" for the same family.
- LNA-only SiGe numbers are higher: C1 2.9 dB minimum at 26 GHz (130 nm), C7 3.1 dB minimum at 14 GHz (0.18 um, single stage), C5 5.1 dB at 22 GHz, C6 5.6 dB at 35 GHz (7HP, 2005), C4 3.2 dB for a 19.7-21 GHz RX channel (0.25 um).
- Non-SiGe, exact band, context only: C12 2.42-2.77 dB over 17.7-21.2 GHz.
- Device-level cross-reference (this repo, not literature): `sim/hbt-kaband-characterization/records/20261009-095725-dbf8179.md` reports a bare-device NFmin worst case of 1.287 dB (`hbt_wcs`, 125 C, 2.25 V, 21.2 GHz) with its own caveat that it is a lower bound on an unvalidated model card.

**Finding.** Literature shows that ~2.1-2.4 dB channel NF across this band is demonstrated in SiGe BiCMOS (C2, C3), so 2.5 dB is not implausible as a *room-temperature, best-case* number; it does **not** show 2.5 dB at **125 C / `hbt_wcs`** (no abstract states temperature), and the LNA-only SiGe entries that state an NF (C1, C5, C6, C7) are all above 2.5 dB. No evidence contradicts the bound as set; no evidence establishes it. The row's own existing statement ("an aspiration to be tested") is consistent with what was found. Flag **stays**.

### Row 7 — LNA IIP3 >= -15 dBm; Row 8 — LNA input P1dB >= -25 dBm

- Row 7: C5 reports IIP3 of -10.4 dBm at 24 GHz and -8.3 dBm at 35 GHz (clear of -15 dBm by 4.6-6.7 dB). C6 reports "9 dBm" IP3 at 35 GHz but does not state input or output referral in the abstract, so it is **not** used as an IIP3 number. 
- Row 8: C1 reports input P1dB "better than -15 dBm" (18-36 GHz), clear of -25 dBm. C6's -5.9 dBm is an **output** P1dB and is not used.
- Both are single published room-temperature-style points; the rows are specified at `hbt_typ` nominal, which is the closest match here. These two rows are marked `(E)` but carry **no** NEEDS-VERIFICATION text in the table; this record is supporting evidence for them, and no flag text was there to close. 

### Row 9 — mixer conversion gain >= 8 dB (power CG into 50 ohm), active

Only C11 states a conversion gain (12.0-10.7 dB) and it is at **60 GHz**, 0.25 um, with gain type not stated: it shows an active SiGe double-balanced mixer clearing 8 dB at a *higher* RF, but not at 17.7-21.2 GHz, not as *power* gain into 50 ohm, and not at `hbt_wcs` / 125 C. C10 (24-30 GHz SiGe Gilbert mixer) does not state CG in the abstract. **No in-band source found. Flag stays.**

### Row 10 — mixer SSB NF <= 12 dB

**No K/Ka-band SiGe active-mixer NF with an SSB/DSB statement was found among verifiable entries.** (Mixer NFs found were in other bands, from other processes, or DSB/unstated; they were excluded rather than stretched.) Flag stays, and the SSB-vs-DSB hazard the row already names applies to anything added later.

### Row 11 — mixer IIP3 >= -5 dBm

C10 gives mixer IP1dB of +7.2 to +10.1 dBm at 24-30 GHz in 130 nm SiGe BiCMOS; its abstract does not give IIP3, and no IIP3 is inferred here from IP1dB. C11 gives input P1dB -17 to -18 dBm at 60 GHz (a different, lower-linearity design point, shown so that the spread is visible). **Finding**: published SiGe active-mixer linearity at 24-30 GHz spans a range that includes values far above the -5 dBm IIP3 target in the P1dB sense (C10); that supports feasibility only for a linearized topology, at the cost shown there (19.8 mW at 1.6 V). IIP3 itself remains unsupported; this row has no NEEDS-VERIFICATION text, and nothing is closed.

### Row 18 — LNA + mixer DC power <= 40 mW

Individual blocks, different bands and processes, so **no sum is claimed**: LNA 25.6 mW (C6, 3-stage, 35 GHz), LNA 39.6 mW (C7, single stage), LNA 60 mW (C8, 5-stage, 2.5 V), RX channel 15.5 mW (C4: includes amplitude/phase control, 19.7-21 GHz), mixer 19.8 mW (C10, 1.6 V). **Finding**: published LNA-only powers already sit at 25-60 mW, so a 40 mW LNA-**plus**-mixer budget is demanding relative to this sample; this is evidence about difficulty, not a contradiction, and no bound is touched.

### Row 16 — IF bandwidth >= 500 MHz (one LEO broadband channel) — OPEN

No verifiable source for a LEO broadband channel bandwidth was obtained in this pass. Flag stays. (C10 reports an 8 GHz IF bandwidth for a mixer, which shows IF-port capability, not what a channel plan requires.)

## Disposition of every (E) row

| Row | Parameter | Literature support found? | Flag disposition |
|---|---|---|---|
| 1 | Receive band | Partial: R1 corroborates to 20.2 GHz; 20.2-21.2 GHz unconfirmed | **stays flagged** |
| 2 | LNA gain | Feasibility only (C1, C5, C8, C2/C3); no corner-matched number | **stays flagged** |
| 3 | LNA NF50 | Channel-level 2.1-2.4 dB in-band (C2, C3); LNA-only SiGe above 2.5 dB (C1, C5, C6, C7) | **stays flagged** |
| 5 | LNA S22 / interstage | none | stays `(E)` |
| 6 | k-factor to 3x band | none | stays `(E)` |
| 7 | LNA IIP3 | C5 (-10.4/-8.3 dBm) | `(E)` stays; supporting evidence recorded |
| 8 | LNA P1dB (in) | C1 (better than -15 dBm) | `(E)` stays; supporting evidence recorded |
| 9 | Mixer CG | out-of-band only (C11) | **stays flagged** |
| 10 | Mixer NF SSB | none verifiable | **stays flagged** |
| 11 | Mixer IIP3 | IP1dB only (C10), no IIP3 | `(E)` stays |
| 12 | Cascade NF SSB | none (C4 is LNA+control, no mixer) | stays `(E)` |
| 13 | Cascade CG | none | stays `(E)` |
| 15 | LO drive / leakage | C11 isolation > 28 dB at 60 GHz, LO drive not stated, not a dBm-at-port number | stays `(E)` |
| 16 | IF centre / BW | none | **stays flagged** |
| 18 | DC power | difficulty evidence only (C4, C6, C7, C8, C10) | `(E)` stays |

Rows 4, 14, 17, 19, 20 are not `(E)`-sourced as such (their sources are (L), (P), derived, or (KLT)) and are untouched.

## Findings and decision-record posture

1. **No bound is shown wrong before the fact.** Nothing retrieved contradicts a ratified bound in a way that was knowable when DR-0003 was written: every contrary-looking entry is in a different band, process, temperature (unstated), or block type, and those differences are recorded beside it. **No DR is proposed by this record.**
2. **Row 3 remains the open risk**, exactly as the table already says: in-band SiGe literature reaches 2.1-2.4 dB only as beamformer-channel NF at what the abstracts do not say is room temperature; LNA-only SiGe results found are 2.9-5.6 dB. The 125 C / `hbt_wcs` corner is the binding one and is not covered by any entry.
3. **Row 1's upper edge (21.2 GHz) is not confirmed by the primary source retrieved** (see Row 1). This should be settled against the ITU Article 5 table before DR-0001 leaves *proposed*.
4. **Mixer rows 9, 10, 11 are essentially unsupported by in-band SiGe literature** retrievable here. The follow-up that would help is full-text reading of K/Ka-band SiGe mixer papers (conversion gain type, NF SSB/DSB, IIP3), which needs literature access this environment lacks beyond abstracts.
5. **Abstract-level only.** Any later PR that wants to cite one of these numbers as a *basis* for editing a flag or bound should read the full text first, confirm the measurement conditions the abstract omits, and say so.

## Considered and excluded (not usable, so not cited)

- Min and Rebeiz, *IEEE JSSC* 2008, DOI 10.1109/jssc.2008.2004336 ("Single-Ended and Differential Ka-Band BiCMOS Phased Array Front-Ends"): the abstract text as retrieved is **corrupted** (several numbers lost between "<" and ">" characters), so no figure can be quoted verbatim. Left out.
- Liu et al., *IEEE TMTT* 2016, DOI 10.1109/tmtt.2016.2602837 (Ka-band 0.13 um T/R front end): 30-40 GHz and a 0.528 W RX-mode DC power; far outside the 17.7-21.2 GHz band and the power budget; not a mapping target for any (E) row.
- E. Ball, *Electronics* 2022, DOI 10.3390/electronics11162516 (26 GHz SiGe transconductance mixer): the measured results are from "PCB results" of a single-ended prototype and the abstract gives only prediction errors, no conversion-gain or IIP3 values.
- Mixers or receivers at 140-275 GHz (e.g. DOIs 10.1109/jssc.2018.2839037, 10.1109/lmwt.2023.3283008) and CMOS mixers at 24-40 GHz: wrong band or wrong process for the row they would otherwise map to.
- 2005 keynote and review papers (e.g. Cressler, SPIE 2005; Kissinger et al., TMTT 2021): abstracts contain no band-specific figures.
- Theses/dissertations without a stable abstract-level number.
- Row 16 (LEO channel bandwidth) and a table-body ITU allocation check: no verifiable source obtained; left open rather than guessed.

## Retrieval record

- Host tools used: `curl` against `api.openalex.org`, `api.crossref.org`, `www.ecfr.gov` (versioner API, `title-47`, part 2, section 2.106, date 2026-09-01 snapshot). No web-search tool was available in this environment; discovery was via OpenAlex keyword search, which means this table is **a verified sample, not a systematic survey**. It makes no claim that better in-band results do not exist.
- No simulation was run to produce this record.
