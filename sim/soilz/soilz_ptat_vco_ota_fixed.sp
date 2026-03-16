** SoilZ: PTAT+VCO+OTA+Comparator (core analog path)
** 约 80 devices — verify bias chain + signal path
.include '_pdk_corner.inc'
.option method=gear reltol=0.003 abstol=1e-12 vntol=1e-6

** PTAT Mirror (L=50µm)
XPM3 net_c1 net_c1 vdd vdd sg13_lv_pmos w=0.5u l=50u ng=1 m=1
XPM4 net_c2 net_c1 vdd vdd sg13_lv_pmos w=0.5u l=50u ng=1 m=1
XPM5 vptat net_c1 vdd vdd sg13_lv_pmos w=0.5u l=50u ng=1 m=1
XPM_ref nmos_bias net_c1 vdd vdd sg13_lv_pmos w=0.5u l=50u ng=1 m=1
XMN1 net_c1 net_c1 0 0 sg13_lv_nmos w=2u l=4u ng=1 m=1
XMN2 net_c2 net_c1 net_rptat 0 sg13_lv_nmos w=16u l=4u ng=8 m=1
XMN_diode nmos_bias nmos_bias 0 0 sg13_lv_nmos w=1u l=2u ng=1 m=1
XMN_pgen pmos_bias nmos_bias 0 0 sg13_lv_nmos w=1u l=2u ng=1 m=1
XPM_pdiode pmos_bias pmos_bias vdd vdd sg13_lv_pmos w=0.5u l=2u ng=1 m=1
XRptat net_rptat 0 0 rhigh w=0.5e-6 l=133e-6 b=12 m=1
XRout vptat 0 0 rppd w=0.5e-6 l=25e-6 b=4 m=1

** Bypass caps
XCbyp_n nmos_bias 0 cap_cmim w=5e-6 l=5e-6 m=1
XCbyp_p pmos_bias 0 cap_cmim w=5e-6 l=5e-6 m=1

** Bias mirror for OTA
XM_bias_mir bias_n pmos_bias vdd vdd sg13_lv_pmos w=0.5u l=2u ng=1 m=1

** VCO (5-stage)
XMpb1 ns1 pmos_bias vdd vdd sg13_lv_pmos w=4u l=2u ng=8 m=1
XMpu1 vco1 vco5 ns1 vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMpd1 vco1 vco5 nb1 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XMnb1 nb1 nmos_bias 0 0 sg13_lv_nmos w=8u l=2u ng=8 m=1
XMpb2 ns2 pmos_bias vdd vdd sg13_lv_pmos w=4u l=2u ng=8 m=1
XMpu2 vco2 vco1 ns2 vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMpd2 vco2 vco1 nb2 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XMnb2 nb2 nmos_bias 0 0 sg13_lv_nmos w=8u l=2u ng=8 m=1
XMpb3 ns3 pmos_bias vdd vdd sg13_lv_pmos w=4u l=2u ng=8 m=1
XMpu3 vco3 vco2 ns3 vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMpd3 vco3 vco2 nb3 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XMnb3 nb3 nmos_bias 0 0 sg13_lv_nmos w=8u l=2u ng=8 m=1
XMpb4 ns4 pmos_bias vdd vdd sg13_lv_pmos w=4u l=2u ng=8 m=1
XMpu4 vco4 vco3 ns4 vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMpd4 vco4 vco3 nb4 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XMnb4 nb4 nmos_bias 0 0 sg13_lv_nmos w=8u l=2u ng=8 m=1
XMpb5 ns5 pmos_bias vdd vdd sg13_lv_pmos w=4u l=2u ng=8 m=1
XMpu5 vco5 vco4 ns5 vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMpd5 vco5 vco4 nb5 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XMnb5 nb5 nmos_bias 0 0 sg13_lv_nmos w=8u l=2u ng=8 m=1

** Buffer
XMBp1 buf1 vco5 vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMBn1 buf1 vco5 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XMBp2 vco_out buf1 vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMBn2 vco_out buf1 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1

** OTA
XMp_load_p mid_p mid_p vdd vdd sg13_lv_pmos w=4u l=4u ng=1 m=1
XMp_load_n ota_out mid_p vdd vdd sg13_lv_pmos w=4u l=4u ng=1 m=1
XMin_p mid_p sum_n tail 0 sg13_lv_nmos w=10u l=2u ng=4 m=1
XMin_n ota_out sum_n tail 0 sg13_lv_nmos w=10u l=2u ng=4 m=1
XMtail tail bias_n 0 0 sg13_lv_nmos w=8u l=4u ng=2 m=1
XMbias_d bias_n bias_n 0 0 sg13_lv_nmos w=4u l=4u ng=1 m=1

** Integrator passives
XC_fb ota_out sum_n cap_cmim w=26e-6 l=26e-6 m=1
XRin chop_in sum_n 0 rhigh w=0.5e-6 l=20e-6 b=2 m=1
XRdac dac_in sum_n 0 rhigh w=0.5e-6 l=20e-6 b=2 m=1

** Test stimulus
Vdd vdd 0 1.2
Vchop chop_in 0 0.6
Vdac dac_in 0 0.9

.ic v(vco1)=0 v(vco2)=1.2 v(vco3)=0 v(vco4)=1.2 v(vco5)=0
.ic v(net_c1)=0.244 v(net_c2)=1.73 v(nmos_bias)=0.26 v(pmos_bias)=1.27
.ic v(bias_n)=0.26 v(ota_out)=0.6 v(sum_n)=0.6

.tran 1n 15u uic

.meas tran vco_freq trig v(vco_out) val=0.6 rise=10 targ v(vco_out) val=0.6 rise=11
.meas tran vptat_end find v(vptat) at=14u
.meas tran bias_n_end find v(bias_n) at=14u
.meas tran ota_out_end find v(ota_out) at=14u
.meas tran sum_n_end find v(sum_n) at=14u

.end
