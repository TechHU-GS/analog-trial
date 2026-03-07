** L2 PTAT+VCO — DC operating point debug
.include 'pdk.inc'

.param VDD_VAL = 1.8
Vdd vdd 0 DC {VDD_VAL}

** --- Simple mirror (no cascode first) ---
XM1 net_c1 net_c1 vdd vdd sg13_lv_pmos w=4u l=2u ng=2 m=1
XM2 net_c2 net_c1 vdd vdd sg13_lv_pmos w=4u l=2u ng=2 m=1

** --- HBT pair ---
XQ1 net_c1 net_c1 0 0 npn13G2 Nx=1
XQ2 net_c2 net_c2 net_rptat 0 npn13G2 Nx=1 m=8

** --- R_ptat ---
XRptat net_rptat 0 0 rppd w=0.5e-6 l=13e-6 b=0 m=1

** --- Startup ---
XRstart vdd net_c1 0 rppd w=0.5e-6 l=48e-6 b=7 m=1

** --- PMOS bias for VCO (mirrors IPTAT as PMOS current source) ---
** net_c1 is the PMOS mirror gate → directly usable as PMOS bias
** No extra NMOS bias needed — use PMOS-only current starving

** --- R_out for VPTAT ---
** Mirror IPTAT, convert to voltage: VPTAT = IPTAT × R_out
** Want ~0.5V at 27°C. I_mirror = 38µA → R_out = 0.5/38µ = 13kΩ
** rppd w=0.5u l=5.5u b=2 → ~13 kΩ (260 Ω/sq × 50 sq)
XM5 vptat net_c1 vdd vdd sg13_lv_pmos w=4u l=2u ng=2 m=1
XRout vptat 0 0 rppd w=0.5e-6 l=5.5e-6 b=2 m=1

** --- 5-stage current-starved ring VCO ---
** PMOS current-starved pull-up + normal NMOS pull-down
** Bias = net_c1 (PMOS mirror gate from PTAT core)

** Stage 1
XMpb1 ps1 net_c1 vdd vdd sg13_lv_pmos w=1u l=4u ng=1 m=1
XMpu1 vco1 vco5 ps1 vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMpd1 vco1 vco5 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1

** Stage 2
XMpb2 ps2 net_c1 vdd vdd sg13_lv_pmos w=1u l=4u ng=1 m=1
XMpu2 vco2 vco1 ps2 vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMpd2 vco2 vco1 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1

** Stage 3
XMpb3 ps3 net_c1 vdd vdd sg13_lv_pmos w=1u l=4u ng=1 m=1
XMpu3 vco3 vco2 ps3 vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMpd3 vco3 vco2 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1

** Stage 4
XMpb4 ps4 net_c1 vdd vdd sg13_lv_pmos w=1u l=4u ng=1 m=1
XMpu4 vco4 vco3 ps4 vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMpd4 vco4 vco3 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1

** Stage 5
XMpb5 ps5 net_c1 vdd vdd sg13_lv_pmos w=1u l=4u ng=1 m=1
XMpu5 vco5 vco4 ps5 vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMpd5 vco5 vco4 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1

** Buffer
XMbp1 buf1 vco5 vdd vdd sg13_lv_pmos w=4u l=0.5u ng=1 m=1
XMbn1 buf1 vco5 0 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XMbp2 vco_out buf1 vdd vdd sg13_lv_pmos w=8u l=0.5u ng=2 m=1
XMbn2 vco_out buf1 0 0 sg13_lv_nmos w=4u l=0.5u ng=2 m=1

.option itl1=500 itl4=200

.control
** Skip OP (segfault-prone), go straight to transient
tran 1n 10u uic

** Measure PTAT bias from late transient
meas tran v_c1 FIND v(net_c1) AT=0.5u
meas tran v_c2 FIND v(net_c2) AT=0.5u
meas tran v_rptat FIND v(net_rptat) AT=0.5u
meas tran v_ptat FIND v(vptat) AT=0.5u

** Measure VCO period (use later rises for settled oscillation)
meas tran t1 TRIG v(vco_out) VAL=0.9 RISE=3 TARG v(vco_out) VAL=0.9 RISE=4
let freq = 1/t1
echo ""
echo "=== PTAT CORE ==="
echo ""
echo "=== VCO ==="
print freq

wrdata /private/tmp/claude-501/ptat_vco_tran.dat v(vco_out) v(vco5) v(vptat)

echo "=== DONE ==="
.endc

.end
