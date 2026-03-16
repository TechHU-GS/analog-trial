** SoilZ v1 — digital
** 136 devices
** Auto-rebuilt from netlist.json

.subckt digital buf_ref_I buf_ref_Q div16_I div16_I_b div16_Q div16_Q_b div2_I div2_I_b
+ div2_Q div2_Q_b div4_I div4_I_b div4_Q div4_Q_b div8 div8_b f_exc f_exc_b
+ freq_sel gnd iq_sel mxfi_selb mxfq_selb mxiq_selb ref_I ref_Q t1I_m t1I_mb
+ t1I_nmn t1I_nmp t1I_nsn t1I_nsp t1Q_m t1Q_mb t1Q_nmn t1Q_nmp t1Q_nsn t1Q_nsp
+ t2I_m t2I_mb t2I_nmn t2I_nmp t2I_nsn t2I_nsp t2Q_m t2Q_mb t2Q_nmn t2Q_nmp
+ t2Q_nsn t2Q_nsp t3_m t3_mb t3_nmn t3_nmp t3_nsn t3_nsp t4I_m t4I_mb
+ t4I_nmn t4I_nmp t4I_nsn t4I_nsp t4Q_m t4Q_mb t4Q_nmn t4Q_nmp t4Q_nsn t4Q_nsp
+ vco_b vco_out vdd

