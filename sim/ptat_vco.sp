** L2: PTAT Current-Starved Ring VCO
** PTAT core (cascode mirror + HBT pair) → 5-stage CS ring VCO → buffer → ua[0]
** VPTAT via R_out → ua[1]
**
** Target: ~10-50 MHz output, frequency proportional to temperature

.include 'pdk.inc'

.param VDD_VAL = 1.8

** ============================================================
** PTAT CORE — Cascode mirror forces I(Q1) = I(Q2)
** ============================================================
** ΔVBE = VT·ln(N) across R_ptat → IPTAT = VT·ln(8) / R_ptat
**
** R_ptat = 6.77 kΩ (rppd w=0.5u l=13u)
** IPTAT(27°C) = 26mV × 2.079 / 6770 = ~8 µA
** IPTAT(-40°C) = 20mV × 2.079 / 6770 = ~6.1 µA
** IPTAT(125°C) = 34.3mV × 2.079 / 6770 = ~10.5 µA

** Power supply
Vdd vdd 0 DC {VDD_VAL}

** --- Mirror pair (M1/M2) ---
** Diode-connected M1 on Q1 side, M2 mirrors to Q2 side
XM1 net_d1 net_d1 vdd vdd sg13_lv_pmos w=4u l=2u ng=2 m=1
XM2 net_d2 net_d1 vdd vdd sg13_lv_pmos w=4u l=2u ng=2 m=1

** --- Cascode pair (M1c/M2c) for better matching ---
XM1c net_c1 net_cb net_d1 vdd sg13_lv_pmos w=4u l=2u ng=2 m=1
XM2c net_c2 net_cb net_d2 vdd sg13_lv_pmos w=4u l=2u ng=2 m=1

** Cascode bias: diode from M1c drain
** Simple: tie cascode gate to M1c drain (self-biased)
Vcb net_cb net_c1 DC 0

** --- HBT pair ---
** Q1: 1× npn13G2, diode-connected
XQ1 net_c1 net_c1 0 0 npn13G2 Nx=1
** Q2: 8× npn13G2 (8 parallel for area ratio N=8)
XQ2 net_c2 net_c2 net_rptat 0 npn13G2 Nx=1 m=8

** --- PTAT resistor ---
** ΔVBE = VT·ln(8) appears across R_ptat
** rppd w=0.5u l=13u → ~6.77 kΩ
XRptat net_rptat 0 0 rppd w=0.5e-6 l=13e-6 b=0 m=1

** --- Startup resistor ---
** R_start: weak pulldown to initialize mirror
** rppd w=0.5u l=48u b=7 → ~500 kΩ (high R, tiny leakage)
XRstart vdd net_d1 0 rppd w=0.5e-6 l=48e-6 b=7 m=1

** ============================================================
** IPTAT OUTPUT — R_out for VPTAT measurement
** ============================================================
** Mirror leg 3: copy IPTAT to output
XM3 net_iout net_d1 vdd vdd sg13_lv_pmos w=4u l=2u ng=2 m=1
XM3c vptat net_cb net_iout vdd sg13_lv_pmos w=4u l=2u ng=2 m=1

** R_out converts IPTAT to VPTAT voltage
** VPTAT = IPTAT × R_out
** Want VPTAT ~ 0.5V at 27°C → R_out = 0.5V / 8µA = 62.5 kΩ
** rppd w=0.5u l=13.74u b=7 → ~60 kΩ
XRout vptat 0 0 rppd w=0.5e-6 l=13.74e-6 b=7 m=1

** ============================================================
** RC DECOUPLING — clean bias for VCO
** ============================================================
** Mirror leg 4: IPTAT copy for VCO bias
XM4 net_vbias net_d1 vdd vdd sg13_lv_pmos w=4u l=2u ng=2 m=1
XM4c vco_bias net_cb net_vbias vdd sg13_lv_pmos w=4u l=2u ng=2 m=1

** RC filter on VCO bias
XRfilt vco_bias vco_bias_f 0 rppd w=0.5e-6 l=5e-6 b=0 m=1
XCdec vco_bias_f 0 cap_cmim w=5e-6 l=5e-6 m=1

** ============================================================
** 5-STAGE CURRENT-STARVED RING VCO
** ============================================================
** Each stage: PMOS pull-up (current-limited) + NMOS pull-down (current-limited)
** Bias PMOS mirrors IPTAT → controls delay → controls frequency
**
** Stage structure:
**   VDD → M_pb (bias, gate=vco_bias_f) → M_pu (inverter PMOS) → out → M_pd (inverter NMOS) → M_nb (bias) → GND
**
** Bias distribution:
**   M_pb gate = vco_bias_f (PTAT current)
**   M_nb gate = generated from diode-connected NMOS

** NMOS bias generation: mirror IPTAT through NMOS diode
XMnb_d vco_nbias vco_nbias 0 0 sg13_lv_nmos w=2u l=1u ng=1 m=1
XMnb_drv vco_nbias net_d1 vdd vdd sg13_lv_pmos w=4u l=2u ng=2 m=1
XMnbc_drv net_nb_cas net_cb vco_nbias vdd sg13_lv_pmos w=4u l=2u ng=2 m=1
** Wait, this is getting complex. Simplify: just use PMOS current starving only.

** Simplified: current-starved inverter with PMOS bias only
** VDD → M_pb (gate=vco_bias_f) → node_s → PMOS inv → out → NMOS inv → GND

** Stage 1
XMpb1 ns1 vco_bias_f vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMpu1 vco1 vco5 ns1 vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMpd1 vco1 vco5 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1

** Stage 2
XMpb2 ns2 vco_bias_f vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMpu2 vco2 vco1 ns2 vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMpd2 vco2 vco1 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1

** Stage 3
XMpb3 ns3 vco_bias_f vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMpu3 vco3 vco2 ns3 vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMpd3 vco3 vco2 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1

** Stage 4
XMpb4 ns4 vco_bias_f vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMpu4 vco4 vco3 ns4 vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMpd4 vco4 vco3 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1

** Stage 5 (feeds back to stage 1)
XMpb5 ns5 vco_bias_f vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMpu5 vco5 vco4 ns5 vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMpd5 vco5 vco4 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1

** ============================================================
** OUTPUT BUFFER — 2 inverter stages to sharpen edges
** ============================================================
XMbp1 buf1 vco5 vdd vdd sg13_lv_pmos w=4u l=0.5u ng=1 m=1
XMbn1 buf1 vco5 0 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1

XMbp2 vco_out buf1 vdd vdd sg13_lv_pmos w=8u l=0.5u ng=2 m=1
XMbn2 vco_out buf1 0 0 sg13_lv_nmos w=4u l=0.5u ng=2 m=1

** ============================================================
** ANALYSIS
** ============================================================
.control

** --- Transient: check oscillation at 27°C ---
set temp = 27
tran 0.5n 2u uic
meas tran t1 TRIG v(vco_out) VAL=0.9 RISE=3 TARG v(vco_out) VAL=0.9 RISE=4
let freq_27 = 1/t1
print freq_27
print v(vptat)

** --- Temperature sweep: measure frequency vs temp ---
let temps = vector(7)
let freqs = vector(7)
let vptats = vector(7)
let idx = 0

foreach temp_val -40 -20 0 27 50 85 125
  set temp = $temp_val
  tran 0.5n 3u uic
  meas tran period TRIG v(vco_out) VAL=0.9 RISE=5 TARG v(vco_out) VAL=0.9 RISE=6
  let f = 1/period
  print $temp_val f v(vptat)
  destroy all
end

.endc

.end
