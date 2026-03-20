`timescale 1ns / 1ps

module tb_soilz_digital;

    reg vco_out, freq_sel, iq_sel, reset_b;
    wire div2_I, div4_I, div16_I, div4_Q, div16_Q;
    wire ref_I, ref_Q, buf_ref_I, buf_ref_Q;
    wire phi_p, phi_n, f_exc, f_exc_b;

    soilz_digital dut (
        .vco_out(vco_out),
        .freq_sel(freq_sel),
        .iq_sel(iq_sel),
        .reset_b(reset_b),
        .div2_I(div2_I),
        .div4_I(div4_I),
        .div16_I(div16_I),
        .div4_Q(div4_Q),
        .div16_Q(div16_Q),
        .ref_I(ref_I),
        .ref_Q(ref_Q),
        .buf_ref_I(buf_ref_I),
        .buf_ref_Q(buf_ref_Q),
        .phi_p(phi_p),
        .phi_n(phi_n),
        .f_exc(f_exc),
        .f_exc_b(f_exc_b)
    );

    // 9MHz VCO clock → 111ns period
    initial vco_out = 0;
    always #55.5 vco_out = ~vco_out;

    integer errors = 0;

    task check(input string name, input logic actual, input logic expected);
        if (actual !== expected) begin
            $display("FAIL: %s = %b, expected %b at %0t", name, actual, expected, $time);
            errors = errors + 1;
        end
    endtask

    initial begin
        $dumpfile("soilz_digital.vcd");
        $dumpvars(0, tb_soilz_digital);

        // Reset
        reset_b = 0; freq_sel = 0; iq_sel = 0;
        #200;
        reset_b = 1;
        #50;

        // ═══ Test 1: Divider chain ═══
        $display("=== Test 1: Divider chain ===");

        // Wait for a few VCO cycles, check div2_I toggles
        @(posedge div2_I);
        @(negedge div2_I);
        @(posedge div2_I);
        $display("  div2_I toggling OK at %0t", $time);

        // Check div4
        @(posedge div4_I);
        @(negedge div4_I);
        @(posedge div4_I);
        $display("  div4_I toggling OK at %0t", $time);

        // Wait for div16
        @(posedge div16_I);
        $display("  div16_I first edge at %0t", $time);

        // ═══ Test 2: f_exc complement ═══
        $display("=== Test 2: f_exc complement ===");
        #100;
        check("f_exc_b vs f_exc", f_exc_b, ~f_exc);

        // ═══ Test 3: Non-overlap (phi_p and phi_n never both high) ═══
        $display("=== Test 3: Non-overlap clock ===");
        repeat (100) begin
            #5;
            if (phi_p === 1 && phi_n === 1) begin
                $display("FAIL: phi_p and phi_n both HIGH at %0t — shoot-through!", $time);
                errors = errors + 1;
            end
        end
        $display("  Non-overlap check done (100 samples)");

        // ═══ Test 4: MUX freq_sel ═══
        $display("=== Test 4: MUX freq_sel ===");
        freq_sel = 0; iq_sel = 0;
        #500;
        // f_exc should follow div4_I when freq_sel=0
        check("f_exc == div4_I (freq_sel=0)", f_exc, div4_I);

        freq_sel = 1;
        #500;
        // f_exc should follow div16_I when freq_sel=1
        check("f_exc == div16_I (freq_sel=1)", f_exc, div16_I);

        // ═══ Test 5: MUX iq_sel ═══
        $display("=== Test 5: MUX iq_sel ===");
        freq_sel = 0; iq_sel = 1;
        #500;
        // f_exc should follow div4_Q when iq_sel=1
        check("f_exc == div4_Q (iq_sel=1)", f_exc, div4_Q);

        // ═══ Summary ═══
        #100;
        if (errors == 0)
            $display("ALL TESTS PASSED");
        else
            $display("FAILED: %0d errors", errors);

        $finish;
    end

    // Timeout
    initial begin
        #100000;
        $display("TIMEOUT");
        $finish;
    end

endmodule
