** SoilZ v1 functional simulation
** sel0/1/2 = VDD (all current sources ON), probe = 1kΩ resistor
** Tests: VCO oscillation, H-bridge excitation, chopper+OTA+comparator, ΣΔ bitstream

.include '_pdk_corner.inc'
.param VDD_VAL = 1.2

** Power
Vdd vdd 0 DC {VDD_VAL}

** Control pins: sel = VDD (all current sources ON)
Vsel0 sel0 0 DC {VDD_VAL}
Vsel1 sel1 0 DC {VDD_VAL}
Vsel2 sel2 0 DC {VDD_VAL}
Vsel0b sel0b 0 DC 0
Vsel1b sel1b 0 DC 0
Vsel2b sel2b 0 DC 0

** Reference voltages
Vref_ota vref_ota 0 DC 0.6
Vref_comp vref_comp 0 DC 0.6
Vbias_n bias_n 0 DC 0.5
Vdac_hi dac_hi 0 DC 0.95
Vdac_lo dac_lo 0 DC 0.85

** External probe: 1kΩ between probe_p and probe_n
Rprobe probe_p probe_n 1k

** Chopper: sens = probe (2-wire mode)
Vsens_p sens_p probe_p DC 0
Vsens_n sens_n probe_n DC 0

** Divider control
Vfreq_sel freq_sel 0 DC {VDD_VAL}
Viq_sel iq_sel 0 DC 0

** Comparator clock from VCO (internal)
Vcomp_clk comp_clk vco_out DC 0

** Reset (active low, release after 1us)
Vrst reset_b 0 PULSE(0 {VDD_VAL} 1u 10n 10n 100u 200u)

** === CIRCUIT (from _soilz_full.sp) ===
** PTAT core
XPM3 net_c1 net_c1 vdd vdd sg13_lv_pmos w=0.5u l=10u ng=1 m=1
XPM4 net_c2 net_c1 vdd vdd sg13_lv_pmos w=0.5u l=10u ng=1 m=1
XMN1 net_c1 net_c1 0 0 sg13_lv_nmos w=2u l=4u ng=1 m=1
XMN2 net_c2 net_c1 net_rptat 0 sg13_lv_nmos w=16u l=4u ng=8 m=1
XRptat net_rptat 0 0 rhigh w=0.5e-6 l=133.0e-6 b=12 m=1
XPM_ref nmos_bias net_c1 vdd vdd sg13_lv_pmos w=0.5u l=10u ng=1 m=1
XMN_diode nmos_bias nmos_bias 0 0 sg13_lv_nmos w=1u l=2u ng=1 m=1
XMN_pgen pmos_bias nmos_bias 0 0 sg13_lv_nmos w=1u l=2u ng=1 m=1
XPM_pdiode pmos_bias pmos_bias vdd vdd sg13_lv_pmos w=0.5u l=2u ng=1 m=1
XPM5 vptat net_c1 vdd vdd sg13_lv_pmos w=0.5u l=10u ng=1 m=1
XRout vptat 0 0 rppd w=0.5e-6 l=25.0e-6 b=4 m=1

** VCO 5-stage
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
XMBp1 buf1 vco5 vdd vdd sg13_lv_pmos w=4u l=0.5u ng=1 m=1
XMBn1 buf1 vco5 0 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XMBp2 vco_out buf1 vdd vdd sg13_lv_pmos w=8u l=0.5u ng=2 m=1
XMBn2 vco_out buf1 0 0 sg13_lv_nmos w=4u l=0.5u ng=2 m=1

** Cascode current source
XPM_cas_ref cas_ref net_c1 vdd vdd sg13_lv_pmos w=1u l=10u ng=1 m=1
XPM_cas_diode vcas vcas cas_ref vdd sg13_lv_pmos w=1u l=2u ng=1 m=1
XMN_cas_load vcas vcas 0 0 sg13_lv_nmos w=0.5u l=2u ng=1 m=1
XPM_mir1 cas1 net_c1 vdd vdd sg13_lv_pmos w=1u l=10u ng=1 m=1
XPM_cas1 src1 vcas cas1 vdd sg13_lv_pmos w=1u l=2u ng=1 m=1
XPM_mir2 cas2 net_c1 vdd vdd sg13_lv_pmos w=2u l=10u ng=1 m=1
XPM_cas2 src2 vcas cas2 vdd sg13_lv_pmos w=2u l=2u ng=1 m=1
XPM_mir3 cas3 net_c1 vdd vdd sg13_lv_pmos w=4u l=10u ng=2 m=1
XPM_cas3 src3 vcas cas3 vdd sg13_lv_pmos w=4u l=2u ng=2 m=1

** SW (TG switches) — sel = VDD → all ON
XSW1n src1 sel0 exc_out 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XSW1p src1 sel0b exc_out vdd sg13_lv_pmos w=4u l=0.5u ng=1 m=1
XSW2n src2 sel1 exc_out 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XSW2p src2 sel1b exc_out vdd sg13_lv_pmos w=4u l=0.5u ng=1 m=1
XSW3n src3 sel2 exc_out 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XSW3p src3 sel2b exc_out vdd sg13_lv_pmos w=4u l=0.5u ng=1 m=1

