import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def test_enable_low(dut):
    """When enable=0, outputs should be static"""
    dut.ena.value = 1
    dut.rst_n.value = 1
    dut.ui_in.value = 0  # enable=0
    dut.clk.value = 0

    await Timer(100, units="ns")
    val1 = dut.uo_out.value

    await Timer(100, units="ns")
    val2 = dut.uo_out.value

    # With enable=0, output should be stable (not oscillating in RTL sim)
    assert val1 == val2, f"Output should be static when disabled: {val1} vs {val2}"

@cocotb.test()
async def test_enable_high(dut):
    """When enable=1, ring oscillator is active"""
    dut.ena.value = 1
    dut.rst_n.value = 1
    dut.ui_in.value = 1  # enable=1, sel=0
    dut.clk.value = 0

    await Timer(10, units="ns")
    # In RTL simulation, combinational loop settles to X or oscillates
    # Just check it doesn't crash
    dut._log.info(f"uo_out = {dut.uo_out.value}")
