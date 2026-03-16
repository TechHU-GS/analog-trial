** SoilZ v1 — comparator_latch
** 23 devices
** Auto-rebuilt from netlist.json

.subckt comparator_latch c_di_n c_di_p c_tail comp_clk comp_outn comp_outp dac_hi dac_lo
+ dac_out gnd lat_q lat_qb n1_mid n2_mid ota_out vdd vref_comp

MMc_tail c_tail comp_clk gnd gnd sg13_lv_nmos W=4u L=0.5u
MMc_inp c_di_p ota_out c_tail gnd sg13_lv_nmos W=4u L=0.5u
MMc_inn c_di_n vref_comp c_tail gnd sg13_lv_nmos W=4u L=0.5u
MMc_lp1 comp_outp comp_outn vdd vdd sg13_lv_pmos W=1u L=0.5u
MMc_lp2 comp_outn comp_outp vdd vdd sg13_lv_pmos W=1u L=0.5u
MMc_ln1 comp_outp comp_outn c_di_p gnd sg13_lv_nmos W=1u L=0.5u
MMc_ln2 comp_outn comp_outp c_di_n gnd sg13_lv_nmos W=1u L=0.5u
MMc_rst_dp c_di_p comp_clk vdd vdd sg13_lv_pmos W=2u L=0.5u
MMc_rst_dn c_di_n comp_clk vdd vdd sg13_lv_pmos W=2u L=0.5u
MMc_rst_op comp_outp comp_clk vdd vdd sg13_lv_pmos W=2u L=0.5u
MMc_rst_on comp_outn comp_clk vdd vdd sg13_lv_pmos W=2u L=0.5u
MMn1a n1_mid comp_outp gnd gnd sg13_lv_nmos W=2u L=0.5u
MMn1b lat_q lat_qb n1_mid gnd sg13_lv_nmos W=2u L=0.5u
MMn2a n2_mid comp_outn gnd gnd sg13_lv_nmos W=2u L=0.5u
MMn2b lat_qb lat_q n2_mid gnd sg13_lv_nmos W=2u L=0.5u
MMp1a lat_q comp_outp vdd vdd sg13_lv_pmos W=2u L=0.5u
MMp1b lat_q lat_qb vdd vdd sg13_lv_pmos W=2u L=0.5u
MMp2a lat_qb comp_outn vdd vdd sg13_lv_pmos W=2u L=0.5u
MMp2b lat_qb lat_q vdd vdd sg13_lv_pmos W=2u L=0.5u
MMdac_tg1n dac_hi lat_q dac_out gnd sg13_lv_nmos W=2u L=0.5u
MMdac_tg1p dac_hi lat_qb dac_out vdd sg13_lv_pmos W=4u L=0.5u
MMdac_tg2n dac_lo lat_qb dac_out gnd sg13_lv_nmos W=2u L=0.5u
MMdac_tg2p dac_lo lat_q dac_out vdd sg13_lv_pmos W=4u L=0.5u

.ends comparator_latch
