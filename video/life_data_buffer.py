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


from nmigen import *

from elab import SimpleElaboratable, SimulationTestCase

import random
import unittest


class LifeDataBufferWrite(object):
    """Write interface for LifeDataBuffer.
       Writes to last line of the LifeDataBuffer
    """
    def __init__(self):
        self.next = Signal() # Rotate buffers. Takes effect next cycle.
        self.addr = Signal(7, name='w_addr') # Address to write
        self.data = Signal(16, name='w_data') # Data to write at address
        self.en = Signal() # Write enable
        self.save = Signal() # When high, also save data as well as regular write

class LifeDataBufferRead(object):
    """Read interface for LifeDataBuffer.
       Simultaneously reads three lines of data.
    """
    def __init__(self):
        self.addr = Signal(7, name='r_addr') # Address to read. Data appears one cycle later
        self.data = [Signal(16, name=f'r_data{i}') for i in range(3)] # Data
        self.saved = Signal() # When high, last data replaced with saved data

class LifeDataBuffer(SimpleElaboratable):
    """Buffers words of cell data for the life simulation.
    
    A LifeDataBuffer provides simultaneous read access to three lines of data, up to
    128 16 bit words wide. New data can be written to the last of the 3 lines.
    When the "next" signal is enabled, the buffers rotate so the last line
    becomes the second, the second line becomes the first, and the first line becomes the last.

    The LifeDataBuffer's purpose is to provide words of pixel/cell data that
    will later be formatted for a LifeCalcWord module.

    A single line of data can be saved and later substituted as the last line.
    This is used to implement wrapping between bottom and top of the screen.

    This class is implemented with 4 16bitx128word memories.
    """
    def __init__(self, read_ports, write_ports):
        """Constructor.

        This class is implemented as interface to 4 memories which are read in parallel in various ways.
           
        :param read_ports: 4 memory read ports
        :param write_ports: 4 memory write ports corresponding to the read_ports
        """
        self.read_ports = read_ports
        self.write_ports = write_ports
        self.read = LifeDataBufferRead()
        self.write = LifeDataBufferWrite()

    def connect_addresses(self, m):
        # Wire up addresses - All 4 BRAMs share read and write addresses + write data
        for i in range(4):
            m.d.comb += [
                self.read_ports[i].addr.eq(self.read.addr),
                self.write_ports[i].addr.eq(self.write.addr),
                self.write_ports[i].data.eq(self.write.data),
            ]

    def handle_reads(self, m, pos):
        """Handle read interface when self.pos == pos, where pos is constant"""
        m.d.comb += self.read.data[0].eq(self.read_ports[(pos + 0) % 3].data)
        m.d.comb += self.read.data[1].eq(self.read_ports[(pos + 1) % 3].data)
        m.d.comb += self.read.data[2].eq(Mux(self.read.saved, 
            self.read_ports[3].data,
            self.read_ports[(pos + 2) % 3].data))

    def handle_writes(self, m, pos):
        """Handle write interface when self.pos == pos, where pos is constant"""
        with m.If(self.write.next):
            m.d.sync += self.pos.eq((pos + 1) % 3)

        with m.If(self.write.en):
            m.d.comb += self.write_ports[(pos + 2) % 3].en.eq(1)
            m.d.comb += self.write_ports[3].en.eq(self.write.save)

    def elab(self, m):
        # Current position in three buffers - range 0..2
        self.pos = Signal(2)
        self.connect_addresses(m)

        # Each value of pos causes buffers to be wired differently
        for p in range(3):
            with m.If(self.pos == p):
                self.handle_writes(m, p)
                self.handle_reads(m, p)


def build_memories(m, depth):
    """Builds memories suitable for use with the LifeDataBuffer.
        m - module to add the memories to
        depth - size of memory
        Returns a pair of lists: (read_ports, write_ports)
    """
    memories = [Memory(width=16, depth=128, name=f"line_buffer_{i}")
            for i in range(4)]
    read_ports = [mem.read_port(transparent=False) for mem in memories]
    for i, rp in enumerate(read_ports):
        m.submodules[f"ldb_read{i}"] = rp
    write_ports = [mem.write_port() for mem in memories]
    for i, wp in enumerate(write_ports):
        m.submodules[f"ldb_write{i}"] = wp
    return read_ports, write_ports


class LifeDataBufferTest(SimulationTestCase):
    def setUp(self):
        read_ports, write_ports = build_memories(self.m, 4)
        self.ldb = LifeDataBuffer(read_ports, write_ports)
        self.add(self.ldb)

    def write(self, addr, data):
        yield self.ldb.write.addr.eq(addr)
        yield self.ldb.write.data.eq(data)
        yield from self.toggle(self.ldb.write.en)

    def write_line(self, data):
        for i in range(4):
            yield from self.write(i, data[i])

    def check(self, addr, values):
        yield self.ldb.read.addr.eq(addr)
        yield # clock in new address
        yield # wait for data to be provided by memory
        for (data, value) in zip(self.ldb.read.data, values):
            self.assertEqual(value, (yield data))

    def check_lines(self, lines):
        for addr in range(4):
            values = [line[addr] for line in lines]
            yield from self.check(addr, values)

    def test_next(self):
        # Just working with addr 0, check that next works
        def process():
            # Write unique value into addr 0 of each line
            for i in range(3):
                yield from self.toggle(self.ldb.write.next)
                yield from self.write(0, i)

            # Read back, using next to rotate buffer
            yield from self.check(0, [0, 1, 2])
            yield from self.toggle(self.ldb.write.next)
            yield from self.check(0, [1, 2, 0])
            yield from self.toggle(self.ldb.write.next)
            yield from self.check(0, [2, 0, 1])
            yield from self.toggle(self.ldb.write.next)
            yield from self.check(0, [0, 1, 2])

        self.run_sim(process, write_trace=False)

    def test_random(self):
        # Write a bunch of random data, read it back
        num_lines = 20
        all_lines = [[random.randrange(65536) for _ in range(4)] for _ in range(num_lines)]
        def process():
            for line_no in range(num_lines):
                # Write data
                yield from self.toggle(self.ldb.write.next)
                yield from self.write_line(all_lines[line_no])

                # Check that is was as expected
                l0 = all_lines[line_no-2] if line_no >= 2 else [0, 0, 0, 0]
                l1 = all_lines[line_no-1] if line_no >= 1 else [0, 0, 0, 0]
                l2 = all_lines[line_no-0]
                yield from self.check_lines([l0, l1, l2])

        self.run_sim(process, write_trace=False)

    def test_save(self):
        # Write 4 lines, saving the first, then sub back in the first
        l0, l1, l2, l3 = [[random.randrange(65536) for _ in range(4)] for _ in range(4)]
        def process():
            yield self.ldb.write.save.eq(1)
            yield from self.write_line(l0)
            yield self.ldb.write.save.eq(0)
            yield from self.toggle(self.ldb.write.next)
            yield from self.write_line(l1)
            yield from self.toggle(self.ldb.write.next)
            yield from self.write_line(l2)
            yield from self.toggle(self.ldb.write.next)
            yield from self.write_line(l3)

            yield from self.check_lines([l1, l2, l3])
            yield self.ldb.read.saved.eq(1)
            yield
            yield from self.check_lines([l1, l2, l0])
            yield self.ldb.read.saved.eq(1)
            yield from self.toggle(self.ldb.write.next)
            yield from self.check_lines([l2, l3, l0])
            yield self.ldb.read.saved.eq(0)
            yield
            yield from self.check_lines([l2, l3, l1])

        self.run_sim(process, write_trace=True)

if __name__ == '__main__':
    unittest.main()