** Non-overlap clock generator
XM_inv0_n f_exc_b f_exc 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XM_inv0_p f_exc_b f_exc vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XM_da1_n da1 f_exc 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XM_da1_p da1 f_exc vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XM_da2_n f_exc_d da1 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XM_da2_p f_exc_d da1 vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XM_db1_n db1 f_exc_b 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XM_db1_p db1 f_exc_b vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XM_db2_n f_exc_b_d db1 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XM_db2_p f_exc_b_d db1 vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XM_na_p1 nand_a f_exc vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XM_na_p2 nand_a f_exc_d vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XM_na_n1 nand_a f_exc na_mid 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XM_na_n2 na_mid f_exc_d 0 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XM_ia_n phi_p nand_a 0 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XM_ia_p phi_p nand_a vdd vdd sg13_lv_pmos w=4u l=0.5u ng=1 m=1
XM_nb_p1 nand_b f_exc_b vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XM_nb_p2 nand_b f_exc_b_d vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XM_nb_n1 nand_b f_exc_b nb_mid 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XM_nb_n2 nb_mid f_exc_b_d 0 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XM_ib_n phi_n nand_b 0 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XM_ib_p phi_n nand_b vdd vdd sg13_lv_pmos w=4u l=0.5u ng=1 m=1

** H-bridge
XMS1 exc_out phi_p probe_p 0 sg13_lv_nmos w=4u l=0.5u ng=2 m=1
XMS2 0 phi_n probe_p 0 sg13_lv_nmos w=4u l=0.5u ng=2 m=1
XMS3 exc_out phi_n probe_n 0 sg13_lv_nmos w=4u l=0.5u ng=2 m=1
XMS4 0 phi_p probe_n 0 sg13_lv_nmos w=4u l=0.5u ng=2 m=1

** Chopper
XMchop1n sens_p f_exc chop_out 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XMchop1p sens_p f_exc_b chop_out vdd sg13_lv_pmos w=4u l=0.5u ng=1 m=1
XMchop2n sens_n f_exc_b chop_out 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XMchop2p sens_n f_exc chop_out vdd sg13_lv_pmos w=4u l=0.5u ng=1 m=1

** OTA
XMbias_d bias_n bias_n 0 0 sg13_lv_nmos w=4u l=4u ng=1 m=1
XMp_load_p mid_p mid_p vdd vdd sg13_lv_pmos w=4u l=4u ng=1 m=1
XMp_load_n ota_out mid_p vdd vdd sg13_lv_pmos w=4u l=4u ng=1 m=1
XMin_p mid_p vref_ota tail 0 sg13_lv_nmos w=10u l=2u ng=4 m=1
XMin_n ota_out sum_n tail 0 sg13_lv_nmos w=10u l=2u ng=4 m=1
XMtail tail bias_n 0 0 sg13_lv_nmos w=8u l=4u ng=2 m=1

** Comparator
XMc_tail c_tail comp_clk 0 0 sg13_lv_nmos w=4u l=0.5u ng=2 m=1
XMc_inp c_di_p ota_out c_tail 0 sg13_lv_nmos w=4u l=0.5u ng=2 m=1
XMc_inn c_di_n vref_comp c_tail 0 sg13_lv_nmos w=4u l=0.5u ng=2 m=1
XMc_rst_dp c_di_p comp_clk vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMc_rst_dn c_di_n comp_clk vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMc_ln1 comp_outp comp_outn c_di_p 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XMc_ln2 comp_outn comp_outp c_di_n 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XMc_lp1 comp_outp comp_outn vdd vdd sg13_lv_pmos w=1u l=0.5u ng=1 m=1
XMc_lp2 comp_outn comp_outp vdd vdd sg13_lv_pmos w=1u l=0.5u ng=1 m=1
XMc_rst_op comp_outp comp_clk vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMc_rst_on comp_outn comp_clk vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1

** SR Latch
XMn1a n1_mid comp_outp 0 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XMp1a lat_q comp_outp vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMn1b lat_q lat_qb n1_mid 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XMp1b lat_q lat_qb vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMn2a n2_mid comp_outn 0 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XMp2a lat_qb comp_outn vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMn2b lat_qb lat_q n2_mid 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XMp2b lat_qb lat_q vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1

** DAC (TG)
XMdac_tg1n dac_hi lat_q dac_out 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XMdac_tg1p dac_hi lat_qb dac_out vdd sg13_lv_pmos w=4u l=0.5u ng=1 m=1
XMdac_tg2n dac_lo lat_qb dac_out 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XMdac_tg2p dac_lo lat_q dac_out vdd sg13_lv_pmos w=4u l=0.5u ng=1 m=1

** Passives
XRin chop_out sum_n 0 rhigh w=0.5e-6 l=20.0e-6 b=2 m=1
XRdac dac_out sum_n 0 rhigh w=0.5e-6 l=20.0e-6 b=2 m=1
XC_fb ota_out sum_n cap_cmim w=26.0e-6 l=26.0e-6 m=1
XCbyp_n nmos_bias 0 cap_cmim w=5.0e-6 l=5.0e-6 m=1
XCbyp_p pmos_bias vdd cap_cmim w=5.0e-6 l=5.0e-6 m=1

** Simulation
.option method=gear
.option reltol=0.01
.option abstol=1e-10
.option gmin=1e-10
.ic v(vco1)=0 v(vco2)=1.2 v(vco3)=0 v(vco4)=1.2 v(vco5)=0

.tran 1n 50u uic

.end
