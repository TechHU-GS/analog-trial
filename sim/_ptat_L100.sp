** PTAT Core only — 100µs settling test
** Same params as SoilZ (L=10µm mirror)
.include '_pdk_corner.inc'

** PTAT Mirror (L=10µm, SoilZ value)
XPM3 net_c1 net_c1 vdd vdd sg13_lv_pmos w=0.5u l=100u ng=1 m=1
XPM4 net_c2 net_c1 vdd vdd sg13_lv_pmos w=0.5u l=100u ng=1 m=1
XPM5 vptat net_c1 vdd vdd sg13_lv_pmos w=0.5u l=100u ng=1 m=1
XPM_ref nmos_bias net_c1 vdd vdd sg13_lv_pmos w=0.5u l=100u ng=1 m=1

** Vittoz NMOS
XMN1 net_c1 net_c1 0 0 sg13_lv_nmos w=2u l=4u ng=1 m=1
XMN2 net_c2 net_c1 net_rptat 0 sg13_lv_nmos w=16u l=4u ng=8 m=1

** Bias gen
XMN_diode nmos_bias nmos_bias 0 0 sg13_lv_nmos w=1u l=2u ng=1 m=1
XMN_pgen pmos_bias nmos_bias 0 0 sg13_lv_nmos w=1u l=2u ng=1 m=1
XPM_pdiode pmos_bias pmos_bias vdd vdd sg13_lv_pmos w=0.5u l=2u ng=1 m=1

** Resistors
XRptat net_rptat 0 0 rhigh w=0.5e-6 l=133e-6 b=12 m=1
XRout vptat 0 0 rppd w=0.5e-6 l=25e-6 b=4 m=1

Vdd vdd 0 1.2

.ic v(net_c1)=0.9 v(net_c2)=0.9 v(nmos_bias)=0.5 v(pmos_bias)=0.8 v(vptat)=0.1
.tran 10n 100u uic

.control
run
echo ""
echo "=== PTAT Settling (L=10µm mirror) ==="
echo "--- At 1µs ---"
meas tran vptat_1u find v(vptat) at=1u
meas tran vnet_c1_1u find v(net_c1) at=1u
echo "--- At 10µs ---"
meas tran vptat_10u find v(vptat) at=10u
meas tran vnet_c1_10u find v(net_c1) at=10u
echo "--- At 50µs ---"
meas tran vptat_50u find v(vptat) at=50u
echo "--- At 100µs ---"
meas tran vptat_100u find v(vptat) at=100u
meas tran vnet_c1_100u find v(net_c1) at=100u
meas tran vnmos_bias_100u find v(nmos_bias) at=100u
meas tran vpmos_bias_100u find v(pmos_bias) at=100u
echo ""
echo "=== Done ==="
quit
.endc

.end
