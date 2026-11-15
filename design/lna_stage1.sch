v {xschem version=3.4.4 file_version=1.2
}
G {}
K {}
V {}
S {}
E {}
T {lna_stage1: Ka-band (17.7-21.2 GHz DRAFT) LNA first stage, npn13G2 cascode, issue #28} -400 -520 0 0 0.5 0.5 {}
T {MATCHING IS IDEAL / BEHAVIORAL: Cshunt+Lin (input), Lfeed+Cm (output) and the degeneration inductor Le1 are ideal lossless ngspice L/C. No PDK inductor model exists. Not a layout-ready match; Le1's loss and Q are unrepresented (passive qualification is #46).} -400 -470 0 0 0.35 0.35 {}
T {Bias: Qref mirror (Nx=1, 1:8) -> Rbias 10k -> Q1 base, with Qref's base fed from the reference node through Rbr so the larger Rbias keeps the same nominal Ic(Q1); Q2 base from R1b/R2b divider of vdd (Cb2 bypass). Rail <= 2.5 V (row 17); Vce checked per PVT cell in the record.} -400 -430 0 0 0.35 0.35 {}
T {Lfeed is ideal (zero DC drop) and feeds Q2 collector from vdd; Cm is both the output match element and the output DC block.} -400 -390 0 0 0.35 0.35 {}
T {CORE CHANGE (issue #79, variant 'ac'): Le1 = 67 pH of emitter degeneration + Rbias 2k -> 10k with the Rbr base-current compensation. Chosen by the declared selection rule of sim/lna-core-variants (record 20261114-031930-fbdf13c): it is the fewest-change variant whose #74 network-independent NF-vs-S11 bound closes at all 18 in-rail PVT points (worst 2.459 dB vs 2.5 dB at hbt_wcs/125 C/2.25 V; the frozen core was infeasible at 8 of 18). Ideal elements, no spec row claimed met.} -400 -350 0 0 0.35 0.35 {}
C {devices/res.sym} -300 -200 0 0 {name=Rref value=8k m=1}
C {devices/lab_pin.sym} -300 -230 0 0 {name=l1 lab=vdd}
C {devices/lab_pin.sym} -300 -170 0 0 {name=l2 lab=nr}
C {sg13g2_pr/npn13G2.sym} -280 -80 0 0 {name=qr model=npn13G2 spiceprefix=X Nx=1}
C {devices/lab_pin.sym} -260 -110 0 0 {name=l3 lab=nr}
C {devices/lab_pin.sym} -300 -80 0 0 {name=l4 lab=br}
C {devices/lab_pin.sym} -260 -50 0 0 {name=l5 lab=er}
C {devices/lab_pin.sym} -260 -80 0 0 {name=l6 lab=gnd}
C {devices/res.sym} -400 -80 0 0 {name=Rbr value=60.9k m=1}
C {devices/lab_pin.sym} -400 -110 0 0 {name=l43 lab=nr}
C {devices/lab_pin.sym} -400 -50 0 0 {name=l44 lab=br}
C {devices/res.sym} -260 60 0 0 {name=Rer value=24 m=1}
C {devices/lab_pin.sym} -260 30 0 0 {name=l7 lab=er}
C {devices/lab_pin.sym} -260 90 0 0 {name=l8 lab=gnd}
C {devices/res.sym} -150 -80 0 0 {name=Rbias value=10k m=1}
C {devices/lab_pin.sym} -150 -110 0 0 {name=l9 lab=nr}
C {devices/lab_pin.sym} -150 -50 0 0 {name=l10 lab=b1}
C {devices/ind.sym} 300 -280 0 0 {name=Lfeed value=0.962n m=1}
C {devices/lab_pin.sym} 300 -310 0 0 {name=l11 lab=vdd}
C {devices/lab_pin.sym} 300 -250 0 0 {name=l12 lab=oc}
C {devices/res.sym} 380 -280 0 0 {name=Rd value=465 m=1}
C {devices/lab_pin.sym} 380 -310 0 0 {name=l13 lab=vdd}
C {devices/lab_pin.sym} 380 -250 0 0 {name=l14 lab=oc}
C {sg13g2_pr/npn13G2.sym} 180 -150 0 0 {name=q2 model=npn13G2 spiceprefix=X Nx=8}
C {devices/lab_pin.sym} 200 -180 0 0 {name=l15 lab=oc}
C {devices/lab_pin.sym} 160 -150 0 0 {name=l16 lab=b2}
C {devices/lab_pin.sym} 200 -120 0 0 {name=l17 lab=c1}
C {devices/lab_pin.sym} 200 -150 0 0 {name=l18 lab=gnd}
C {sg13g2_pr/npn13G2.sym} 180 0 0 0 {name=q1 model=npn13G2 spiceprefix=X Nx=8}
C {devices/lab_pin.sym} 200 -30 0 0 {name=l19 lab=c1}
C {devices/lab_pin.sym} 160 0 0 0 {name=l20 lab=b1}
C {devices/lab_pin.sym} 200 30 0 0 {name=l21 lab=e1}
C {devices/lab_pin.sym} 200 0 0 0 {name=l22 lab=gnd}
C {devices/ind.sym} 120 140 0 0 {name=Le1 value=67p m=1}
C {devices/lab_pin.sym} 120 110 0 0 {name=l45 lab=e1}
C {devices/lab_pin.sym} 120 170 0 0 {name=l46 lab=e1d}
C {devices/res.sym} 200 140 0 0 {name=Re1 value=3 m=1}
C {devices/lab_pin.sym} 200 110 0 0 {name=l23 lab=e1d}
C {devices/lab_pin.sym} 200 170 0 0 {name=l24 lab=gnd}
C {devices/res.sym} 40 -240 0 0 {name=R1b value=1.5k m=1}
C {devices/lab_pin.sym} 40 -270 0 0 {name=l25 lab=vdd}
C {devices/lab_pin.sym} 40 -210 0 0 {name=l26 lab=b2}
C {devices/res.sym} 40 -120 0 0 {name=R2b value=7k m=1}
C {devices/lab_pin.sym} 40 -150 0 0 {name=l27 lab=b2}
C {devices/lab_pin.sym} 40 -90 0 0 {name=l28 lab=gnd}
C {devices/capa.sym} 100 -180 0 0 {name=Cb2 value=10p m=1}
C {devices/lab_pin.sym} 100 -210 0 0 {name=l29 lab=b2}
C {devices/lab_pin.sym} 100 -150 0 0 {name=l30 lab=gnd}
C {devices/capa.sym} -400 100 0 0 {name=Cshunt value=170f m=1}
C {devices/lab_pin.sym} -400 70 0 0 {name=l31 lab=in}
C {devices/lab_pin.sym} -400 130 0 0 {name=l32 lab=gnd}
C {devices/ind.sym} -330 200 0 0 {name=Lin value=1.41n m=1}
C {devices/lab_pin.sym} -330 170 0 0 {name=l33 lab=in}
C {devices/lab_pin.sym} -330 230 0 0 {name=l34 lab=in2}
C {devices/capa.sym} -210 200 0 0 {name=Cblk_in value=1n m=1}
C {devices/lab_pin.sym} -210 170 0 0 {name=l35 lab=in2}
C {devices/lab_pin.sym} -210 230 0 0 {name=l36 lab=b1}
C {devices/capa.sym} 400 -150 0 0 {name=Cm value=57.8f m=1}
C {devices/lab_pin.sym} 400 -180 0 0 {name=l37 lab=oc}
C {devices/lab_pin.sym} 400 -120 0 0 {name=l38 lab=out}
C {devices/ipin.sym} -500 200 0 0 {name=p_in lab=in}
C {devices/lab_pin.sym} -500 200 0 0 {name=l39 lab=in}
C {devices/opin.sym} 520 -150 0 0 {name=p_out lab=out}
C {devices/lab_pin.sym} 520 -150 0 0 {name=l40 lab=out}
C {devices/iopin.sym} 300 -380 0 0 {name=p_vdd lab=vdd}
C {devices/lab_pin.sym} 300 -380 0 0 {name=l41 lab=vdd}
C {devices/iopin.sym} 300 220 0 0 {name=p_gnd lab=gnd}
C {devices/lab_pin.sym} 300 220 0 0 {name=l42 lab=gnd}
