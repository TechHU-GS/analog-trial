** SoilZ v1 — Complete circuit (all blocks combined)
** 249 devices
** IHP SG13G2 130nm BiCMOS (CMOS-only)

.include ../pdk.inc

.include soilz_ptat_vco.sp
.include soilz_current_src.sp
.include soilz_hbridge_nol.sp
.include soilz_ota_chopper.sp
.include soilz_comparator_latch.sp
.include soilz_digital.sp

** Top-level instantiation
Xptat_vco buf1 gnd nb1 nb2 nb3 nb4 nb5 net_c1 net_c2 net_rptat nmos_bias ns1 ns2 ns3 ns4 ns5 pmos_bias vco1 vco2 vco3 vco4 vco5 vco_b vco_out vdd vptat ptat_vco
Xcurrent_src cas1 cas2 cas3 cas_ref exc_out gnd net_c1 sel0 sel0b sel1 sel1b sel2 sel2b src1 src2 src3 vcas vdd current_src
Xhbridge_nol da1 db1 exc_out f_exc f_exc_b f_exc_b_d f_exc_d gnd na_mid nand_a nand_b nb_mid phi_n phi_p probe_n probe_p vdd hbridge_nol
Xota_chopper bias_n chop_out dac_out f_exc f_exc_b gnd mid_p ota_out sens_n sens_p sum_n tail vdd vref_ota ota_chopper
Xcomparator_latch c_di_n c_di_p c_tail comp_clk comp_outn comp_outp dac_hi dac_lo dac_out gnd lat_q lat_qb n1_mid n2_mid ota_out vdd vref_comp comparator_latch
Xdigital buf_ref_I buf_ref_Q div16_I div16_I_b div16_Q div16_Q_b div2_I div2_I_b div2_Q div2_Q_b div4_I div4_I_b div4_Q div4_Q_b div8 div8_b f_exc f_exc_b freq_sel gnd iq_sel mxfi_selb mxfq_selb mxiq_selb ref_I ref_Q t1I_m t1I_mb t1I_nmn t1I_nmp t1I_nsn t1I_nsp t1Q_m t1Q_mb t1Q_nmn t1Q_nmp t1Q_nsn t1Q_nsp t2I_m t2I_mb t2I_nmn t2I_nmp t2I_nsn t2I_nsp t2Q_m t2Q_mb t2Q_nmn t2Q_nmp t2Q_nsn t2Q_nsp t3_m t3_mb t3_nmn t3_nmp t3_nsn t3_nsp t4I_m t4I_mb t4I_nmn t4I_nmp t4I_nsn t4I_nsp t4Q_m t4Q_mb t4Q_nmn t4Q_nmp t4Q_nsn t4Q_nsp vco_b vco_out vdd digital

** Power
Vdd vdd 0 1.2
Vgnd gnd 0 0

** Transient
.tran 1n 10u
.end
