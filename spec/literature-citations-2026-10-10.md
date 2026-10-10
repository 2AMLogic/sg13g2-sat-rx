# Primary-source check of row 1 band edges (ITU RR Art. 5 table body) and row 16 channel bandwidth

- **Date / retrieval date**: 2026-10-10 (all documents below were fetched on this date).
- **Issue**: [#86](https://github.com/2AMLogic/sg13g2-sat-rx/issues/86) — executes `target-spec.md` open item 2.
- **Follows**: `spec/literature-citations-2026-10-09.md` ("Row 1" and "Row 16" sections), which left the table-body check and the channel-bandwidth source owed. That record is **not edited**; this record supplements it and supersedes nothing.
- **Kind**: append-only evidence record. It is **not** a decision record and changes **no ratified value**. `spec/target-spec.md` and `spec/row-coverage.json` are untouched: rows 1 and 16 stay **OPEN** and their `NEEDS-VERIFICATION` flags stay in place. A flag is closed by a later PR that reads this record.
- **Method**: documents were downloaded with `curl` into a scratch directory and converted with `pdftotext -layout`. Every quotation below is copied from that extracted text; nothing is from memory. Layout whitespace inside table cells was collapsed to single spaces; words were not altered.

## Part 1 — ITU Radio Regulations, Article 5, table body for 17.7-21.2 GHz

### Source

- ITU, *Radio Regulations, Articles*, **Edition of 2024** (incorporates WRC-23; entry into force 1 January 2025 per the Secretariat note), Volume 1, Chapter II "Frequencies", Article 5.
- URL: <https://www.itu.int/dms_pub/itu-r/opb/reg/R-REG-RR-2024-ZPF-E.zip> (linked from <https://www.itu.int/pub/R-REG-RR-2024>); member `2400594-RR-Vol 1-E-A5.pdf`. SHA-256 of the extracted PDF begins `a19db602...`.
- Page references below are the Volume 1 page labels printed on the page (`RR5-nnn`, with the running page number in parentheses).

### Table body (verbatim, whitespace collapsed)

`RR5-128` (p. 162), band 17.7-18.4 GHz (Regions 1 / 2 / 3 columns):

- 17.7-18.1 (Region 1) and 17.7-18.1 (Region 3): "FIXED / FIXED-SATELLITE (space-to-Earth) 5.484A 5.517A 5.517B (Earth-to-space) 5.516 / MOBILE".
- 17.7-17.8 (Region 2): "FIXED / FIXED-SATELLITE (space-to-Earth) 5.517 5.517A 5.517B (Earth-to-space) 5.516 / BROADCASTING-SATELLITE / Mobile 5.515"; then 17.8-18.1 (Region 2): "FIXED / FIXED-SATELLITE (space-to-Earth) 5.484A 5.517A 5.517B (Earth-to-space) 5.516 / MOBILE 5.519".
- 18.1-18.4 (all Regions): "FIXED / FIXED-SATELLITE (space-to-Earth) 5.484A 5.516B 5.517A 5.517B (Earth-to-space) 5.520 / INTER-SATELLITE 5.521A / MOBILE 5.519 5.521".

`RR5-131` (p. 165), band "18.4-22 GHz":

- 18.4-18.6 (all Regions): "FIXED / FIXED-SATELLITE (space-to-Earth) 5.484A 5.516B 5.517A 5.517B / INTER-SATELLITE 5.521A / MOBILE".
- 18.6-18.8, Region 2 column: "EARTH EXPLORATION-SATELLITE (passive) / FIXED / FIXED-SATELLITE (space-to-Earth) 5.516B 5.517A 5.522B / MOBILE except aeronautical mobile / SPACE RESEARCH (passive)"; Regions 1 and 3 columns: "FIXED-SATELLITE (space-to-Earth) 5.517A 5.522B".
- 18.8-19.3 (all Regions): "FIXED / FIXED-SATELLITE (space-to-Earth) 5.516B 5.517A 5.517B 5.523A / INTER-SATELLITE 5.521A / MOBILE".
- 19.3-19.7 (all Regions): "FIXED / FIXED-SATELLITE (space-to-Earth) (Earth-to-space) 5.517A 5.523B 5.523C 5.523D 5.523E / INTER-SATELLITE 5.521A 5.523DA / MOBILE".
- 19.7-20.1 (Regions 1 / 2 / 3): "FIXED-SATELLITE (space-to-Earth) 5.484A 5.484B 5.516B 5.517B 5.527A" (Region 2 order of footnotes differs) "/ INTER-SATELLITE 5.521A / Mobile-satellite (space-to-Earth)" (capitalised "MOBILE-SATELLITE" in Region 2) "... 5.524 5.525 5.526 5.527 5.528 5.529".
- 20.1-20.2 (all Regions): "FIXED-SATELLITE (space-to-Earth) 5.484A 5.484B 5.516B 5.517B 5.527A / INTER-SATELLITE 5.521A / MOBILE-SATELLITE (space-to-Earth) 5.524 5.525 5.526 5.527 5.528".
- **20.2-21.2 (single entry spanning all three Region columns):**
  > "FIXED-SATELLITE (space-to-Earth) / MOBILE-SATELLITE (space-to-Earth) / Standard frequency and time signal-satellite (space-to-Earth) / 5.524 5.529A"
- 21.2-21.4 (all Regions): "EARTH EXPLORATION-SATELLITE (passive) / FIXED / MOBILE / SPACE RESEARCH (passive)" — i.e. no FSS above 21.2 GHz.

Footnotes quoted from the same edition:

- 5.524, `RR5-133`: "Additional allocation: in Afghanistan, Algeria, Saudi Arabia, ... Togo and Tunisia, the frequency band 19.7-21.2 GHz is also allocated to the fixed and mobile services on a primary basis. This additional use shall not impose any limitation on the power flux-density of space stations in the fixed-satellite service in the frequency band 19.7-21.2 GHz and of space stations in the mobile-satellite service in the frequency band 19.7-20.2 GHz ..." (WRC-23)
- 5.529A, `RR5-133`: "In the frequency bands 20.2-21.2 GHz and 30-31 GHz, non-geostationary-satellite systems for which complete coordination or notification information, according to the case, is received by the Bureau as of 1 January 2025 shall not cause unacceptable interference to and shall not claim protection from geostationary-satellite networks in the mobile-satellite service operating in accordance with these Regulations. No. 5.43A does not apply." (WRC-23)
- 5.522B, `RR5-132`: "The use of the band 18.6-18.8 GHz by the fixed-satellite service is limited to geostationary systems and systems with an orbit of apogee greater than 20 000 km." (WRC-2000)
- 5.523B, `RR5-132`: "The use of the band 19.3-19.6 GHz (Earth-to-space) by the fixed-satellite service is limited to feeder links for non-geostationary-satellite systems in the mobile-satellite service."
- 5.484A, `RR5-115`: lists "17.8-18.6 GHz (space-to-Earth), 19.7-20.2 GHz (space-to-Earth)" (and, in Region 2, "17.3-17.7 GHz") among bands where use "by a non-geostationary-satellite system in the fixed-satellite service is subject to application of the provisions of No. 9.12". Note that 20.2-21.2 GHz is **not** in this list.
- 5.516B, `RR5-129`: high-density-application identification includes "19.7-20.2 GHz (space-to-Earth) in all Regions" and "18.3-19.3 GHz (space-to-Earth) in Region 2". Nothing at 20.2-21.2 GHz.
- 5.517, `RR5-130`: "In Region 2, use of the fixed-satellite (space-to-Earth) service in the frequency band 17.3-17.8 GHz shall not cause harmful interference to nor claim protection from assignments in the broadcasting-satellite service operating in conformity with the Radio Regulations."

### Finding: is 20.2-21.2 GHz a civil FSS space-to-Earth allocation?

**Yes at the international (ITU Article 5) level, with a footnote caveat.** The 2024 edition's table body allocates 20.2-21.2 GHz, in all three Regions, to the FIXED-SATELLITE SERVICE (space-to-Earth) in upper-case type, which the Radio Regulations use for a primary allocation (the same typography as the 17.7-20.2 GHz entries). The same entry also carries MOBILE-SATELLITE (space-to-Earth) and standard-frequency-and-time-signal-satellite (space-to-Earth) as primary services. The Radio Regulations do not distinguish "civil" from "military" in the table; that distinction is national (see below). The previous record's worry — that only the 17.7-20.2 GHz span was corroborated — is therefore resolved at the ITU level: the 17.7-21.2 GHz span is FSS (space-to-Earth) in every Region, with no gap.

Caveats that bear on a "wideband" claim (recorded, not acted on):

1. **The upper segment is conditioned differently.** 20.2-21.2 GHz carries footnote 5.529A, under which post-1 January 2025 NGSO systems "shall not claim protection from geostationary-satellite networks in the mobile-satellite service". It is also outside the 5.484A/5.516B lists above, so it is not among the bands identified there for NGSO-FSS coordination under No. 9.12 or for high-density FSS. This is a regulatory-status difference, not a physical one; it does not remove the allocation.
2. **There are sub-band restrictions inside 17.7-21.2 GHz.** 18.6-18.8 GHz is FSS (space-to-Earth) only for "geostationary systems and systems with an orbit of apogee greater than 20 000 km" (5.522B), so a LEO downlink is not allocated there in any Region. 19.3-19.7 GHz FSS is (space-to-Earth)(Earth-to-space) with footnotes 5.523B-5.523E restricting parts of it to feeder links. Whether "every row holds across 17.7-21.2 GHz" (the repo's definition of wideband) is a design requirement or whether the band should be a union of usable LEO sub-bands is a **DR-0001 follow-up question**, not an edit made here.
3. **Region 2, 17.7-17.8 GHz** also carries BROADCASTING-SATELLITE and footnote 5.517 (FSS not to cause harmful interference to BSS). The lower edge is therefore allocated but encumbered in Region 2.
4. **National (US) overlay is separate.** The 2026-10-09 record quoted G117 (US Federal FSS/MSS limited to military systems in 17.6-21.2 GHz) from 47 CFR 2.106. That is a statement about *Federal* use in the US Table, not about whether a civil non-Federal space-to-Earth allocation exists; it is not contradicted by this finding, and the US non-Federal column was **not** re-fetched here. If the design's target jurisdiction is the US, the non-Federal column of 47 CFR 2.106 for 20.2-21.2 GHz is still unchecked.

**Disposition.** The ITU-level edge check requested by `target-spec.md` open item 2 for row 1 is satisfied by this record: both 17.7 GHz and 21.2 GHz are FSS (space-to-Earth) band edges in the 2024 Edition table body (21.2-21.4 GHz carries no FSS allocation). Row 1 is **not** edited here; the `NEEDS-VERIFICATION` flag is closed or reworded by a later PR. The caveats above are suggested inputs to DR-0001 before it leaves *proposed*; this record does not change the DR.

## Part 2 — Primary source for LEO broadband downlink channel bandwidth

### What was obtained

**3GPP TS 38.101-5** (NR; UE radio transmission and reception; Part 5: Satellite access RF and performance requirements), version 19.5.0, Release 19, as published by ETSI as **ETSI TS 138 101-5 V19.5.0 (2026-08)**.
URL: <https://www.etsi.org/deliver/etsi_ts/138100_138199/13810105/19.05.00_60/ts_13810105v190500p.pdf>. SHA-256 of the file begins `4ae322f0...`. (This is a standards-body specification of a satellite-access air interface; it is **not** any LEO operator's published channel plan.)

- Table 5.2.3-1 "Satellite operating bands in FR2-NTN" (p. 20): satellite operating bands n512, n511 and n510 have a downlink ("SAN transmit / UE receive") of "17300 MHz - 20200 MHz" (FDD); the uplinks are 27500-30000 MHz (n512), 28350-30000 MHz (n511) and 27500-28350 MHz (n510).
- Table 9.2.1.0-1 "The definitions of NTN VSAT Types" (p. 101) includes "Fixed VSAT communicating with GSO and LEO", "Fixed VSAT communicating with LEO only with electronic steering antenna" and "Mobile VSAT communicating with LEO only with electronic steering antenna"; its NOTE 3 states "LEO support for bands n512, n511 is excluding: For band n511: 18.6-18.8 and 19.4-19.6 GHz (DL); ..." — consistent with footnotes 5.522B/5.523x in Part 1.
- Table 5.3.5-2 "Channel bandwidths for each NTN satellite band in FR2-NTN" (p. 23), for n512, n511, n510: UE channel bandwidths of **50, 100, 200 and 400 MHz**. At 60 kHz SCS the row is 50, 100, 200; at 120 kHz SCS it is 50, 100, 200, 400. In the extracted text the 200 and 400 MHz entries carry a footnote marker (rendered "2001", "4001"); the table's NOTE 1 reads "This UE channel bandwidth is optional in this release of the specification."

### Finding for row 16

- A standardized Ka-band NR-NTN downlink in 17.3-20.2 GHz (which covers the LEO-usable part of the repo's band up to 20.2 GHz) defines carrier channel bandwidths of **at most 400 MHz** (optional, 120 kHz SCS only), with 200 MHz and below as the other tabulated sizes. **No 500 MHz channel appears.** The row-16 phrase "one LEO broadband channel ≈ 500 MHz" is therefore **not supported as stated** by this source; the nearest published figures are 400 MHz (largest, optional) and 200 MHz.
- Two readings are open and this record does not choose between them: (a) the IF must pass **one** such carrier, so ≥ 400 MHz (or 200 MHz for the non-optional sizes) would be the supported figure; (b) the IF must pass **contiguous or aggregated** carriers, in which case ≥ 500 MHz is an aggregation assumption, not a single-channel one. 3GPP channel bandwidth is a *UE channel* bandwidth, i.e. the occupied carrier, so the −1 dB IF flatness bandwidth needed to pass it would also exceed the channel figure by the amount of roll-off the architecture allows; that margin is a design choice, not in the source.
- This is a **DR-0002 / DR-0001 follow-up**, not an edit here: the IF bandwidth bound interacts with the beamsteering partition (DR-0002) and the band choice (DR-0001), and row 16's sentence "one LEO broadband channel" should be reworded or its number re-derived from a stated carrier plan. The `≥ 500 MHz` value is **not** shown wrong by this record (it remains a conservative superset of a 400 MHz carrier); it is shown to have no single-channel source.

### Not obtained: operator channel plans — a human must fetch these

I tried to find a published **LEO operator** channel bandwidth (Starlink-class, Kuiper-class) and did not obtain one. Specifically:

- The FCC Orders fetched and searched on 2026-10-10 — FCC 18-161 (SpaceX Gen1 NGSO FSS authorization, Nov 2018), FCC 20-102 (Kuiper, July 2020) and FCC 22-91 (SpaceX Gen2, Dec 2022), from `docs.fcc.gov/public/attachments/` — **do not state a downlink channel bandwidth** (searched for "channel", "channel bandwidth", "MHz channel", "250 MHz", "bandwidth of"); the only "channel" hits in FCC 22-91 are about channels-per-beam in general terms and a generic reference. They are not citable for row 16.
- Operator technical narratives (Schedule S / technical annex attached to the satellite applications), ITU filings (e.g. Article 9 / Appendix 4 notification data for the LEO constellations in the Ka downlink) and ITU-R reports on NGSO FSS were not retrievable with the tools available (no search engine, only direct `curl`). I do not quote any value for them and do not recall one.

**What a human must fetch** to settle "one LEO broadband channel": (i) the SpaceX and Amazon Kuiper (and any other target operator's) FCC IBFS/ICFS Schedule S technical-annex filings, giving the Ka-band (17.7-20.2 GHz) downlink carrier / channel bandwidth; or (ii) the corresponding ITU Space Network List / Appendix 4 notification, or an ITU-R Recommendation/Report stating a typical NGSO FSS Ka-band downlink channel bandwidth. Until then, the only checkable primary source for the row-16 number is the 3GPP figure above.

## Summary of dispositions

| Row | Question | Result of this pass | Flag |
|---|---|---|---|
| 1 | Are the 17.7 and 21.2 GHz edges FSS (space-to-Earth) in ITU RR Art. 5? Is 20.2-21.2 GHz one? | Yes: ITU RR 2024 Edition, Art. 5 table body (`RR5-128`, `RR5-131`): 20.2-21.2 GHz is FSS (space-to-Earth) in all Regions; 21.2-21.4 GHz is not. Sub-band LEO and Region-2 caveats recorded. | stays flagged until a later PR reads this record; US non-Federal column unchecked |
| 16 | Is ≈ 500 MHz a published LEO broadband channel bandwidth? | Not supported by the one source obtained: 3GPP NR-NTN Ka-band channel sizes are 50/100/200/400 MHz (400 optional). Operator channel plans **not obtained**. | stays flagged |

No simulation was run to produce this record. No file other than this one was added or edited.
