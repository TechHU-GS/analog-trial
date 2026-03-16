** Minimal test: 2 PMOS from SoilZ
.include 'pdk.inc'

MPM3 net_c1 net_c1 vdd vdd sg13_lv_pmos W=0.5u L=10u
MPM4 net_c2 net_c1 vdd vdd sg13_lv_pmos W=0.5u L=10u

Vdd vdd 0 1.2

.op
.end
