** SoilZ Block Test 1: PTAT Core + VCO
** Verify: VCO frequency 7-11 MHz, VPTAT monotonic
** Mirror L=50µm (area compromise)
.include '_pdk_corner.inc'

** PTAT Mirror
XPM3 net_c1 net_c1 vdd vdd sg13_lv_pmos w=0.5u l=50u ng=1 m=1
XPM4 net_c2 net_c1 vdd vdd sg13_lv_pmos w=0.5u l=50u ng=1 m=1
XPM5 vptat net_c1 vdd vdd sg13_lv_pmos w=0.5u l=50u ng=1 m=1
XPM_ref nmos_bias net_c1 vdd vdd sg13_lv_pmos w=0.5u l=50u ng=1 m=1

** Vittoz NMOS
XMN1 net_c1 net_c1 0 0 sg13_lv_nmos w=2u l=4u ng=1 m=1
XMN2 net_c2 net_c1 net_rptat 0 sg13_lv_nmos w=16u l=4u ng=8 m=1

** Bias gen
XMN_diode nmos_bias nmos_bias 0 0 sg13_lv_nmos w=1u l=2u ng=1 m=1
XMN_pgen pmos_bias nmos_bias 0 0 sg13_lv_nmos w=1u l=2u ng=1 m=1
XPM_pdiode pmos_bias pmos_bias vdd vdd sg13_lv_pmos w=0.5u l=2u ng=1 m=1

** VCO: 5-stage current-starved ring
XMpb1 ns1 pmos_bias vdd vdd sg13_lv_pmos w=20u l=0.13u ng=8 m=1
XMpu1 vco1 vco5 ns1 vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMpd1 vco1 vco5 nb1 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XMnb1 nb1 nmos_bias 0 0 sg13_lv_nmos w=20u l=0.13u ng=8 m=1

XMpb2 ns2 pmos_bias vdd vdd sg13_lv_pmos w=20u l=0.13u ng=8 m=1
XMpu2 vco2 vco1 ns2 vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMpd2 vco2 vco1 nb2 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XMnb2 nb2 nmos_bias 0 0 sg13_lv_nmos w=20u l=0.13u ng=8 m=1

XMpb3 ns3 pmos_bias vdd vdd sg13_lv_pmos w=20u l=0.13u ng=8 m=1
XMpu3 vco3 vco2 ns3 vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMpd3 vco3 vco2 nb3 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XMnb3 nb3 nmos_bias 0 0 sg13_lv_nmos w=20u l=0.13u ng=8 m=1

XMpb4 ns4 pmos_bias vdd vdd sg13_lv_pmos w=20u l=0.13u ng=8 m=1
XMpu4 vco4 vco3 ns4 vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMpd4 vco4 vco3 nb4 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XMnb4 nb4 nmos_bias 0 0 sg13_lv_nmos w=20u l=0.13u ng=8 m=1

XMpb5 ns5 pmos_bias vdd vdd sg13_lv_pmos w=20u l=0.13u ng=8 m=1
XMpu5 vco5 vco4 ns5 vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMpd5 vco5 vco4 nb5 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XMnb5 nb5 nmos_bias 0 0 sg13_lv_nmos w=20u l=0.13u ng=8 m=1

** Buffer
XMBp1 buf1 vco5 vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMBn1 buf1 vco5 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XMBp2 vco_out buf1 vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMBn2 vco_out buf1 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1

** Resistors
XRptat net_rptat 0 0 rhigh w=0.5e-6 l=133e-6 b=12 m=1
XRout vptat 0 0 rppd w=0.5e-6 l=25e-6 b=4 m=1

Vdd vdd 0 1.2

.ic v(net_c1)=0.25 v(net_c2)=0.9
.ic v(vco1)=0 v(vco2)=1.2 v(vco3)=0 v(vco4)=1.2 v(vco5)=0

.tran 1n 15u uic

.control
run
echo ""
echo "=== SoilZ PTAT+VCO Block Test (L=50µm) ==="

* VCO frequency
meas tran vco_period trig v(vco_out) val=0.6 rise=5 targ v(vco_out) val=0.6 rise=6
if (vco_period > 0)
  let freq_mhz = 1/vco_period/1e6
  echo "VCO Frequency = $&freq_mhz MHz"
  if (freq_mhz > 7 && freq_mhz < 11)
    echo "  --> PASS (7-11 MHz range)"
  else
    echo "  --> FAIL (outside 7-11 MHz)"
  end
end

* VPTAT at end
meas tran vptat_final find v(vptat) at=14u
echo "VPTAT = $&vptat_final V"

* Bias points
meas tran v_nc1 find v(net_c1) at=14u
meas tran v_nmos find v(nmos_bias) at=14u
meas tran v_pmos find v(pmos_bias) at=14u

echo ""
echo "=== Bias Points ==="
echo "net_c1 = $&v_nc1 V"
echo "nmos_bias = $&v_nmos V"
echo "pmos_bias = $&v_pmos V"
echo "=== Done ==="
quit
.endc

.end
