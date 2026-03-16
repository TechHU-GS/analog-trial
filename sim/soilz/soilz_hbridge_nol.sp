** SoilZ v1 — hbridge_nol
** 26 devices
** Auto-rebuilt from netlist.json

.subckt hbridge_nol da1 db1 exc_out f_exc f_exc_b f_exc_b_d f_exc_d gnd
+ na_mid nand_a nand_b nb_mid phi_n phi_p probe_n probe_p vdd

MM_inv0_n f_exc_b f_exc gnd gnd sg13_lv_nmos W=1u L=0.5u
MM_inv0_p f_exc_b f_exc vdd vdd sg13_lv_pmos W=2u L=0.5u
MM_na_n1 nand_a f_exc na_mid gnd sg13_lv_nmos W=2u L=0.5u
MM_na_n2 na_mid f_exc_d gnd gnd sg13_lv_nmos W=2u L=0.5u
MM_na_p1 nand_a f_exc vdd vdd sg13_lv_pmos W=2u L=0.5u
MM_na_p2 nand_a f_exc_d vdd vdd sg13_lv_pmos W=2u L=0.5u
MM_nb_n1 nand_b f_exc_b nb_mid gnd sg13_lv_nmos W=2u L=0.5u
MM_nb_n2 nb_mid f_exc_b_d gnd gnd sg13_lv_nmos W=2u L=0.5u
MM_nb_p1 nand_b f_exc_b vdd vdd sg13_lv_pmos W=2u L=0.5u
MM_nb_p2 nand_b f_exc_b_d vdd vdd sg13_lv_pmos W=2u L=0.5u
MM_ia_n phi_p nand_a gnd gnd sg13_lv_nmos W=2u L=0.5u
MM_ia_p phi_p nand_a vdd vdd sg13_lv_pmos W=4u L=0.5u
MM_ib_n phi_n nand_b gnd gnd sg13_lv_nmos W=2u L=0.5u
MM_ib_p phi_n nand_b vdd vdd sg13_lv_pmos W=4u L=0.5u
MMS1 exc_out phi_p probe_p gnd sg13_lv_nmos W=4u L=0.5u
MMS2 gnd phi_n probe_p gnd sg13_lv_nmos W=4u L=0.5u
MMS3 exc_out phi_n probe_n gnd sg13_lv_nmos W=4u L=0.5u
MMS4 gnd phi_p probe_n gnd sg13_lv_nmos W=4u L=0.5u
MM_da1_n da1 f_exc gnd gnd sg13_lv_nmos W=1u L=0.5u
MM_da1_p da1 f_exc vdd vdd sg13_lv_pmos W=2u L=0.5u
MM_da2_n f_exc_d da1 gnd gnd sg13_lv_nmos W=1u L=0.5u
MM_da2_p f_exc_d da1 vdd vdd sg13_lv_pmos W=2u L=0.5u
MM_db1_n db1 f_exc_b gnd gnd sg13_lv_nmos W=1u L=0.5u
MM_db1_p db1 f_exc_b vdd vdd sg13_lv_pmos W=2u L=0.5u
MM_db2_n f_exc_b_d db1 gnd gnd sg13_lv_nmos W=1u L=0.5u
MM_db2_p f_exc_b_d db1 vdd vdd sg13_lv_pmos W=2u L=0.5u

.ends hbridge_nol
