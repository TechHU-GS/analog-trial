** Measure: TFF switching current drawn from VDD/GND
** 7 TFFs driven by ideal 10MHz clock, measure supply current
.include '_pdk_corner.inc'

** Ideal clock
Vclk vco_out 0 pulse(0 1.2 0 0.5n 0.5n 50n 100n)
XINV_n vco_b vco_out 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XINV_p vco_b vco_out vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1

** VDD through sense resistor (1mΩ — negligible drop, measurable current)
Vdd_ext vdd_ext 0 1.2
Vsense vdd_ext vdd 0

XT1I_m1 div2_I_b vco_b t1I_m 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT1I_m2 div2_I_b vco_out t1I_m vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1I_m3 t1I_mb t1I_m 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT1I_m4 t1I_mb t1I_m vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1I_m5 t1I_nmp vco_b vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1I_m6 t1I_m t1I_mb t1I_nmp vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1I_m7 t1I_m t1I_mb t1I_nmn 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT1I_m8 t1I_nmn vco_out 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT1I_s1 t1I_m vco_out div2_I 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT1I_s2 t1I_m vco_b div2_I vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1I_s3 div2_I_b div2_I 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT1I_s4 div2_I_b div2_I vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1I_s5 t1I_nsp vco_out vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1I_s6 div2_I div2_I_b t1I_nsp vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1I_s7 div2_I div2_I_b t1I_nsn 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT1I_s8 t1I_nsn vco_b 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT1Q_m1 div2_Q_b vco_out t1Q_m 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT1Q_m2 div2_Q_b vco_b t1Q_m vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1Q_m3 t1Q_mb t1Q_m 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT1Q_m4 t1Q_mb t1Q_m vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1Q_m5 t1Q_nmp vco_out vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1Q_m6 t1Q_m t1Q_mb t1Q_nmp vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1Q_m7 t1Q_m t1Q_mb t1Q_nmn 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT1Q_m8 t1Q_nmn vco_b 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT1Q_s1 t1Q_m vco_b div2_Q 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT1Q_s2 t1Q_m vco_out div2_Q vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1Q_s3 div2_Q_b div2_Q 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT1Q_s4 div2_Q_b div2_Q vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1Q_s5 t1Q_nsp vco_b vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1Q_s6 div2_Q div2_Q_b t1Q_nsp vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT1Q_s7 div2_Q div2_Q_b t1Q_nsn 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT1Q_s8 t1Q_nsn vco_out 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2I_m1 div4_I_b div2_I_b t2I_m 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2I_m2 div4_I_b div2_I t2I_m vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2I_m3 t2I_mb t2I_m 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2I_m4 t2I_mb t2I_m vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2I_m5 t2I_nmp div2_I_b vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2I_m6 t2I_m t2I_mb t2I_nmp vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2I_m7 t2I_m t2I_mb t2I_nmn 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2I_m8 t2I_nmn div2_I 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2I_s1 t2I_m div2_I div4_I 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2I_s2 t2I_m div2_I_b div4_I vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2I_s3 div4_I_b div4_I 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2I_s4 div4_I_b div4_I vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2I_s5 t2I_nsp div2_I vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2I_s6 div4_I div4_I_b t2I_nsp vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2I_s7 div4_I div4_I_b t2I_nsn 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2I_s8 t2I_nsn div2_I_b 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2Q_m1 div4_Q_b div2_I t2Q_m 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2Q_m2 div4_Q_b div2_I_b t2Q_m vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2Q_m3 t2Q_mb t2Q_m 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2Q_m4 t2Q_mb t2Q_m vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2Q_m5 t2Q_nmp div2_I vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2Q_m6 t2Q_m t2Q_mb t2Q_nmp vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2Q_m7 t2Q_m t2Q_mb t2Q_nmn 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2Q_m8 t2Q_nmn div2_I_b 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2Q_s1 t2Q_m div2_I_b div4_Q 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2Q_s2 t2Q_m div2_I div4_Q vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2Q_s3 div4_Q_b div4_Q 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2Q_s4 div4_Q_b div4_Q vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2Q_s5 t2Q_nsp div2_I_b vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2Q_s6 div4_Q div4_Q_b t2Q_nsp vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT2Q_s7 div4_Q div4_Q_b t2Q_nsn 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT2Q_s8 t2Q_nsn div2_I 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT3_m1 div8_b div4_I_b t3_m 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT3_m2 div8_b div4_I t3_m vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT3_m3 t3_mb t3_m 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT3_m4 t3_mb t3_m vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT3_m5 t3_nmp div4_I_b vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT3_m6 t3_m t3_mb t3_nmp vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT3_m7 t3_m t3_mb t3_nmn 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT3_m8 t3_nmn div4_I 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT3_s1 t3_m div4_I div8 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT3_s2 t3_m div4_I_b div8 vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT3_s3 div8_b div8 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT3_s4 div8_b div8 vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT3_s5 t3_nsp div4_I vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT3_s6 div8 div8_b t3_nsp vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT3_s7 div8 div8_b t3_nsn 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT3_s8 t3_nsn div4_I_b 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4I_m1 div16_I_b div8_b t4I_m 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4I_m2 div16_I_b div8 t4I_m vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4I_m3 t4I_mb t4I_m 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4I_m4 t4I_mb t4I_m vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4I_m5 t4I_nmp div8_b vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4I_m6 t4I_m t4I_mb t4I_nmp vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4I_m7 t4I_m t4I_mb t4I_nmn 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4I_m8 t4I_nmn div8 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4I_s1 t4I_m div8 div16_I 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4I_s2 t4I_m div8_b div16_I vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4I_s3 div16_I_b div16_I 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4I_s4 div16_I_b div16_I vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4I_s5 t4I_nsp div8 vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4I_s6 div16_I div16_I_b t4I_nsp vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4I_s7 div16_I div16_I_b t4I_nsn 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4I_s8 t4I_nsn div8_b 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4Q_m1 div16_Q_b div8 t4Q_m 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4Q_m2 div16_Q_b div8_b t4Q_m vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4Q_m3 t4Q_mb t4Q_m 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4Q_m4 t4Q_mb t4Q_m vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4Q_m5 t4Q_nmp div8 vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4Q_m6 t4Q_m t4Q_mb t4Q_nmp vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4Q_m7 t4Q_m t4Q_mb t4Q_nmn 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4Q_m8 t4Q_nmn div8_b 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4Q_s1 t4Q_m div8_b div16_Q 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4Q_s2 t4Q_m div8 div16_Q vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4Q_s3 div16_Q_b div16_Q 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4Q_s4 div16_Q_b div16_Q vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4Q_s5 t4Q_nsp div8_b vdd vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4Q_s6 div16_Q div16_Q_b t4Q_nsp vdd sg13_lv_pmos w=2u l=0.5u ng=1 m=1
XT4Q_s7 div16_Q div16_Q_b t4Q_nsn 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
XT4Q_s8 t4Q_nsn div8 0 0 sg13_lv_nmos w=1u l=0.5u ng=1 m=1
.tran 0.1n 2u

** Measure peak and average supply current
.meas tran i_peak max i(Vsense)
.meas tran i_avg avg i(Vsense)
.meas tran i_rms rms i(Vsense)

.end
