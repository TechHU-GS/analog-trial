// SoilZ frequency divider chain — 7 TSPC FFs
// Replaces 112 custom transistors (7 × 16) with 7 standard cell FFs
//
// Divider chain:
//   vco_buf → /2 (T1I,T1Q) → /4 (T2I,T2Q) → /8 (T3) → /16 (T4I,T4Q)
//
// Each FF is a simple DFF with reset, feedback-connected as toggle FF:
//   D = ~Q (toggle mode = divide-by-2)

module tff_divider (
    input  wire clk_vco,      // VCO buffer output (highest freq)
    input  wire reset_b,      // Active-low reset
    output wire div2_I,
    output wire div2_I_b,
    output wire div2_Q,       // Quadrature
    output wire div2_Q_b,
    output wire div4_I,
    output wire div4_I_b,
    output wire div4_Q,
    output wire div4_Q_b,
    output wire div8,
    output wire div8_b,
    output wire div16_I,
    output wire div16_I_b,
    output wire div16_Q,
    output wire div16_Q_b
);

    // T1I: vco_buf → div2_I (toggle FF on rising edge)
    sg13g2_dfrbp_1 T1I (
        .CLK(clk_vco),
        .D(div2_I_b),
        .RESET_B(reset_b),
        .Q(div2_I),
        .Q_N(div2_I_b)
    );

    // T1Q: vco_buf → div2_Q (toggle FF on falling edge = Q output)
    sg13g2_dfrbp_1 T1Q (
        .CLK(~clk_vco),
        .D(div2_Q_b),
        .RESET_B(reset_b),
        .Q(div2_Q),
        .Q_N(div2_Q_b)
    );

    // T2I: div2_I → div4_I
    sg13g2_dfrbp_1 T2I (
        .CLK(div2_I),
        .D(div4_I_b),
        .RESET_B(reset_b),
        .Q(div4_I),
        .Q_N(div4_I_b)
    );

    // T2Q: div2_I → div4_Q
    sg13g2_dfrbp_1 T2Q (
        .CLK(div2_I),
        .D(div4_Q_b),
        .RESET_B(reset_b),
        .Q(div4_Q),
        .Q_N(div4_Q_b)
    );

    // T3: div4_I → div8
    sg13g2_dfrbp_1 T3 (
        .CLK(div4_I),
        .D(div8_b),
        .RESET_B(reset_b),
        .Q(div8),
        .Q_N(div8_b)
    );

    // T4I: div8 → div16_I
    sg13g2_dfrbp_1 T4I (
        .CLK(div8),
        .D(div16_I_b),
        .RESET_B(reset_b),
        .Q(div16_I),
        .Q_N(div16_I_b)
    );

    // T4Q: div8 → div16_Q
    sg13g2_dfrbp_1 T4Q (
        .CLK(div8),
        .D(div16_Q_b),
        .RESET_B(reset_b),
        .Q(div16_Q),
        .Q_N(div16_Q_b)
    );

endmodule
