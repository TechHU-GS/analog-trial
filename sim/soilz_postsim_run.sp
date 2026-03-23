** SoilZ v1 functional sim with ngspice control block
.control
osdi /Users/techhu/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/ngspice/osdi/psp103.osdi
osdi /Users/techhu/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/ngspice/osdi/psp103_nqs.osdi
osdi /Users/techhu/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/ngspice/osdi/r3_cmc.osdi
osdi /Users/techhu/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/ngspice/osdi/mosvar.osdi
set sourcepath = ( /Users/techhu/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/ngspice/models )
source soilz_postsim.sp
tran 1n 20u uic
print v(vptat) v(nmos_bias) v(pmos_bias) v(vco_out) v(ota_out) v(sum_n) v(lat_q) v(exc_out) v(probe_p) v(probe_n)
meas tran vco_freq trig v(vco_out) val=0.6 rise=5 targ v(vco_out) val=0.6 rise=15
meas tran vptat_dc avg v(vptat) from=15u to=20u
meas tran nbias_dc avg v(nmos_bias) from=15u to=20u
meas tran pbias_dc avg v(pmos_bias) from=15u to=20u
meas tran ota_dc avg v(ota_out) from=15u to=20u
meas tran sumn_dc avg v(sum_n) from=15u to=20u
quit
.endc
.end
