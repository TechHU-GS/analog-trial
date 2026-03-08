** L2: CMOS Dual Current-Starved Ring VCO + VPTAT
**
** Architecture:
**   Vittoz PTAT core → NMOS bias (PM_ref → MN_diode → nmos_bias)
**                     → PMOS bias (MN_pgen → PM_pdiode → pmos_bias)
**   5-stage ring VCO with BOTH sides current-starved
**   Buffer → ua[0] (digital frequency output)
**   VPTAT via PM5 + Rout → ua[1] (analog PTAT voltage)
**
** VCO frequency is CTAT due to MOSFET mobility degradation
** dominating the PTAT current increase.
** Temperature calibration via VPTAT output (monotonic PTAT voltage).
**
** ALL SG13CMOS devices — no BJT/HBT
** IHP SG13G2 130nm, TTIHP 26a, 1x2 tile
**
** RESIZE v2: Rptat rppd l=769u → rhigh l=133u b=12 (same R ≈ 5.1 MOhm)
** Mirror L=100u kept (critical for PTAT accuracy)

.include 'pdk.inc'

.param VDD_VAL = 1.8

** Power supply
Vdd vdd 0 DC {VDD_VAL}

** ============================================================
** PTAT CORE — Vittoz topology
** ============================================================
** MN1 (1x) diode-connected, MN2 (8x) common-gate (gate=net_c1)
** KVL: DVGS = VGS1 - VGS2 = I*R → I = n*VT*ln(N)/R (PTAT)
**
** Rptat: rhigh w=0.5u l=133u b=12 (R ≈ 5.1 MOhm)

** --- PMOS mirror (PM3 diode, PM4 mirror) ---
XPM3 net_c1 net_c1 vdd vdd sg13_lv_pmos w=0.5u l=100u ng=1 m=1
XPM4 net_c2 net_c1 vdd vdd sg13_lv_pmos w=0.5u l=100u ng=1 m=1

** --- NMOS pair — Vittoz ---
XMN1 net_c1 net_c1 0 0 sg13_lv_nmos w=2u l=4u ng=1 m=1
XMN2 net_c2 net_c1 net_rptat 0 sg13_lv_nmos w=16u l=4u ng=8 m=1

** --- PTAT resistor (rhigh: Rs≈1360 Ohm/sq, TC1≈-2300 ppm/C) ---
XRptat net_rptat 0 0 rhigh w=0.5e-6 l=133e-6 b=12 m=1

** ============================================================
** NMOS BIAS GENERATION
** ============================================================
** PM_ref (L=10u) mirrors PTAT current into diode-connected MN_diode
XPM_ref nmos_bias net_c1 vdd vdd sg13_lv_pmos w=0.5u l=100u ng=1 m=1
XMN_diode nmos_bias nmos_bias 0 0 sg13_lv_nmos w=1u l=2u ng=1 m=1
XCbyp_n nmos_bias 0 cap_cmim w=5e-6 l=5e-6 m=1

** ============================================================
** PMOS BIAS GENERATION
** ============================================================
** MN_pgen mirrors PTAT current → sinks through diode-connected PM_pdiode
** PM_pdiode same W/L as VCO PMOS current sources → accurate mirror
XMN_pgen pmos_bias nmos_bias 0 0 sg13_lv_nmos w=1u l=2u ng=1 m=1
XPM_pdiode pmos_bias pmos_bias vdd vdd sg13_lv_pmos w=0.5u l=2u ng=1 m=1
XCbyp_p pmos_bias 0 cap_cmim w=5e-6 l=5e-6 m=1

** ============================================================
** 5-STAGE DUAL CURRENT-STARVED RING VCO
** ============================================================
** Top:    PMOS CS (gate=pmos_bias, W=4u L=2u, ng=8)
** Bottom: NMOS CS (gate=nmos_bias, W=8u L=2u, ng=8)
** Inverter: PMOS W=2u L=0.5u, NMOS W=1u L=0.5u

** Stage 1
XMpb1 ns1 pmos_bias vdd vdd sg13_lv_pmos w=4u l=2u ng=8 m=1
XMpu1 vco1 vco5 ns1 vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMpd1 vco1 vco5 nb1 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XMnb1 nb1 nmos_bias 0 0 sg13_lv_nmos w=8u l=2u ng=8 m=1

** Stage 2
XMpb2 ns2 pmos_bias vdd vdd sg13_lv_pmos w=4u l=2u ng=8 m=1
XMpu2 vco2 vco1 ns2 vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMpd2 vco2 vco1 nb2 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XMnb2 nb2 nmos_bias 0 0 sg13_lv_nmos w=8u l=2u ng=8 m=1

