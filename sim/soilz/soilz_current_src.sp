** SoilZ v1 — current_src
** 15 devices
** Auto-rebuilt from netlist.json

.subckt current_src cas1 cas2 cas3 cas_ref exc_out gnd net_c1 sel0
+ sel0b sel1 sel1b sel2 sel2b src1 src2 src3 vcas vdd

MPM_cas_ref cas_ref net_c1 vdd vdd sg13_lv_pmos W=1u L=10u
MPM_cas_diode vcas vcas cas_ref vdd sg13_lv_pmos W=1u L=2u
MPM_cas1 src1 vcas cas1 vdd sg13_lv_pmos W=1u L=2u
MPM_cas2 src2 vcas cas2 vdd sg13_lv_pmos W=2u L=2u
MPM_cas3 src3 vcas cas3 vdd sg13_lv_pmos W=4u L=2u
MPM_mir1 cas1 net_c1 vdd vdd sg13_lv_pmos W=1u L=10u
MPM_mir2 cas2 net_c1 vdd vdd sg13_lv_pmos W=2u L=10u
MPM_mir3 cas3 net_c1 vdd vdd sg13_lv_pmos W=4u L=10u
MMN_cas_load vcas vcas gnd gnd sg13_lv_nmos W=0.5u L=2u
MSW1n src1 sel0 exc_out gnd sg13_lv_nmos W=2u L=0.5u
MSW1p src1 sel0b exc_out vdd sg13_lv_pmos W=4u L=0.5u
MSW2n src2 sel1 exc_out gnd sg13_lv_nmos W=2u L=0.5u
MSW2p src2 sel1b exc_out vdd sg13_lv_pmos W=4u L=0.5u
MSW3n src3 sel2 exc_out gnd sg13_lv_nmos W=2u L=0.5u
MSW3p src3 sel2b exc_out vdd sg13_lv_pmos W=4u L=0.5u

.ends current_src
