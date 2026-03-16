** Direct include (bypass .lib)
.param sg13g2_lv_nmos_vfbo = 1.0
.param sg13g2_lv_nmos_ctl = 1.208
.param sg13g2_lv_nmos_rsw1 = 0.72
.param sg13g2_lv_nmos_muew = 0.85
.param sg13g2_lv_nmos_dphibo = 0.9915
.param sg13g2_lv_pmos_vfbo = 1.0
.param sg13g2_lv_pmos_ctl = 1.296
.param sg13g2_lv_pmos_rsw1 = 0.735
.param sg13g2_lv_pmos_muew = 0.84
.param sg13g2_lv_pmos_dphibo = 1.007
.include /Users/techhu/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/ngspice/models/sg13g2_moslv_mod.lib

MPM3 net_c1 net_c1 vdd vdd sg13_lv_pmos W=0.5u L=10u
Vdd vdd 0 1.2

.op
.print dc v(net_c1)
.end