** Stage 3
XMpb3 ns3 pmos_bias vdd vdd sg13_lv_pmos w=4u l=2u ng=8 m=1
XMpu3 vco3 vco2 ns3 vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMpd3 vco3 vco2 nb3 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XMnb3 nb3 nmos_bias 0 0 sg13_lv_nmos w=8u l=2u ng=8 m=1

** Stage 4
XMpb4 ns4 pmos_bias vdd vdd sg13_lv_pmos w=4u l=2u ng=8 m=1
XMpu4 vco4 vco3 ns4 vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMpd4 vco4 vco3 nb4 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XMnb4 nb4 nmos_bias 0 0 sg13_lv_nmos w=8u l=2u ng=8 m=1

** Stage 5
XMpb5 ns5 pmos_bias vdd vdd sg13_lv_pmos w=4u l=2u ng=8 m=1
XMpu5 vco5 vco4 ns5 vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMpd5 vco5 vco4 nb5 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XMnb5 nb5 nmos_bias 0 0 sg13_lv_nmos w=8u l=2u ng=8 m=1

** ============================================================
** OUTPUT BUFFER — 2 inverter stages
** ============================================================
XMbp1 buf1 vco5 vdd vdd sg13_lv_pmos w=4u l=0.5u ng=1 m=1
XMbn1 buf1 vco5 0 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1

XMbp2 vco_out buf1 vdd vdd sg13_lv_pmos w=8u l=0.5u ng=2 m=1
XMbn2 vco_out buf1 0 0 sg13_lv_nmos w=4u l=0.5u ng=2 m=1

** ============================================================
** VPTAT OUTPUT — ua[1]
** ============================================================
XPM5 vptat net_c1 vdd vdd sg13_lv_pmos w=0.5u l=100u ng=1 m=1
XRout vptat 0 0 rppd w=0.5e-6 l=25e-6 b=4 m=1

** ============================================================
** CONVERGENCE AIDS
** ============================================================
.nodeset v(net_c1) = 0.25 v(net_c2) = 1.5 v(nmos_bias) = 0.3 v(pmos_bias) = 1.5
.ic v(net_c1)=0.244 v(net_c2)=1.73 v(nmos_bias)=0.26 v(pmos_bias)=1.5
.ic v(vco1)=0 v(vco2)=1.8 v(vco3)=0 v(vco4)=1.8 v(vco5)=0
.option itl1=500 itl4=200

** ============================================================
** ANALYSIS
** ============================================================
.control

** --- DC operating point @ 27C ---
set temp = 27
op
echo "============================================================"
echo "CMOS Dual-CS VCO — DC @ 27C"
echo "============================================================"
echo "  V(net_c1)    = $&v(net_c1) V"
echo "  V(net_c2)    = $&v(net_c2) V"
echo "  V(net_rptat) = $&v(net_rptat) V  (DVGS)"
echo "  V(nmos_bias) = $&v(nmos_bias) V"
echo "  V(pmos_bias) = $&v(pmos_bias) V"
echo "  V(vptat)     = $&v(vptat) V"
echo "  I(VDD)       = $&@vdd[i] A"
destroy all

** --- Transient @ 27C ---
set temp = 27
tran 1n 15u uic

meas tran v5max MAX v(vco5)
meas tran v5min MIN v(vco5)
echo ""
echo "vco5 swing: $&v5min to $&v5max V"

meas tran voutmax MAX v(vco_out)
meas tran voutmin MIN v(vco_out)
echo "vco_out swing: $&voutmin to $&voutmax V"

meas tran period TRIG v(vco_out) VAL=0.9 RISE=5 TARG v(vco_out) VAL=0.9 RISE=6
if ( period > 0 )
  let freq = 1/period / 1e6
  echo "Freq = $&freq MHz"
else
  echo "NO OSCILLATION at 27C"
end
destroy all

** --- Temperature sweep ---
echo ""
echo "============================================================"
echo "Temperature sweep (tt/typ)"
echo "============================================================"

foreach temp_val -40 -20 0 27 50 85 125
  set temp = $temp_val
  tran 1n 15u uic
  meas tran p TRIG v(vco_out) VAL=0.9 RISE=5 TARG v(vco_out) VAL=0.9 RISE=6
  if ( p > 0 )
    let f = 1/p / 1e6
    echo "$temp_val $&f"
  else
    echo "$temp_val NO_OSC"
  end
  destroy all
end

echo ""
echo "Columns: Temp(C) Freq(MHz)"

.endc

.end
