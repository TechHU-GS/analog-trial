** L2 PTAT+VCO — Single-temp test at 27°C, then manual temp changes
** Run each temperature separately to avoid ngspice foreach state issues
.include 'pdk.inc'

.param VDD_VAL = 1.8
Vdd vdd 0 DC {VDD_VAL}

** --- Simple mirror ---
XM1 net_c1 net_c1 vdd vdd sg13_lv_pmos w=4u l=2u ng=2 m=1
XM2 net_c2 net_c1 vdd vdd sg13_lv_pmos w=4u l=2u ng=2 m=1

** --- HBT pair ---
XQ1 net_c1 net_c1 0 0 npn13G2 Nx=1
XQ2 net_c2 net_c2 net_rptat 0 npn13G2 Nx=1 m=8

** --- R_ptat ---
XRptat net_rptat 0 0 rppd w=0.5e-6 l=13e-6 b=0 m=1

** --- Startup ---
XRstart vdd net_c1 0 rppd w=0.5e-6 l=48e-6 b=7 m=1

** --- R_out for VPTAT ---
XM5 vptat net_c1 vdd vdd sg13_lv_pmos w=4u l=2u ng=2 m=1
XRout vptat 0 0 rppd w=0.5e-6 l=5.5e-6 b=2 m=1

** --- 5-stage current-starved ring VCO ---
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

** Run separate transient for each temperature
** (avoids ngspice foreach state contamination)

set temp = -40
tran 0.5n 3u uic
meas tran p_m40 TRIG v(vco_out) VAL=0.9 RISE=3 TARG v(vco_out) VAL=0.9 RISE=4
meas tran vptat_m40 FIND v(vptat) AT=1u
reset

set temp = 0
tran 0.5n 3u uic
meas tran p_0 TRIG v(vco_out) VAL=0.9 RISE=3 TARG v(vco_out) VAL=0.9 RISE=4
meas tran vptat_0 FIND v(vptat) AT=1u
reset

set temp = 27
tran 0.5n 3u uic
meas tran p_27 TRIG v(vco_out) VAL=0.9 RISE=3 TARG v(vco_out) VAL=0.9 RISE=4
meas tran vptat_27 FIND v(vptat) AT=1u
reset

set temp = 85
tran 0.5n 3u uic
meas tran p_85 TRIG v(vco_out) VAL=0.9 RISE=3 TARG v(vco_out) VAL=0.9 RISE=4
meas tran vptat_85 FIND v(vptat) AT=1u
reset

set temp = 125
tran 0.5n 3u uic
meas tran p_125 TRIG v(vco_out) VAL=0.9 RISE=3 TARG v(vco_out) VAL=0.9 RISE=4
meas tran vptat_125 FIND v(vptat) AT=1u

echo ""
echo "=== RESULTS ==="
echo "T=-40:  period, vptat"
print p_m40 vptat_m40
echo "T=0:"
print p_0 vptat_0
echo "T=27:"
print p_27 vptat_27
echo "T=85:"
print p_85 vptat_85
echo "T=125:"
print p_125 vptat_125
echo "=== DONE ==="

.endc

.end
