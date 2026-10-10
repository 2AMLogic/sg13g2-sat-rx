v {xschem version=3.4.4 file_version=1.2
}
G {}
K {}
V {}
S {}
E {}
T {tb_lna_stage1: smoke-test wrapper for the lna_stage1 symbol (50 ohm terminations, 2.5 V rail). Netlisting this exports lna_stage1 as a .subckt. Not a performance bench; the benches live in sim/lna-sparam-nf.} -400 -300 0 0 0.35 0.35 {}
C {lna_stage1.sym} 0 0 0 0 {name=xdut}
C {devices/lab_pin.sym} -60 0 0 0 {name=l1 lab=in}
C {devices/lab_pin.sym} 60 0 0 0 {name=l2 lab=out}
C {devices/lab_pin.sym} 0 -40 0 0 {name=l3 lab=vdd}
C {devices/lab_pin.sym} 0 40 0 0 {name=l4 lab=gnd}
C {devices/vsource.sym} -300 -100 0 0 {name=Vdd value=2.5}
C {devices/lab_pin.sym} -300 -130 0 0 {name=l5 lab=vdd}
C {devices/lab_pin.sym} -300 -70 0 0 {name=l6 lab=gnd}
C {devices/res.sym} -200 100 0 0 {name=Rs1 value=50 m=1}
C {devices/lab_pin.sym} -200 70 0 0 {name=l7 lab=in}
C {devices/lab_pin.sym} -200 130 0 0 {name=l8 lab=gnd}
C {devices/res.sym} 200 100 0 0 {name=Rs2 value=50 m=1}
C {devices/lab_pin.sym} 200 70 0 0 {name=l9 lab=out}
C {devices/lab_pin.sym} 200 130 0 0 {name=l10 lab=gnd}
C {devices/gnd.sym} -300 -20 0 0 {name=l11 lab=GND}
