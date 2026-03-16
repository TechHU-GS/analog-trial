# SoilZ v1 — Lock-In Impedance Analyzer Design Notes

## Architecture

1-bit IQ lock-in ΣΔ impedance analyzer for soil moisture sensing.
Chopper = lock-in demodulator (not offset cancellation), multiplies sensor signal by ±1 at f_exc.

Signal chain: H-bridge excitation → soil probe → chopper → CT-ΣΔ integrator → bitstream → ESP32

## Verified SPICE Blocks (2026-03-08)

### Programmable Current Source (`soilz_current_src.sp`)
- 3 binary-weighted legs (×1/×2/×4) from PTAT net_c1
- Cascode for high Zout: PM_cas + PM_mir (L=10u/L=2u)
- CMOS TG enable switches
- **Results**: 7 codes (3.65–24.2µA), Zout≈4.7MΩ, leakage 44.7pA
- Temp: CTAT (27.7µA@-40°C → 21.2µA@125°C)

### H-Bridge + Non-Overlap Clock (`soilz_hbridge.sp`)
- Feedforward non-overlap (no feedback → guaranteed startup)
- phi_p = AND(f_exc, delayed_f_exc), phi_n = AND(f_exc_b, delayed_f_exc_b)
- 4 NMOS switches (W=4u L=0.5u ng=2)
- Dead time ~2-5ns, no shoot-through verified

### 5-Transistor OTA (`soilz_ota.sp`)
- NMOS diff pair: W=10u L=2u ng=4 (low offset)
- PMOS mirror load: W=4u L=4u (high ro)
- NMOS tail: W=8u L=4u ng=2 (20µA total)
- Bias: 10µA ideal source + diode-connected W=4u L=4u
- **Results**: Gain=30.5dB, GBW=18.5MHz, PM≈178°
- Temp: 32.3dB/-40°C to 27.1dB/125°C — stable
- 30dB sufficient for 1st-order ΣΔ with OSR=45000
- Folded-cascode abandoned (4 iterations failed: bias issues, fold node collapse)

### Strong-Arm Comparator (`soilz_comparator.sp`)
- Standard Strong-arm: 11T (input pair + precharge + NMOS/PMOS latch + reset)
- Clocked at 9MHz (VCO frequency)
- **Results**: <0.1mV sensitivity, rail-to-rail output
- Stable -40 to 125°C
- v1 had broken di_p/di_n (no precharge) — fixed in v2

### CT-ΣΔ Modulator (`soilz_sigma_delta.sp`)
- Proper inverting integrator: OTA(+)=Vref, OTA(-)=summing node
- C_fb=1pF (output to summing node), R_in=R_dac=200kΩ
- SR latch (NAND-based, 8T) captures comparator decision through reset
- TG DAC (4T): switches between V_hi=0.95V and V_lo=0.85V
- **Results**: Density linear within ±1% of expected
- Valid input range: VDD/2 ± 50mV (chopper output)
- Temp: ±3% density drift across -40 to 125°C

### Lock-In System (`soilz_system_v3.sp`)
- Chopper (4× CMOS TG) swaps sens_p/sens_n at f_exc → demodulates to DC
- Demodulated signal → CT-ΣΔ → bitstream
- **Results**: Excellent linearity (0-45mV VPROBE)
  - VPROBE=0: density=0.489, VPROBE=45mV: density=0.050
  - Chopper avg = 0.9 + VPROBE (perfect demodulation)
- Temp: ~20% density variation over -40 to 125°C (chopper TG contributes)

## Design Decisions & Lessons

### OTA Gain Trade-offs (IHP SG13G2)
- Increasing PMOS L beyond 4u REDUCES gain (current density mismatch, high-temp collapse)
- Increasing NMOS input L from 2u to 4u halves gain (lower gm dominates)
- 5T OTA with L=2u/4u at 10µA → 30dB is the sweet spot for this process
- Don't chase higher gain with simple topology changes — need cascode or 2-stage