MT1I_m1 div2_I_b vco_b t1I_m gnd sg13_lv_nmos W=1u L=0.5u
MT1I_m2 div2_I_b vco_out t1I_m vdd sg13_lv_pmos W=2u L=0.5u
MT1I_m3 t1I_mb t1I_m gnd gnd sg13_lv_nmos W=1u L=0.5u
MT1I_m4 t1I_mb t1I_m vdd vdd sg13_lv_pmos W=2u L=0.5u
MT1I_m5 t1I_nmp vco_b vdd vdd sg13_lv_pmos W=2u L=0.5u
MT1I_m6 t1I_m t1I_mb t1I_nmp vdd sg13_lv_pmos W=2u L=0.5u
MT1I_m7 t1I_m t1I_mb t1I_nmn gnd sg13_lv_nmos W=1u L=0.5u
MT1I_m8 t1I_nmn vco_out gnd gnd sg13_lv_nmos W=1u L=0.5u
MT1I_s1 t1I_m vco_out div2_I gnd sg13_lv_nmos W=1u L=0.5u
MT1I_s2 t1I_m vco_b div2_I vdd sg13_lv_pmos W=2u L=0.5u
MT1I_s3 div2_I_b div2_I gnd gnd sg13_lv_nmos W=1u L=0.5u
MT1I_s4 div2_I_b div2_I vdd vdd sg13_lv_pmos W=2u L=0.5u
MT1I_s5 t1I_nsp vco_out vdd vdd sg13_lv_pmos W=2u L=0.5u
MT1I_s6 div2_I div2_I_b t1I_nsp vdd sg13_lv_pmos W=2u L=0.5u
MT1I_s7 div2_I div2_I_b t1I_nsn gnd sg13_lv_nmos W=1u L=0.5u
MT1I_s8 t1I_nsn vco_b gnd gnd sg13_lv_nmos W=1u L=0.5u
MT1Q_m1 div2_Q_b vco_out t1Q_m gnd sg13_lv_nmos W=1u L=0.5u
MT1Q_m2 div2_Q_b vco_b t1Q_m vdd sg13_lv_pmos W=2u L=0.5u
MT1Q_m3 t1Q_mb t1Q_m gnd gnd sg13_lv_nmos W=1u L=0.5u
MT1Q_m4 t1Q_mb t1Q_m vdd vdd sg13_lv_pmos W=2u L=0.5u
MT1Q_m5 t1Q_nmp vco_out vdd vdd sg13_lv_pmos W=2u L=0.5u
MT1Q_m6 t1Q_m t1Q_mb t1Q_nmp vdd sg13_lv_pmos W=2u L=0.5u
MT1Q_m7 t1Q_m t1Q_mb t1Q_nmn gnd sg13_lv_nmos W=1u L=0.5u
MT1Q_m8 t1Q_nmn vco_b gnd gnd sg13_lv_nmos W=1u L=0.5u
MT1Q_s1 t1Q_m vco_b div2_Q gnd sg13_lv_nmos W=1u L=0.5u
MT1Q_s2 t1Q_m vco_out div2_Q vdd sg13_lv_pmos W=2u L=0.5u
MT1Q_s3 div2_Q_b div2_Q gnd gnd sg13_lv_nmos W=1u L=0.5u
MT1Q_s4 div2_Q_b div2_Q vdd vdd sg13_lv_pmos W=2u L=0.5u
MT1Q_s5 t1Q_nsp vco_b vdd vdd sg13_lv_pmos W=2u L=0.5u
MT1Q_s6 div2_Q div2_Q_b t1Q_nsp vdd sg13_lv_pmos W=2u L=0.5u
MT1Q_s7 div2_Q div2_Q_b t1Q_nsn gnd sg13_lv_nmos W=1u L=0.5u
MT1Q_s8 t1Q_nsn vco_out gnd gnd sg13_lv_nmos W=1u L=0.5u
MT2I_m1 div4_I_b div2_I_b t2I_m gnd sg13_lv_nmos W=1u L=0.5u
MT2I_m2 div4_I_b div2_I t2I_m vdd sg13_lv_pmos W=2u L=0.5u
MT2I_m3 t2I_mb t2I_m gnd gnd sg13_lv_nmos W=1u L=0.5u
MT2I_m4 t2I_mb t2I_m vdd vdd sg13_lv_pmos W=2u L=0.5u
MT2I_m5 t2I_nmp div2_I_b vdd vdd sg13_lv_pmos W=2u L=0.5u
MT2I_m6 t2I_m t2I_mb t2I_nmp vdd sg13_lv_pmos W=2u L=0.5u
MT2I_m7 t2I_m t2I_mb t2I_nmn gnd sg13_lv_nmos W=1u L=0.5u
MT2I_m8 t2I_nmn div2_I gnd gnd sg13_lv_nmos W=1u L=0.5u
MT2I_s1 t2I_m div2_I div4_I gnd sg13_lv_nmos W=1u L=0.5u
MT2I_s2 t2I_m div2_I_b div4_I vdd sg13_lv_pmos W=2u L=0.5u
MT2I_s3 div4_I_b div4_I gnd gnd sg13_lv_nmos W=1u L=0.5u
MT2I_s4 div4_I_b div4_I vdd vdd sg13_lv_pmos W=2u L=0.5u
MT2I_s5 t2I_nsp div2_I vdd vdd sg13_lv_pmos W=2u L=0.5u
MT2I_s6 div4_I div4_I_b t2I_nsp vdd sg13_lv_pmos W=2u L=0.5u
MT2I_s7 div4_I div4_I_b t2I_nsn gnd sg13_lv_nmos W=1u L=0.5u
MT2I_s8 t2I_nsn div2_I_b gnd gnd sg13_lv_nmos W=1u L=0.5u
MT2Q_m1 div4_Q_b div2_I t2Q_m gnd sg13_lv_nmos W=1u L=0.5u
MT2Q_m2 div4_Q_b div2_I_b t2Q_m vdd sg13_lv_pmos W=2u L=0.5u
MT2Q_m3 t2Q_mb t2Q_m gnd gnd sg13_lv_nmos W=1u L=0.5u
MT2Q_m4 t2Q_mb t2Q_m vdd vdd sg13_lv_pmos W=2u L=0.5u
MT2Q_m5 t2Q_nmp div2_I vdd vdd sg13_lv_pmos W=2u L=0.5u
MT2Q_m6 t2Q_m t2Q_mb t2Q_nmp vdd sg13_lv_pmos W=2u L=0.5u
MT2Q_m7 t2Q_m t2Q_mb t2Q_nmn gnd sg13_lv_nmos W=1u L=0.5u
MT2Q_m8 t2Q_nmn div2_I_b gnd gnd sg13_lv_nmos W=1u L=0.5u
MT2Q_s1 t2Q_m div2_I_b div4_Q gnd sg13_lv_nmos W=1u L=0.5u
MT2Q_s2 t2Q_m div2_I div4_Q vdd sg13_lv_pmos W=2u L=0.5u
MT2Q_s3 div4_Q_b div4_Q gnd gnd sg13_lv_nmos W=1u L=0.5u
MT2Q_s4 div4_Q_b div4_Q vdd vdd sg13_lv_pmos W=2u L=0.5u
MT2Q_s5 t2Q_nsp div2_I_b vdd vdd sg13_lv_pmos W=2u L=0.5u
MT2Q_s6 div4_Q div4_Q_b t2Q_nsp vdd sg13_lv_pmos W=2u L=0.5u
MT2Q_s7 div4_Q div4_Q_b t2Q_nsn gnd sg13_lv_nmos W=1u L=0.5u
MT2Q_s8 t2Q_nsn div2_I gnd gnd sg13_lv_nmos W=1u L=0.5u
MT3_m1 div8_b div4_I_b t3_m gnd sg13_lv_nmos W=1u L=0.5u
MT3_m2 div8_b div4_I t3_m vdd sg13_lv_pmos W=2u L=0.5u
MT3_m3 t3_mb t3_m gnd gnd sg13_lv_nmos W=1u L=0.5u
MT3_m4 t3_mb t3_m vdd vdd sg13_lv_pmos W=2u L=0.5u
MT3_m5 t3_nmp div4_I_b vdd vdd sg13_lv_pmos W=2u L=0.5u
MT3_m6 t3_m t3_mb t3_nmp vdd sg13_lv_pmos W=2u L=0.5u
MT3_m7 t3_m t3_mb t3_nmn gnd sg13_lv_nmos W=1u L=0.5u
MT3_m8 t3_nmn div4_I gnd gnd sg13_lv_nmos W=1u L=0.5u
MT3_s1 t3_m div4_I div8 gnd sg13_lv_nmos W=1u L=0.5u
MT3_s2 t3_m div4_I_b div8 vdd sg13_lv_pmos W=2u L=0.5u
MT3_s3 div8_b div8 gnd gnd sg13_lv_nmos W=1u L=0.5u
MT3_s4 div8_b div8 vdd vdd sg13_lv_pmos W=2u L=0.5u
MT3_s5 t3_nsp div4_I vdd vdd sg13_lv_pmos W=2u L=0.5u
MT3_s6 div8 div8_b t3_nsp vdd sg13_lv_pmos W=2u L=0.5u
MT3_s7 div8 div8_b t3_nsn gnd sg13_lv_nmos W=1u L=0.5u
MT3_s8 t3_nsn div4_I_b gnd gnd sg13_lv_nmos W=1u L=0.5u
MT4I_m1 div16_I_b div8_b t4I_m gnd sg13_lv_nmos W=1u L=0.5u
MT4I_m2 div16_I_b div8 t4I_m vdd sg13_lv_pmos W=2u L=0.5u
MT4I_m3 t4I_mb t4I_m gnd gnd sg13_lv_nmos W=1u L=0.5u
MT4I_m4 t4I_mb t4I_m vdd vdd sg13_lv_pmos W=2u L=0.5u
MT4I_m5 t4I_nmp div8_b vdd vdd sg13_lv_pmos W=2u L=0.5u
MT4I_m6 t4I_m t4I_mb t4I_nmp vdd sg13_lv_pmos W=2u L=0.5u
MT4I_m7 t4I_m t4I_mb t4I_nmn gnd sg13_lv_nmos W=1u L=0.5u
MT4I_m8 t4I_nmn div8 gnd gnd sg13_lv_nmos W=1u L=0.5u
MT4I_s1 t4I_m div8 div16_I gnd sg13_lv_nmos W=1u L=0.5u
MT4I_s2 t4I_m div8_b div16_I vdd sg13_lv_pmos W=2u L=0.5u
MT4I_s3 div16_I_b div16_I gnd gnd sg13_lv_nmos W=1u L=0.5u
MT4I_s4 div16_I_b div16_I vdd vdd sg13_lv_pmos W=2u L=0.5u
MT4I_s5 t4I_nsp div8 vdd vdd sg13_lv_pmos W=2u L=0.5u
MT4I_s6 div16_I div16_I_b t4I_nsp vdd sg13_lv_pmos W=2u L=0.5u
MT4I_s7 div16_I div16_I_b t4I_nsn gnd sg13_lv_nmos W=1u L=0.5u
MT4I_s8 t4I_nsn div8_b gnd gnd sg13_lv_nmos W=1u L=0.5u
MT4Q_m1 div16_Q_b div8 t4Q_m gnd sg13_lv_nmos W=1u L=0.5u
MT4Q_m2 div16_Q_b div8_b t4Q_m vdd sg13_lv_pmos W=2u L=0.5u
MT4Q_m3 t4Q_mb t4Q_m gnd gnd sg13_lv_nmos W=1u L=0.5u
MT4Q_m4 t4Q_mb t4Q_m vdd vdd sg13_lv_pmos W=2u L=0.5u
MT4Q_m5 t4Q_nmp div8 vdd vdd sg13_lv_pmos W=2u L=0.5u
MT4Q_m6 t4Q_m t4Q_mb t4Q_nmp vdd sg13_lv_pmos W=2u L=0.5u
MT4Q_m7 t4Q_m t4Q_mb t4Q_nmn gnd sg13_lv_nmos W=1u L=0.5u
MT4Q_m8 t4Q_nmn div8_b gnd gnd sg13_lv_nmos W=1u L=0.5u
MT4Q_s1 t4Q_m div8_b div16_Q gnd sg13_lv_nmos W=1u L=0.5u
MT4Q_s2 t4Q_m div8 div16_Q vdd sg13_lv_pmos W=2u L=0.5u
MT4Q_s3 div16_Q_b div16_Q gnd gnd sg13_lv_nmos W=1u L=0.5u
MT4Q_s4 div16_Q_b div16_Q vdd vdd sg13_lv_pmos W=2u L=0.5u
MT4Q_s5 t4Q_nsp div8_b vdd vdd sg13_lv_pmos W=2u L=0.5u
MT4Q_s6 div16_Q div16_Q_b t4Q_nsp vdd sg13_lv_pmos W=2u L=0.5u
MT4Q_s7 div16_Q div16_Q_b t4Q_nsn gnd sg13_lv_nmos W=1u L=0.5u
MT4Q_s8 t4Q_nsn div8 gnd gnd sg13_lv_nmos W=1u L=0.5u
MMXfi_n1 mxfi_selb freq_sel gnd gnd sg13_lv_nmos W=1u L=0.5u
MMXfi_n2 div4_I mxfi_selb ref_I gnd sg13_lv_nmos W=1u L=0.5u
MMXfi_n3 div16_I freq_sel ref_I gnd sg13_lv_nmos W=1u L=0.5u
MMXfi_p1 mxfi_selb freq_sel vdd vdd sg13_lv_pmos W=2u L=0.5u
MMXfi_p2 div4_I freq_sel ref_I vdd sg13_lv_pmos W=2u L=0.5u
MMXfi_p3 div16_I mxfi_selb ref_I vdd sg13_lv_pmos W=2u L=0.5u
MMXfq_n1 mxfq_selb freq_sel gnd gnd sg13_lv_nmos W=1u L=0.5u
MMXfq_n2 div4_Q mxfq_selb ref_Q gnd sg13_lv_nmos W=1u L=0.5u
MMXfq_n3 div16_Q freq_sel ref_Q gnd sg13_lv_nmos W=1u L=0.5u
MMXfq_p1 mxfq_selb freq_sel vdd vdd sg13_lv_pmos W=2u L=0.5u
MMXfq_p2 div4_Q freq_sel ref_Q vdd sg13_lv_pmos W=2u L=0.5u
MMXfq_p3 div16_Q mxfq_selb ref_Q vdd sg13_lv_pmos W=2u L=0.5u
MMXiq_n1 mxiq_selb iq_sel gnd gnd sg13_lv_nmos W=1u L=0.5u
MMXiq_n2 ref_I mxiq_selb f_exc gnd sg13_lv_nmos W=1u L=0.5u
MMXiq_n3 ref_Q iq_sel f_exc gnd sg13_lv_nmos W=1u L=0.5u
MMXiq_p1 mxiq_selb iq_sel vdd vdd sg13_lv_pmos W=2u L=0.5u
MMXiq_p2 ref_I iq_sel f_exc vdd sg13_lv_pmos W=2u L=0.5u
MMXiq_p3 ref_Q mxiq_selb f_exc vdd sg13_lv_pmos W=2u L=0.5u
MBUF_I_n buf_ref_I ref_I gnd gnd sg13_lv_nmos W=1u L=0.5u
MBUF_I_p buf_ref_I ref_I vdd vdd sg13_lv_pmos W=2u L=0.5u
MBUF_Q_n buf_ref_Q ref_Q gnd gnd sg13_lv_nmos W=1u L=0.5u
MBUF_Q_p buf_ref_Q ref_Q vdd vdd sg13_lv_pmos W=2u L=0.5u
MBUF_CK_n f_exc_b f_exc gnd gnd sg13_lv_nmos W=1u L=0.5u
MBUF_CK_p f_exc_b f_exc vdd vdd sg13_lv_pmos W=2u L=0.5u

.ends digital
