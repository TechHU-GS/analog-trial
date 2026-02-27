/*
 * Copyright (c) 2025 TechHU
 * SPDX-License-Identifier: Apache-2.0
 *
 * Configurable ring oscillator for IHP SG13G2 process characterization.
 *
 * ui_in[0]   = enable (1 = oscillate, 0 = hold low)
 * ui_in[3:1] = chain select (tap point for uo_out[0])
 * uo_out[0]  = selected ring output
 * uo_out[1]  = chain 7 output
 * uo_out[2]  = chain 13 output
 * uo_out[3]  = chain 21 output
 * uo_out[4]  = chain 51 output
 * uo_out[5]  = chain 101 output
 * uo_out[6]  = chain 201 output
 * uo_out[7]  = chain 501 output
 */

`default_nettype none

module tt_um_techhu_analog_trial (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);

  // ---------- parameters ----------
  localparam N = 501;  // total inverters

  // ---------- inverter chain ----------
  wire [N-1:0] chain;

  // Enable-gated feedback: NAND at head
  // When enable=0, nand_out=1, chain holds static
  // When enable=1, nand_out=~chain[N-1], ring oscillates
  wire enable = ui_in[0] & ena & rst_n;
  wire nand_out = ~(enable & chain[N-1]);

  // First inverter driven by NAND gate
  assign chain[0] = ~nand_out;

  // Remaining inverters
  genvar i;
  generate
    for (i = 1; i < N; i = i + 1) begin : inv
      assign chain[i] = ~chain[i-1];
    end
  endgenerate

  // ---------- output taps ----------
  // Fixed taps at various chain lengths for frequency comparison
  wire [7:0] taps;
  assign taps[0] = chain[6];    // 7 inverters
  assign taps[1] = chain[12];   // 13 inverters
  assign taps[2] = chain[20];   // 21 inverters
  assign taps[3] = chain[50];   // 51 inverters
  assign taps[4] = chain[100];  // 101 inverters
  assign taps[5] = chain[200];  // 201 inverters
  assign taps[6] = chain[350];  // 351 inverters
  assign taps[7] = chain[N-1];  // 501 inverters (full chain)

  // Mux: ui_in[3:1] selects which tap drives uo_out[0]
  assign uo_out[0] = taps[ui_in[3:1]];

  // Direct tap outputs
  assign uo_out[1] = taps[0];   // 7-inv
  assign uo_out[2] = taps[1];   // 13-inv
  assign uo_out[3] = taps[2];   // 21-inv
  assign uo_out[4] = taps[3];   // 51-inv
  assign uo_out[5] = taps[4];   // 101-inv
  assign uo_out[6] = taps[5];   // 201-inv
  assign uo_out[7] = taps[6];   // 351-inv

  // Bidir pins: output full chain + extra taps
  assign uio_oe  = 8'b1111_1111;
  assign uio_out[0] = taps[7];  // 501-inv (full chain)
  assign uio_out[1] = chain[2];   // 3-inv (fastest)
  assign uio_out[2] = chain[4];   // 5-inv
  assign uio_out[3] = chain[30];  // 31-inv
  assign uio_out[4] = chain[74];  // 75-inv
  assign uio_out[5] = chain[148]; // 149-inv
  assign uio_out[6] = chain[250]; // 251-inv
  assign uio_out[7] = chain[400]; // 401-inv

  wire _unused = &{uio_in, clk, ui_in[7:4]};

endmodule
