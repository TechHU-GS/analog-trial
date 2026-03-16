** SoilZ v1: 250-device transient (batch mode, no .control)
.include '_pdk_corner.inc'
.option method=gear reltol=0.003 abstol=1e-12 vntol=1e-6

.ic v(vco1)=0 v(vco2)=1.2 v(vco3)=0 v(vco4)=1.2 v(vco5)=0
.ic v(net_c1)=0.25 v(net_c2)=0.9 v(nmos_bias)=0.3 v(pmos_bias)=1.2
.ic v(bias_n)=0.5 v(vptat)=0.01 v(ota_out)=0.6 v(sum_n)=0.6

Vdd vdd 0 1.2

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
XMBp1 buf1 vco5 vdd vdd sg13_lv_pmos w=4u l=0.5u ng=1 m=1
XMBn1 buf1 vco5 0 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XMBp2 vco_out buf1 vdd vdd sg13_lv_pmos w=8u l=0.5u ng=2 m=1
XMBn2 vco_out buf1 0 0 sg13_lv_nmos w=4u l=0.5u ng=2 m=1
XPM_cas_ref cas_ref net_c1 vdd vdd sg13_lv_pmos w=1u l=10u ng=1 m=1
XPM_cas_diode vcas vcas cas_ref vdd sg13_lv_pmos w=1u l=2u ng=1 m=1
XMN_cas_load vcas vcas 0 0 sg13_lv_nmos w=0.5u l=2u ng=1 m=1
XPM_mir1 cas1 net_c1 vdd vdd sg13_lv_pmos w=1u l=10u ng=1 m=1
XPM_cas1 src1 vcas cas1 vdd sg13_lv_pmos w=1u l=2u ng=1 m=1
XPM_mir2 cas2 net_c1 vdd vdd sg13_lv_pmos w=2u l=10u ng=1 m=1
XPM_cas2 src2 vcas cas2 vdd sg13_lv_pmos w=2u l=2u ng=1 m=1
XPM_mir3 cas3 net_c1 vdd vdd sg13_lv_pmos w=4u l=10u ng=2 m=1
XPM_cas3 src3 vcas cas3 vdd sg13_lv_pmos w=4u l=2u ng=2 m=1
XSW1n src1 sel0 exc_out 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XSW1p src1 sel0b exc_out vdd sg13_lv_pmos w=4u l=0.5u ng=1 m=1
XSW2n src2 sel1 exc_out 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XSW2p src2 sel1b exc_out vdd sg13_lv_pmos w=4u l=0.5u ng=1 m=1
XSW3n src3 sel2 exc_out 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XSW3p src3 sel2b exc_out vdd sg13_lv_pmos w=4u l=0.5u ng=1 m=1
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
XMS1 exc_out phi_p probe_p 0 sg13_lv_nmos w=4u l=0.5u ng=2 m=1
XMS2 0 phi_n probe_p 0 sg13_lv_nmos w=4u l=0.5u ng=2 m=1
XMS3 exc_out phi_n probe_n 0 sg13_lv_nmos w=4u l=0.5u ng=2 m=1
XMS4 0 phi_p probe_n 0 sg13_lv_nmos w=4u l=0.5u ng=2 m=1
XMchop1n sens_p f_exc chop_out 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XMchop1p sens_p f_exc_b chop_out vdd sg13_lv_pmos w=4u l=0.5u ng=1 m=1
XMchop2n sens_n f_exc_b chop_out 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XMchop2p sens_n f_exc chop_out vdd sg13_lv_pmos w=4u l=0.5u ng=1 m=1
XMbias_d bias_n bias_n 0 0 sg13_lv_nmos w=4u l=4u ng=1 m=1
XMp_load_p mid_p mid_p vdd vdd sg13_lv_pmos w=4u l=4u ng=1 m=1
XMp_load_n ota_out mid_p vdd vdd sg13_lv_pmos w=4u l=4u ng=1 m=1
XMin_p mid_p vref_ota tail 0 sg13_lv_nmos w=10u l=2u ng=4 m=1
XMin_n ota_out sum_n tail 0 sg13_lv_nmos w=10u l=2u ng=4 m=1
XMtail tail bias_n 0 0 sg13_lv_nmos w=8u l=4u ng=2 m=1
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
XMn1a n1_mid comp_outp 0 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XMp1a lat_q comp_outp vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMn1b lat_q lat_qb n1_mid 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XMp1b lat_q lat_qb vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMn2a n2_mid comp_outn 0 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XMp2a lat_qb comp_outn vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMn2b lat_qb lat_q n2_mid 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XMp2b lat_qb lat_q vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMdac_tg1n dac_hi lat_q dac_out 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XMdac_tg1p dac_hi lat_qb dac_out vdd sg13_lv_pmos w=4u l=0.5u ng=1 m=1
XMdac_tg2n dac_lo lat_qb dac_out 0 sg13_lv_nmos w=2u l=0.5u ng=1 m=1
XMdac_tg2p dac_lo lat_q dac_out vdd sg13_lv_pmos w=4u l=0.5u ng=1 m=1
XRin chop_out sum_n 0 rhigh w=0.5e-6 l=20.0e-6 b=2 m=1
XRdac dac_out sum_n 0 rhigh w=0.5e-6 l=20.0e-6 b=2 m=1
XT1I_m1 div2_I_b vco_b t1I_m 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT1I_m2 div2_I_b vco_out t1I_m vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1I_m3 t1I_mb t1I_m 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT1I_m4 t1I_mb t1I_m vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1I_m5 t1I_nmp vco_b vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1I_m6 t1I_m t1I_mb t1I_nmp vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1I_m7 t1I_m t1I_mb t1I_nmn 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT1I_m8 t1I_nmn vco_out 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT1I_s1 t1I_m vco_out div2_I 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT1I_s2 t1I_m vco_b div2_I vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1I_s3 div2_I_b div2_I 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT1I_s4 div2_I_b div2_I vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1I_s5 t1I_nsp vco_out vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1I_s6 div2_I div2_I_b t1I_nsp vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1I_s7 div2_I div2_I_b t1I_nsn 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT1I_s8 t1I_nsn vco_b 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT1Q_m1 div2_Q_b vco_out t1Q_m 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT1Q_m2 div2_Q_b vco_b t1Q_m vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1Q_m3 t1Q_mb t1Q_m 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT1Q_m4 t1Q_mb t1Q_m vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1Q_m5 t1Q_nmp vco_out vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1Q_m6 t1Q_m t1Q_mb t1Q_nmp vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1Q_m7 t1Q_m t1Q_mb t1Q_nmn 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT1Q_m8 t1Q_nmn vco_b 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT1Q_s1 t1Q_m vco_b div2_Q 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT1Q_s2 t1Q_m vco_out div2_Q vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1Q_s3 div2_Q_b div2_Q 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT1Q_s4 div2_Q_b div2_Q vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1Q_s5 t1Q_nsp vco_b vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1Q_s6 div2_Q div2_Q_b t1Q_nsp vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1Q_s7 div2_Q div2_Q_b t1Q_nsn 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT1Q_s8 t1Q_nsn vco_out 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2I_m1 div4_I_b div2_I_b t2I_m 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2I_m2 div4_I_b div2_I t2I_m vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2I_m3 t2I_mb t2I_m 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2I_m4 t2I_mb t2I_m vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2I_m5 t2I_nmp div2_I_b vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2I_m6 t2I_m t2I_mb t2I_nmp vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2I_m7 t2I_m t2I_mb t2I_nmn 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2I_m8 t2I_nmn div2_I 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2I_s1 t2I_m div2_I div4_I 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2I_s2 t2I_m div2_I_b div4_I vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2I_s3 div4_I_b div4_I 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2I_s4 div4_I_b div4_I vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2I_s5 t2I_nsp div2_I vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2I_s6 div4_I div4_I_b t2I_nsp vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2I_s7 div4_I div4_I_b t2I_nsn 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2I_s8 t2I_nsn div2_I_b 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2Q_m1 div4_Q_b div2_I t2Q_m 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2Q_m2 div4_Q_b div2_I_b t2Q_m vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2Q_m3 t2Q_mb t2Q_m 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2Q_m4 t2Q_mb t2Q_m vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2Q_m5 t2Q_nmp div2_I vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2Q_m6 t2Q_m t2Q_mb t2Q_nmp vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2Q_m7 t2Q_m t2Q_mb t2Q_nmn 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2Q_m8 t2Q_nmn div2_I_b 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2Q_s1 t2Q_m div2_I_b div4_Q 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2Q_s2 t2Q_m div2_I div4_Q vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2Q_s3 div4_Q_b div4_Q 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2Q_s4 div4_Q_b div4_Q vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2Q_s5 t2Q_nsp div2_I_b vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2Q_s6 div4_Q div4_Q_b t2Q_nsp vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2Q_s7 div4_Q div4_Q_b t2Q_nsn 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2Q_s8 t2Q_nsn div2_I 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT3_m1 div8_b div4_I_b t3_m 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT3_m2 div8_b div4_I t3_m vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT3_m3 t3_mb t3_m 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT3_m4 t3_mb t3_m vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT3_m5 t3_nmp div4_I_b vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT3_m6 t3_m t3_mb t3_nmp vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT3_m7 t3_m t3_mb t3_nmn 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT3_m8 t3_nmn div4_I 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT3_s1 t3_m div4_I div8 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT3_s2 t3_m div4_I_b div8 vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT3_s3 div8_b div8 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT3_s4 div8_b div8 vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT3_s5 t3_nsp div4_I vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT3_s6 div8 div8_b t3_nsp vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT3_s7 div8 div8_b t3_nsn 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT3_s8 t3_nsn div4_I_b 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4I_m1 div16_I_b div8_b t4I_m 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4I_m2 div16_I_b div8 t4I_m vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4I_m3 t4I_mb t4I_m 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4I_m4 t4I_mb t4I_m vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4I_m5 t4I_nmp div8_b vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4I_m6 t4I_m t4I_mb t4I_nmp vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4I_m7 t4I_m t4I_mb t4I_nmn 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4I_m8 t4I_nmn div8 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4I_s1 t4I_m div8 div16_I 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4I_s2 t4I_m div8_b div16_I vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4I_s3 div16_I_b div16_I 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4I_s4 div16_I_b div16_I vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4I_s5 t4I_nsp div8 vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4I_s6 div16_I div16_I_b t4I_nsp vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4I_s7 div16_I div16_I_b t4I_nsn 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4I_s8 t4I_nsn div8_b 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4Q_m1 div16_Q_b div8 t4Q_m 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4Q_m2 div16_Q_b div8_b t4Q_m vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4Q_m3 t4Q_mb t4Q_m 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4Q_m4 t4Q_mb t4Q_m vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4Q_m5 t4Q_nmp div8 vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4Q_m6 t4Q_m t4Q_mb t4Q_nmp vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4Q_m7 t4Q_m t4Q_mb t4Q_nmn 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4Q_m8 t4Q_nmn div8_b 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4Q_s1 t4Q_m div8_b div16_Q 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4Q_s2 t4Q_m div8 div16_Q vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4Q_s3 div16_Q_b div16_Q 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4Q_s4 div16_Q_b div16_Q vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4Q_s5 t4Q_nsp div8_b vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4Q_s6 div16_Q div16_Q_b t4Q_nsp vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4Q_s7 div16_Q div16_Q_b t4Q_nsn 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4Q_s8 t4Q_nsn div8 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XMXfi_n1 mxfi_selb freq_sel 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XMXfi_p1 mxfi_selb freq_sel vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMXfi_n2 div4_I mxfi_selb ref_I 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XMXfi_p2 div4_I freq_sel ref_I vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMXfi_n3 div16_I freq_sel ref_I 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XMXfi_p3 div16_I mxfi_selb ref_I vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMXfq_n1 mxfq_selb freq_sel 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XMXfq_p1 mxfq_selb freq_sel vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMXfq_n2 div4_Q mxfq_selb ref_Q 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XMXfq_p2 div4_Q freq_sel ref_Q vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMXfq_n3 div16_Q freq_sel ref_Q 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XMXfq_p3 div16_Q mxfq_selb ref_Q vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMXiq_n1 mxiq_selb iq_sel 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XMXiq_p1 mxiq_selb iq_sel vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMXiq_n2 ref_I mxiq_selb f_exc 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XMXiq_p2 ref_I iq_sel f_exc vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XMXiq_n3 ref_Q iq_sel f_exc 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XMXiq_p3 ref_Q mxiq_selb f_exc vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XBUF_I_n buf_ref_I ref_I 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XBUF_I_p buf_ref_I ref_I vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XBUF_Q_n buf_ref_Q ref_Q 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XBUF_Q_p buf_ref_Q ref_Q vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XBUF_CK_n f_exc_b f_exc 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XBUF_CK_p f_exc_b f_exc vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XINV_VCO_n vco_b vco_out 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XINV_VCO_p vco_b vco_out vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XC_fb ota_out sum_n cap_cmim w=26.0e-6 l=26.0e-6 m=1

.tran 1n 15u uic

.meas tran vco_freq trig v(vco_out) val=0.6 rise=5 targ v(vco_out) val=0.6 rise=6
.meas tran vptat_end find v(vptat) at=14u
.meas tran bias_n_end find v(bias_n) at=14u
.meas tran pmos_bias_end find v(pmos_bias) at=14u
.meas tran nmos_bias_end find v(nmos_bias) at=14u
.meas tran ota_out_end find v(ota_out) at=14u
.meas tran net_c1_end find v(net_c1) at=14u

.end
