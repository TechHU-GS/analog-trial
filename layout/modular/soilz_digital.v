// SoilZ v1 — Complete digital block
// Replaces 164 custom transistors with ~23 standard cells
//
// Blocks:
//   1. VCO buffer chain (3 INV)
//   2. TFF divider chain (7 DFF)
//   3. Frequency select MUX (3 MUX2)
//   4. Output buffers (2 INV)
//   5. Non-overlap clock generator (5 INV + 2 NAND2)
//   6. Clock buffer (1 INV, shared with NOL)

module soilz_digital (
    // From analog: VCO output
    input  wire vco_out,

    // From analog: excitation frequency select
    input  wire freq_sel,     // MUX select for I-channel
    input  wire iq_sel,       // MUX select for I/Q

    // Reset (directly active-low, active-high)
    input  wire reset_b,

    // To analog: divided clocks for MUX selection
    output wire div2_I,
    output wire div4_I,
    output wire div16_I,
    output wire div4_Q,
    output wire div16_Q,

    // To analog: buffered reference clocks
    output wire ref_I,        // selected frequency I-channel
    output wire ref_Q,        // selected frequency Q-channel
    output wire buf_ref_I,    // buffered ref_I
    output wire buf_ref_Q,    // buffered ref_Q

    // To analog: non-overlap clocks for H-bridge
    output wire phi_p,        // positive phase
    output wire phi_n,        // negative phase

    // To analog: excitation signal
    output wire f_exc,        // excitation frequency
    output wire f_exc_b       // complement
);

    // ════════════════════════════════════════════
    // 1. VCO buffer chain: vco_out → vco_buf → vco_buf_b
    // ════════════════════════════════════════════
    wire vco_b, vco_buf, vco_buf_b;

    (* keep *) sg13g2_inv_1 INV_VCO   (.A(vco_out),  .Y(vco_b));
    (* keep *) sg13g2_inv_2 INV_iso   (.A(vco_out),  .Y(vco_buf));
    (* keep *) sg13g2_inv_2 INV_isob  (.A(vco_buf),  .Y(vco_buf_b));

    // ════════════════════════════════════════════
    // 2. TFF divider chain: 7 toggle FFs
    //    vco_buf → /2(I,Q) → /4(I,Q) → /8 → /16(I,Q)
    // ════════════════════════════════════════════
    wire div2_I_b, div2_Q, div2_Q_b;
    wire div4_I_b, div4_Q_b;
    wire div8, div8_b;
    wire div16_I_b, div16_Q_b;

    // T1I: vco_buf_b → div2_I (TSPC uses inverted clock)
    sg13g2_dfrbp_1 T1I (.CLK(vco_buf_b), .D(div2_I_b),
                         .RESET_B(reset_b), .Q(div2_I), .Q_N(div2_I_b));

    // T1Q: vco_buf → div2_Q (quadrature: opposite clock edge)
    (* keep *) sg13g2_dfrbp_1 T1Q (.CLK(vco_buf),   .D(div2_Q_b),
                         .RESET_B(reset_b), .Q(div2_Q), .Q_N(div2_Q_b));

    // T2I: div2_I → div4_I
    sg13g2_dfrbp_1 T2I (.CLK(div2_I),    .D(div4_I_b),
                         .RESET_B(reset_b), .Q(div4_I), .Q_N(div4_I_b));

    // T2Q: div2_I → div4_Q
    sg13g2_dfrbp_1 T2Q (.CLK(div2_I),    .D(div4_Q_b),
                         .RESET_B(reset_b), .Q(div4_Q), .Q_N(div4_Q_b));

    // T3: div4_I → div8
    sg13g2_dfrbp_1 T3  (.CLK(div4_I),    .D(div8_b),
                         .RESET_B(reset_b), .Q(div8), .Q_N(div8_b));

    // T4I: div8 → div16_I
    sg13g2_dfrbp_1 T4I (.CLK(div8),      .D(div16_I_b),
                         .RESET_B(reset_b), .Q(div16_I), .Q_N(div16_I_b));

    // T4Q: div8 → div16_Q
    sg13g2_dfrbp_1 T4Q (.CLK(div8),      .D(div16_Q_b),
                         .RESET_B(reset_b), .Q(div16_Q), .Q_N(div16_Q_b));

    // ════════════════════════════════════════════
    // 3. Frequency select MUX
    //    MXfi: selects I-channel frequency (div4_I or div16_I)
    //    MXfq: selects Q-channel frequency (div4_Q or div16_Q)
    //    MXiq: selects I or Q channel
    // ════════════════════════════════════════════
    wire mxfi_out, mxfq_out;

    // freq_sel=0 → div4, freq_sel=1 → div16
    sg13g2_mux2_1 MXfi (.A0(div4_I),  .A1(div16_I),
                         .S(freq_sel), .X(mxfi_out));
    sg13g2_mux2_1 MXfq (.A0(div4_Q),  .A1(div16_Q),
                         .S(freq_sel), .X(mxfq_out));

    // iq_sel=0 → I-channel, iq_sel=1 → Q-channel
    sg13g2_mux2_1 MXiq (.A0(mxfi_out), .A1(mxfq_out),
                         .S(iq_sel),    .X(f_exc));

    // ════════════════════════════════════════════
    // 4. Excitation complement + output buffers
    // ════════════════════════════════════════════
    sg13g2_inv_1 INV_exc  (.A(f_exc),     .Y(f_exc_b));
    sg13g2_inv_1 BUF_I    (.A(ref_I),     .Y(buf_ref_I));
    sg13g2_inv_1 BUF_Q    (.A(ref_Q),     .Y(buf_ref_Q));

    // ref_I and ref_Q are MUX outputs (directly from MXfi/MXfq)
    assign ref_I = mxfi_out;
    assign ref_Q = mxfq_out;

    // ════════════════════════════════════════════
    // 5. Non-overlap clock generator
    //    f_exc → delayed → NAND with original → phi_p/phi_n
    //    Prevents H-bridge shoot-through
    // ════════════════════════════════════════════
    wire da1, f_exc_d;      // delay chain A
    wire db1, f_exc_b_d;    // delay chain B
    wire nand_a, nand_b;

    // Delay chain A: f_exc → da1 → f_exc_d
    sg13g2_inv_1 DA1 (.A(f_exc),   .Y(da1));
    sg13g2_inv_1 DA2 (.A(da1),     .Y(f_exc_d));

    // Delay chain B: f_exc_b → db1 → f_exc_b_d
    sg13g2_inv_1 DB1 (.A(f_exc_b), .Y(db1));
    sg13g2_inv_1 DB2 (.A(db1),     .Y(f_exc_b_d));

    // NAND + INV = non-overlap
    sg13g2_nand2_1 NA (.A(f_exc),   .B(f_exc_d),   .Y(nand_a));
    sg13g2_inv_1   IA (.A(nand_a),  .Y(phi_p));

    sg13g2_nand2_1 NB (.A(f_exc_b), .B(f_exc_b_d), .Y(nand_b));
    sg13g2_inv_1   IB (.A(nand_b),  .Y(phi_n));

endmodule
