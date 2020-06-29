#!/usr/bin/env python
# Copyright 2020 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""ICE40 single port RAM Wrapper
"""

from nmigen import *
from nmigen.back import verilog
from nmigen.back.pysim import Simulator

import argparse
import unittest

class SinglePortRam(Elaboratable):
    """Minimal wrapper around ICE40 single port RAM"""
    def __init__(self):
        self.addr = Signal(14)
        self.data_in = Signal(16)
        self.wren = Signal()
        self.cs = Signal()
        self.data_out = Signal(16)
        pass

    def elaborate(self, platform):
        m = Module()
        clock_signal = ClockSignal('sync')
        instance = Instance("SB_SPRAM256KA",
                i_DATAIN=self.data_in,
                i_ADDRESS=self.addr,
                i_MASKWREN=0xf,
                i_WREN=self.wren,
                i_CHIPSELECT=self.cs,
                i_CLOCK=clock_signal,
                i_STANDBY=0,
                i_SLEEP=0,
                i_POWEROFF=1, # Jeebus POWEROFF=1 means power on
                o_DATAOUT=self.data_out)
        m.submodules.spram = instance
        return m

class FakeSinglePortRam(SinglePortRam):
    """Fake RAM for testing.
       Due to (entirely understandable) limitations of the simulation
       framework, only 256 of the 16K words are emulated.
    """
    n_bits=8
    def elaborate(self, platform):
        m = Module()

        mem = Array(Signal(16, name=f"mem_{i:02d}") for i in range(2**self.n_bits))

        m.d.sync += self.data_out.eq(0)
        with m.If(self.cs):
            with m.If(self.wren):
                m.d.sync += mem[self.addr[:self.n_bits]].eq(self.data_in)
            with m.Else():
                m.d.sync += self.data_out.eq(mem[self.addr[:self.n_bits]])
        return m

class FakeSinglePortRamTest(unittest.TestCase):

    def setUp(self):
        m = Module()
        m.submodules.ram = self.ram = FakeSinglePortRam()
        self.sim = Simulator(m)
        self.sim.add_clock(1) # 1Hz for simplicity of counting

    def run_sim(self, p):
        self.sim.add_sync_process(p)
        self.sim.run()
        #with self.sim.write_vcd("zz.vcd", "zz.gtkw"):
        #    self.sim.run()

    def test_write_read(self):
        r = self.ram
        def process():
            yield r.cs.eq(1)
            yield r.addr.eq(5)
            yield r.data_in.eq(0x1234)
            yield r.wren.eq(1)
            yield # Writes ram[5]=0x1234

            yield r.addr.eq(25)
            yield r.data_in.eq(0x5678)
            yield # Writes ram[25]=0x5678

            yield r.addr.eq(5)
            yield r.wren.eq(0)
            yield # Command to read ram[5]
            self.assertEqual(0, (yield r.data_out)) # Should be zero until read completes
            yield # Command completes
            self.assertEqual(0x1234, (yield r.data_out))
        self.run_sim(process)

    def test_cs(self):
        r = self.ram
        def process():
            yield r.cs.eq(1)
            yield r.addr.eq(10)
            yield r.data_in.eq(0x1234)
            yield r.wren.eq(1)
            yield # Writes ram[10]=0x1234

            yield r.cs.eq(0)
            yield r.addr.eq(11)
            yield r.data_in.eq(0x1234)
            yield r.wren.eq(1)
            yield # DOES NOT write ram[11]=0x1234

            yield r.cs.eq(1)
            yield r.wren.eq(0)
            yield r.addr.eq(10)
            yield # Command to read ram[10]
            yield
            self.assertEqual(0x1234, (yield r.data_out))

            yield r.cs.eq(0)
            yield r.wren.eq(0)
            yield r.addr.eq(10)
            yield # Does not read ram[10]
            yield
            self.assertEqual(0, (yield r.data_out))

            yield r.cs.eq(1)
            yield r.wren.eq(0)
            yield r.addr.eq(11)
            yield # Command to read ram[11], which is empty
            yield
            self.assertEqual(0, (yield r.data_out))

            self.assertEqual(0, (yield r.data_out)) # Should be zero until read completes
            yield # Command completes
        self.run_sim(process)


class RamBank(Elaboratable):
    """A single RAM Bank, constructed from four smaller RAMs"""
    def __init__(self, fake=False):
        self.addr = Signal(16)
        self.data_in = Signal(16)
        self.wren = Signal()
        self.data_out = Signal(16)
        ram_class = FakeSinglePortRam if fake else SinglePortRam 
        self.rams = [ram_class() for _ in range(4)]

    def elaborate(self, platform):
        m = Module()
        r = self.rams
        for i in range(4):
            m.submodules[f"bank{i}"] = r[i]
            m.d.comb += [
                    r[i].addr.eq(self.addr[0:14]),
                    r[i].data_in.eq(self.data_in),
                    r[i].wren.eq(self.wren & (self.addr[14:16] == i)),
                    r[i].cs.eq(1),
            ]
        m.d.comb += self.data_out.eq(
                Array(self.rams)[self.addr[14:16]].data_out)
        return m


class FakeRamBankTest(unittest.TestCase):
    def setUp(self):
        m = Module()
        m.submodules.ram = self.ram = RamBank(True)
        self.sim = Simulator(m)
        self.sim.add_clock(1) # 1Hz for simplicity of counting

    def run_sim(self, p):
        self.sim.add_sync_process(p)
        #self.sim.run()
        with self.sim.write_vcd("zz.vcd", "zz.gtkw"):
            self.sim.run()

    def test(self):
        r = self.ram
        def read(addr):
            yield r.addr.eq(addr)
            yield r.wren.eq(0)
            yield 
            yield

        def write(addr, val):
            yield r.addr.eq(addr)
            yield r.data_in.eq(val)
            yield r.wren.eq(1)
            yield
            yield

        def process():
            yield from write(0x0010, 0x1111)
            yield from read(0x0010)
            self.assertEqual(0x1111, (yield r.data_out))
            yield from write(0x4010, 0x2222)
            yield from read(0x4010)
            self.assertEqual(0x2222, (yield r.data_out))
            yield from write(0xc010, 0xffff)
            yield from read(0xc010)
            self.assertEqual(0xffff, (yield r.data_out))
            yield from read(0x0010)
            self.assertEqual(0x1111, (yield r.data_out))

        self.run_sim(process)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-g', '--generate', action='store_true', help='Generate Verilog for oscilator')
    args = parser.parse_args()

    if args.generate:
        from nmigen_boards.icebreaker import ICEBreakerPlatform
        print(verilog.convert(SinglePortRam(), platform=ICEBreakerPlatform()))
    else:
        unittest.main()

