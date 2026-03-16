#!/bin/bash
cd /Users/techhu/Code/GS_IC/designs/analog-trial/sim
ngspice -n << 'NGSPICE'
osdi /Users/techhu/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/ngspice/osdi/psp103.osdi
osdi /Users/techhu/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/ngspice/osdi/psp103_nqs.osdi
osdi /Users/techhu/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/ngspice/osdi/r3_cmc.osdi
osdi /Users/techhu/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/ngspice/osdi/mosvar.osdi
set sourcepath = ( /Users/techhu/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/ngspice/models )
source _test_2dev.sp
run
print v(net_c1) v(net_c2) v(vdd)
quit
NGSPICE
