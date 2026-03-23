#!/bin/bash
source ~/pdk/venv/bin/activate
ngspice << 'NGEOF'
osdi /Users/techhu/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/ngspice/osdi/psp103.osdi
osdi /Users/techhu/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/ngspice/osdi/psp103_nqs.osdi
osdi /Users/techhu/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/ngspice/osdi/r3_cmc.osdi
osdi /Users/techhu/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/ngspice/osdi/mosvar.osdi
set sourcepath = ( /Users/techhu/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/ngspice/models )
source soilz_postsim.sp
tran 5n 5u uic
meas tran vco_period trig v(vco_out) val=0.6 rise=3 targ v(vco_out) val=0.6 rise=13
meas tran vptat_v avg v(vptat) from=2u to=3.5u
meas tran nbias_v avg v(nmos_bias) from=2u to=3.5u
meas tran pbias_v avg v(pmos_bias) from=2u to=3.5u
meas tran ota_v avg v(ota_out) from=2u to=3.5u
meas tran excout_v avg v(exc_out) from=2u to=3.5u
quit
NGEOF
