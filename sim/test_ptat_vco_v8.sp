** L2 PTAT+VCO v8 — Direct R-bias approach
** Instead of current-mirroring, use VPTAT voltage directly as VCO control
** VCO: 5-stage with both sides current-starved by a single shared bias rail
** Bias rail voltage = VPTAT = IPTAT × R_out → tracks temperature
.include 'pdk.inc'

.param VDD_VAL = 1.8
Vdd vdd 0 DC {VDD_VAL}

** PTAT CORE (simple mirror — gives ~38µA at 27°C)
XM1 net_c1 net_c1 vdd vdd sg13_lv_pmos w=4u l=2u ng=2 m=1
XM2 net_c2 net_c1 vdd vdd sg13_lv_pmos w=4u l=2u ng=2 m=1
XQ1 net_c1 net_c1 0 0 npn13G2 Nx=1
XQ2 net_c2 net_c2 net_rptat 0 npn13G2 Nx=1 m=8
XRptat net_rptat 0 0 rppd w=0.5e-6 l=13e-6 b=0 m=1
XRstart vdd net_c1 0 rppd w=0.5e-6 l=48e-6 b=7 m=1

** VPTAT for measurement: ua[1]
XM5 vptat net_c1 vdd vdd sg13_lv_pmos w=4u l=2u ng=2 m=1
XRout vptat 0 0 rppd w=0.5e-6 l=5.5e-6 b=2 m=1

** NMOS BIAS (mirror IPTAT to NMOS)
XM3 nmos_bias net_c1 vdd vdd sg13_lv_pmos w=4u l=2u ng=2 m=1
XMnb_d nmos_bias nmos_bias 0 0 sg13_lv_nmos w=2u l=1u ng=1 m=1

** ============================================================
** 5-STAGE VCO — asymmetric: fast PMOS pull-up, slow NMOS pull-down
** ============================================================
** Key insight: make PMOS pull-up much stronger than NMOS pull-down
** so the delay is dominated by NMOS (current-starved) discharge
** Rise time << fall time → frequency ≈ N / (fall_time)
** fall_time ∝ C·V / I_nmos → frequency ∝ I_nmos ∝ IPTAT

** No caps (smaller, faster, MOSFET Cgate is the load)
** PMOS: W=4u L=0.5u (strong, fast pull-up)
** NMOS inverter: W=0.5u L=0.5u (weak, but fast when ON)
** NMOS bias: W=1u L=4u (current-limited by PTAT)

** Stage 1
XMpu1 vco1 vco5 vdd vdd sg13_lv_pmos w=4u l=0.5u ng=1 m=1
XMpd1 vco1 vco5 ns1 0 sg13_lv_nmos w=0.5u l=0.5u ng=1 m=1
XMnb1 ns1 nmos_bias 0 0 sg13_lv_nmos w=1u l=2.5u ng=1 m=1

** Stage 2
XMpu2 vco2 vco1 vdd vdd sg13_lv_pmos w=4u l=0.5u ng=1 m=1
XMpd2 vco2 vco1 ns2 0 sg13_lv_nmos w=0.5u l=0.5u ng=1 m=1
XMnb2 ns2 nmos_bias 0 0 sg13_lv_nmos w=1u l=2.5u ng=1 m=1

** Stage 3
XMpu3 vco3 vco2 vdd vdd sg13_lv_pmos w=4u l=0.5u ng=1 m=1
XMpd3 vco3 vco2 ns3 0 sg13_lv_nmos w=0.5u l=0.5u ng=1 m=1
XMnb3 ns3 nmos_bias 0 0 sg13_lv_nmos w=1u l=2.5u ng=1 m=1

** Stage 4
XMpu4 vco4 vco3 vdd vdd sg13_lv_pmos w=4u l=0.5u ng=1 m=1
XMpd4 vco4 vco3 ns4 0 sg13_lv_nmos w=0.5u l=0.5u ng=1 m=1
XMnb4 ns4 nmos_bias 0 0 sg13_lv_nmos w=1u l=2.5u ng=1 m=1

** Stage 5
XMpu5 vco5 vco4 vdd vdd sg13_lv_pmos w=4u l=0.5u ng=1 m=1
XMpd5 vco5 vco4 ns5 0 sg13_lv_nmos w=0.5u l=0.5u ng=1 m=1
XMnb5 ns5 nmos_bias 0 0 sg13_lv_nmos w=1u l=2.5u ng=1 m=1

** Buffer
XMbp1 buf1 vco5 vdd vdd sg13_lv_pmos w=4u l=0.5u ng=1 m=1
XMbn1 buf1 vco5 0 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XMbp2 vco_out buf1 vdd vdd sg13_lv_pmos w=8u l=0.5u ng=2 m=1
XMbn2 vco_out buf1 0 0 sg13_lv_nmos w=4u l=0.5u ng=2 m=1

.option itl1=500 itl4=200

.control

echo "=== L2 PTAT+VCO v8: Asymmetric fast-PMOS / slow-NMOS ==="

** Test 4 temperatures
foreach temp_val -40 27 85 125
  set temp = $temp_val
  tran 0.5n 3u uic
  meas tran period TRIG v(vco_out) VAL=0.9 RISE=3 TARG v(vco_out) VAL=0.9 RISE=4
  meas tran vptat_v FIND v(vptat) AT=1u
  meas tran vnb_v FIND v(nmos_bias) AT=1u
  destroy all
end

echo "=== DONE ==="
.endc

.end
