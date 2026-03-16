** Inline PDK test
.control
  pre_osdi /Users/techhu/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/ngspice/osdi/psp103.osdi
  pre_osdi /Users/techhu/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/ngspice/osdi/r3_cmc.osdi
  set sourcepath = ( /Users/techhu/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/ngspice/models )
.endc

.lib /Users/techhu/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/ngspice/models/cornerMOSlv.lib mos_tt

MPM3 net_c1 net_c1 vdd vdd sg13_lv_pmos W=0.5u L=10u

Vdd vdd 0 1.2

.op
.print dc v(net_c1)
.end
