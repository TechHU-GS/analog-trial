** SoilZ v1 — ota_chopper
** 12 devices
** Auto-rebuilt from netlist.json

.subckt ota_chopper bias_n chop_out dac_out f_exc f_exc_b gnd mid_p ota_out
+ sens_n sens_p sum_n tail vdd vref_ota

MMp_load_p mid_p mid_p vdd vdd sg13_lv_pmos W=4u L=4u
MMp_load_n ota_out mid_p vdd vdd sg13_lv_pmos W=4u L=4u
MMin_p mid_p vref_ota tail gnd sg13_lv_nmos W=10u L=2u
MMin_n ota_out sum_n tail gnd sg13_lv_nmos W=10u L=2u
MMtail tail bias_n gnd gnd sg13_lv_nmos W=8u L=4u
MMbias_d bias_n bias_n gnd gnd sg13_lv_nmos W=4u L=4u
MMchop1n sens_p f_exc chop_out gnd sg13_lv_nmos W=2u L=0.5u
MMchop1p sens_p f_exc_b chop_out vdd sg13_lv_pmos W=4u L=0.5u
MMchop2n sens_n f_exc_b chop_out gnd sg13_lv_nmos W=2u L=0.5u
MMchop2p sens_n f_exc chop_out vdd sg13_lv_pmos W=4u L=0.5u
RRin chop_out sum_n rhigh w=0.5u l=20.0u b=2 m=1
RRdac dac_out sum_n rhigh w=0.5u l=20.0u b=2 m=1

.ends ota_chopper