### ΣΔ Architecture
- v1-v3 failed: OTA as open-loop amp driving C_int to ground → railed every cycle
- v4 fixed: Proper inverting integrator with C_fb (Miller feedback) + resistive input
- Integration time constant τ=R×C controls loop gain independently of OTA gain
- DAC must use latched comparator output (SR latch) — Strong-arm resets both outputs to VDD
- DAC range must bracket the input signal range

### Chopper
- Must swap sensor p/n connections (not signal/bias) to demodulate
- Single-ended chopper: TG1 passes sens_p when f_exc=HIGH, TG2 passes sens_n when f_exc=LOW
- Result: rectified differential signal → DC proportional to impedance

### Valid Impedance Range
- ΣΔ input range: VDD/2 ± 50mV (DAC range [0.85, 0.95V])
- Max VPROBE = 50mV = I_exc × R_probe / 2
- R_max per current setting:
  - All (24µA): R_max ≈ 4.2kΩ
  - x4 (13.7µA): R_max ≈ 7.3kΩ
  - x2 (6.9µA): R_max ≈ 14.5kΩ
  - x1 (3.7µA): R_max ≈ 27kΩ
- ESP32 selects current level based on initial impedance measurement

### ngspice Issues
- f_exc_b inverter causes "timestep too small" at ~19-25µs — convergence issue
- Workaround: use buffered clock or add stabilization cap
- `alterparam` + `reset` works for parameter sweeps (not just `alter`)
- NAND SR latch with active-low inputs works correctly with Strong-arm outputs

## Transistor Count

### Measurement Path (35T + passives)
- Chopper: 4T
- OTA + bias: 6T
- Comparator: 11T
- SR Latch: 8T
- DAC: 4T
- f_exc inverter: 2T
- Passives: 1pF cap_cmim + 2×200kΩ rhigh

### Digital Block (138T) — verified `soilz_digital.sp`
- 7× TFF (16T each): 112T
- 3× MUX2 (6T each): 18T
- 3× output buffer INV: 6T
- VCO complement INV: 2T

### TFF Architecture (16T — CRITICAL)
- Master: TG(2T) + INV(2T) + TRI_INV feedback(4T) = 8T
- Slave: TG(2T) + INV(2T) + TRI_INV feedback(4T) = 8T
- **12T TG-feedback design DOES NOT WORK**: TG+INV loop = 1 inversion = negative feedback → metastable at VDD/2
- **16T tri-state-INV design works**: TRI_INV+INV loop = 2 inversions = positive feedback → proper latch
- TG passes D to latch node; TRI_INV provides clocked feedback with inversion
- **Slave receives m (not m_b)**: ensures D=Q_b → new_Q = INV(old_Q) toggle
- Must NOT use `uic` with subcircuit TFFs — let ngspice find operating point

### Quadrature Architecture (TFF-pairs)
- TFF_I(clk=Q_prev) and TFF_Q(clk=Q_prev_b) at same freq, 90° apart
- Q_b rising edges are half-period shifted → 90° of output frequency
- **Original plan cascade approach was WRONG**: TFF[n] and TFF[n-1] are at DIFFERENT frequencies, not quadrature
- Verified: phase errors <1° at ÷2, ÷4, ÷16

### Divider Chain
- VCO(9MHz) → TFF_1I/1Q(÷2) → TFF_2I/2Q(÷4) → TFF_3(÷8) → TFF_4I/4Q(÷16)
- Freq select: 1-bit MUX (÷4 or ÷16)
- I/Q select: 1-bit MUX (chopper phase)
- All digital transistors: nmos_vco (w=1u l=0.5u) + pmos_vco (w=2u l=0.5u)

## Verified Assumptions (2026-03-08)

### SG13G2 器件可用性 — ✅ 全部确认
- PDK README: "poly silicon resistors and MIM capacitors are available"
- BEOL: 5 thin metal (M1-M5) + 2 thick metal (TopMetal1/2) + MIM layer，标准后端全含
- TTIHP shuttle 用 SG13G2 BiCMOS 晶圆，CMOS-only 设计完全兼容
- **sg13_lv_nmos/pmos**: cornerMOSlv.lib ✅
- **rhigh**: cornerRES.lib, rsh=1360 Ω/sq (typical), effective ~1490 at w=0.5µm ✅
- **cap_cmim**: capacitors_mod.lib, Caspec=1.5 fF/µm², M5↔TopMetal1 层栈 ✅

