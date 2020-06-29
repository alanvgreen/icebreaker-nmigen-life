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
from nmigen.back.pysim import Simulator, Passive
from nmigen.utils import bits_for

from double_buffer import DoubleBuffer
from elab import SimpleElaboratable, SimulationTestCase
from life_buffer_filler import LifeBufferFiller, LifeBufferFillerMode
from life_buffer_reader import LifeBufferReader
from life_data_buffer import LifeDataBuffer, build_memories
from life_rules import life_row, CalcLifeWord
from spram import RamBank
from util import all_bits_list, flatten_list, to_number, to_words
from video_config import RESOLUTIONS
from writer import WriterBase

from enum import IntEnum
import random
import unittest


class LifeWriter(WriterBase):
    """Writes Life to a double buffer"""
    def __init__(self, resolution, db, filler_control, filler_ram, reader_interface, *, fake_ram=False):
        super().__init__(resolution, db)
        self.ram = RamBank(fake_ram)

        wpl = resolution.words_per_line
        self.total_words = resolution.total_words

        self.filler = filler_control
        self.filler_ram = filler_ram

        self.reader = reader_interface

        self.calc = CalcLifeWord()

        self.rng_in = Signal(16) # input
        self.rng_enable = Signal() # output

    def connect_submodules(self, m):
        m.submodules.ram = self.ram
        m.submodules.calc = self.calc
        for i in range(3):
            m.d.comb += self.calc.input[i].eq(self.reader.life_data[i])

    def calc_filler_mode(self):
        return Mux(self.v_count == 0, LifeBufferFillerMode.FIRST, 
                Mux(self.is_on_last_line(), LifeBufferFillerMode.LAST, 
                    LifeBufferFillerMode.MIDDLE))

    def elaborate(self, platform):
        m = Module()
        self.connect_submodules(m)
        m.d.comb += self.reader.last.eq(self.is_on_last_line())
        led_r = platform.request("led_r", 0) if platform else None
        led_g = platform.request("led_g", 0) if platform else None

        write_addr = Signal(16)

        with m.FSM() as fsm:
            # Wait for double buffer flip, and start fetch
            with m.State("WAIT_START"):
                with m.If(self.db.ready):
                    m.d.sync += [
                            self.filler.mode.eq(self.calc_filler_mode()),
                            self.filler.start.eq(1),
                    ]
                    m.next = "FILL"
            with m.State("FILL"):
                # fill buffer
                m.d.sync += self.filler.start.eq(0)
                m.d.comb += [
                        self.ram.addr.eq(self.filler_ram.addr),
                        self.filler_ram.data.eq(self.ram.data_out),
                ]
                if led_r is not None and led_g is not None:
                    m.d.comb += [
                            led_r.eq(self.filler_ram.data == 0),
                            led_g.eq(self.filler_ram.data != 0),
                    ]
                with m.If(self.filler.finished):
                    m.d.sync += self.reader.begin.eq(1)
                    m.next = "PROCESS"
            with m.State("PROCESS"):
                m.d.sync += self.reader.begin.eq(0)
                # Read from line buffer, calculate, output and write to RAM
                # Get a value to output
                # Uses reader timing to count words, no matter what is displayed
                with m.If(self.reader.valid):
                    # Calculate an output value
                    val = Signal(16)
                    with m.If(self.f_count[:12] == 0):
                        m.d.comb += val.eq(self.rng_in)
                        m.d.comb += self.rng_enable.eq(1)
                    with m.Else():
                        m.d.comb += val.eq(self.calc.output)
                    self.db_write_word(m, val)

                    # Tell RAM to write data
                    m.d.comb += [
                        self.ram.addr.eq(write_addr),
                        self.ram.wren.eq(1),
                        self.ram.data_in.eq(val)
                    ]

                    # Increment RAM address
                    m.d.sync += write_addr.eq(write_addr + 1)
                    with m.If(write_addr == self.total_words - 1):
                        m.d.sync += write_addr.eq(0)

                    # Increment pixel counts, and when finished a line, write the tag
                    self.increment_counts(m, on_end="WRITE_TAG")

            with m.State("WRITE_TAG"):
                # Write tag to output
                self.db_write_tag(m)
                m.next = "WAIT_START"

        return m


class LifeWriterTest(SimulationTestCase):
    def setUp(self):
        # Set up simulation
        self.res = RESOLUTIONS['TESTBIG']
        wpl = self.res.words_per_line
        db = DoubleBuffer(wpl + 1, read_domain='sync', write_domain='sync')
        self.add(db, 'db')
        self.db_read = db.read

        read_ports, write_ports = build_memories(self.m, wpl)
        ldbuf = LifeDataBuffer(read_ports, write_ports)
        self.add(ldbuf, 'ldbuf')
        filler = LifeBufferFiller(ldbuf.write, wpl, self.res.total_words)
        self.add(filler, 'filler')
        ldreader = LifeBufferReader(wpl, ldbuf.read)
        self.add(ldreader, 'ldreader')

        self.lw = LifeWriter(self.res, db.write, filler.control,
                filler.ram, ldreader.interface, fake_ram=True)
        self.add(self.lw, 'lw')

        # Make a list of random numbers for rng, same size as frame
        random.seed(0)
        self.rng_data = [
                [random.randrange(65536) for _ in range(self.res.words_per_line)]
                for _ in range(self.res.vertical.active)]
        self.extra_processes.append(self.rng_process)

    def rng_process(self):
        yield Passive()
        # Set new data whenever enable is set
        for word in flatten_list(self.rng_data):
            yield self.lw.rng_in.eq(word)
            yield
            while not (yield self.lw.rng_enable):
                yield

        yield # Allow one more enable
        # That's all the data we have
        while not (yield self.lw.rng_enable):
            yield
        fail("Requested more random numbers than expected")

    def check_row(self, frame, row, tag, words):
        def check_value(expected):
            actual = yield self.db_read.data
            if (actual != expected):
                print(f"frame, row = {frame}, {row:02x}: {actual:05x} != {expected:05x}")
                #breakpoint()
            self.assertEqual(actual, expected)
            yield from self.toggle(self.db_read.next)
            yield
        yield from self.toggle(self.db_read.toggle)
        yield
        for n, val in enumerate(words):
            yield from check_value(val)
        yield from check_value(tag)
        for i in range(34): yield # Give the writer a bit of time

    def calc_next(self, expected, i):
        def bits_from(row):
            l = all_bits_list(row)
            return [l[-1]] + l + [l[0]]
        a = bits_from(expected[i-1])
        b = bits_from(expected[i])
        c = bits_from(expected[(i+1)%(self.res.vertical.active)])
        result = life_row(a, b, c)
        return to_words(result)

    def test_run(self):
        # reads the double buffer
        num_frames = 3
        def reader():
            yield
            yield
            yield from self.toggle(self.db_read.toggle)
            for i in range(30): yield # Give the writer a bit of time
            expected = self.rng_data
            expected_next = [None] * len(expected)
            wpl = self.res.words_per_line
            for f in range(num_frames):
                for i in range(0, self.res.vertical.active):
                    #if f == 1: breakpoint()
                    yield from self.check_row(f, i, i==0, expected[i])
                    expected_next[i] = self.calc_next(expected, i)
                expected = expected_next[:]

        self.run_sim(reader, write_trace=False)


if __name__ == '__main__':
        unittest.main()
