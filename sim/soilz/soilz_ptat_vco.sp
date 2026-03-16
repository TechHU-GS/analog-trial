** SoilZ v1 — ptat_vco
** 37 devices
** Auto-rebuilt from netlist.json

.subckt ptat_vco buf1 gnd nb1 nb2 nb3 nb4 nb5 net_c1
+ net_c2 net_rptat nmos_bias ns1 ns2 ns3 ns4 ns5 pmos_bias vco1
+ vco2 vco3 vco4 vco5 vco_b vco_out vdd vptat

MPM3 net_c1 net_c1 vdd vdd sg13_lv_pmos W=0.5u L=10u
MPM4 net_c2 net_c1 vdd vdd sg13_lv_pmos W=0.5u L=10u
MPM5 vptat net_c1 vdd vdd sg13_lv_pmos W=0.5u L=10u
MPM_ref nmos_bias net_c1 vdd vdd sg13_lv_pmos W=0.5u L=10u
MMN1 net_c1 net_c1 gnd gnd sg13_lv_nmos W=2u L=4u
MMN2 net_c2 net_c1 net_rptat gnd sg13_lv_nmos W=16u L=4u
MMN_diode nmos_bias nmos_bias gnd gnd sg13_lv_nmos W=1u L=2u
MMN_pgen pmos_bias nmos_bias gnd gnd sg13_lv_nmos W=1u L=2u
MPM_pdiode pmos_bias pmos_bias vdd vdd sg13_lv_pmos W=0.5u L=2u
MMpb1 ns1 pmos_bias vdd vdd sg13_lv_pmos W=4u L=2u
MMpb2 ns2 pmos_bias vdd vdd sg13_lv_pmos W=4u L=2u
MMpb3 ns3 pmos_bias vdd vdd sg13_lv_pmos W=4u L=2u
MMpb4 ns4 pmos_bias vdd vdd sg13_lv_pmos W=4u L=2u
MMpb5 ns5 pmos_bias vdd vdd sg13_lv_pmos W=4u L=2u
MMpu1 vco1 vco5 ns1 vdd sg13_lv_pmos W=2u L=0.5u
MMpu2 vco2 vco1 ns2 vdd sg13_lv_pmos W=2u L=0.5u
MMpu3 vco3 vco2 ns3 vdd sg13_lv_pmos W=2u L=0.5u
MMpu4 vco4 vco3 ns4 vdd sg13_lv_pmos W=2u L=0.5u
MMpu5 vco5 vco4 ns5 vdd sg13_lv_pmos W=2u L=0.5u
MMpd1 vco1 vco5 nb1 gnd sg13_lv_nmos W=1u L=0.5u
MMpd2 vco2 vco1 nb2 gnd sg13_lv_nmos W=1u L=0.5u
MMpd3 vco3 vco2 nb3 gnd sg13_lv_nmos W=1u L=0.5u
MMpd4 vco4 vco3 nb4 gnd sg13_lv_nmos W=1u L=0.5u
MMpd5 vco5 vco4 nb5 gnd sg13_lv_nmos W=1u L=0.5u
MMnb1 nb1 nmos_bias gnd gnd sg13_lv_nmos W=8u L=2u
MMnb2 nb2 nmos_bias gnd gnd sg13_lv_nmos W=8u L=2u
MMnb3 nb3 nmos_bias gnd gnd sg13_lv_nmos W=8u L=2u
MMnb4 nb4 nmos_bias gnd gnd sg13_lv_nmos W=8u L=2u
MMnb5 nb5 nmos_bias gnd gnd sg13_lv_nmos W=8u L=2u
MMBp1 buf1 vco5 vdd vdd sg13_lv_pmos W=4u L=0.5u
MMBp2 vco_out buf1 vdd vdd sg13_lv_pmos W=8u L=0.5u
MMBn1 buf1 vco5 gnd gnd sg13_lv_nmos W=2u L=0.5u
MMBn2 vco_out buf1 gnd gnd sg13_lv_nmos W=4u L=0.5u
MINV_VCO_p vco_b vco_out vdd vdd sg13_lv_pmos W=2u L=0.5u
MINV_VCO_n vco_b vco_out gnd gnd sg13_lv_nmos W=1u L=0.5u
RRptat net_rptat gnd rhigh w=0.5u l=133.0u b=12 m=1
RRout vptat gnd rppd w=0.5u l=25.0u b=4 m=1

.ends ptat_vco