### rhigh 200kΩ — ✅ ngspice 仿真验证
- w=0.5µm l=20µm b=2 → 198,992 Ω (误差 0.5%)
- 温漂 TC1=-2300 ppm/°C (-40°C: 233kΩ, 125°C: 159kΩ)
- R_in/R_dac 比值恒为1，ΣΔ DC 传函不受温漂影响

### cap_cmim 1pF — ✅ KLayout PCell 探测
- PCell class = "cmim" (不是 "cap_cmim"), library = SG13_dev
- 26×26µm → bbox 27.2×27.2µm, 1.01pF
- 层: TopMetal1 (top plate), M5/layer36 (bottom plate), TopVia1/layer129 (400 via cuts)
- ATK 不能自动路由（M3+以上），需在 assemble_gds.py 手动放置 + via stack
- integrate_tile.py 已有 M2→TopMetal1 via stack 实现可复用

### TTIHP 混合流程 — ❌ 不支持
- 只有两条路径: 纯数字 (Verilog→LibreLane) 或 纯模拟 (custom_gds)
- 全离散 MOSFET + ATK 版图是唯一路线

### MOSFET-cap 做浮空电容 — ❌ 不可行
- C_fb 是 ota_out↔sum_n 浮空 Miller 反馈电容
- MOSFET-cap 一个极板连衬底(GND)，无法做两信号节点间浮空电容
- 必须用 cap_cmim (MIM)

## Phase 0 探测结果 (2026-03-08)
- 29/29 器件全部成功 → device_lib.json 已更新
- 14 新类型: pmos_cas_mir1/2/4, pmos_cas1/2/4, nmos_cas_load, pmos_ota_load,
  nmos_ota_bias, nmos_ota_input, nmos_ota_tail, pmos_comp_latch, rhigh_200k, cap_cmim_1p
- 15 复用现有类型 (pmos_vco, pmos_buf1, nmos_vco, nmos_buf1, nmos_buf2 等)

## Stage 7 进行中 — Placement

### Mirror L 变更 (未验证)
- pmos_mirror: l=100µm → l=10µm (PCell 101.3→11.3µm)
- 原因: l=100µm 的 4 个 mirror 宽度 (405µm) 超出 tile 宽度 (202µm)
- **未经 SPICE 验证**: 匹配精度/输出阻抗影响未知。用户建议 L=2-4µm 够用，选了 L=10 作为保守方案
- 前仿确认后才能锁定此参数

### VCO 行拆分
- vco_cs_p/n, vco_pu/pd 各拆成 _a(1-3) + _b(4-5) 两行
- 原因: 5×20µm=103µm 单行太宽; 拆后最宽 62µm
- y_align 约束保持子组 Y 对齐
- routing_channels 对应更新 (6 channels → 对应 a/b 各 3)

### CP-SAT 结果 (grid ceil 修复后, 2026-03-08)
- FEASIBLE 600s (未达 OPTIMAL, 推测因 249 变量 + HPWL 复杂度)
- Bounding box: 127.1 × 164.2 µm (tile 202×314, 用 33%)
- HPWL: 1,206 µm
- 0 行分裂, VCO 子组 Y 对齐完美
- **min gap: 0.700µm, 0 violations**

### Grid quantization 修复
- `_to_g()` 用 `round()` 转换器件尺寸 → 可下舍最多 50nm
- 新增 `_size_g()` 用 `math.ceil()` 转换器件尺寸
- 修复前: 87 pairs gap < 700nm (最小 660nm), bbox 106×158
- 修复后: 0 violations, bbox 127×164 (+25% 面积, 符合预期)

### wirelength_weight
- 设为 1.0 (经验选择, 无严格依据)
- 优先 HPWL 减少 vs 面积

## Next Steps
- Stage 7 续: Phase 3 (ties) → Phase 4 (routing)
- **关键待办**: mirror L=10 SPICE 前仿验证
- Stage 8: GDS + DRC + LVS
- Stage 9: Tile 集成
