** Quick L=100µm mirror test (L2 original value)
.include '_pdk_corner.inc'

XPM3 net_c1 net_c1 vdd vdd sg13_lv_pmos w=0.5u l=100u ng=1 m=1
XPM4 net_c2 net_c1 vdd vdd sg13_lv_pmos w=0.5u l=100u ng=1 m=1
XPM5 vptat net_c1 vdd vdd sg13_lv_pmos w=0.5u l=100u ng=1 m=1
XMN1 net_c1 net_c1 0 0 sg13_lv_nmos w=2u l=4u ng=1 m=1
XMN2 net_c2 net_c1 net_rptat 0 sg13_lv_nmos w=16u l=4u ng=8 m=1
XRptat net_rptat 0 0 rhigh w=0.5e-6 l=133e-6 b=12 m=1
XRout vptat 0 0 rppd w=0.5e-6 l=25e-6 b=4 m=1

Vdd vdd 0 1.2

.ic v(net_c1)=0.9 v(net_c2)=0.9 v(vptat)=0.6
.tran 1n 5u uic

.control
run
print v(vptat)[length(v(vptat))-1]
quit
.endc

.end
