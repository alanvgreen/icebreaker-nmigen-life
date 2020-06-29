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

"""Writes 1-d automata to a double buffer
"""
from double_buffer import DoubleBuffer
from elab import SimulationTestCase
from lfsr import Lfsr, LfsrConfig
from oned_rules import Calc1DWord, Rules1D, Rules1DConfig, InitStyle
from util import to_words
from video_config import RESOLUTIONS
from writer import WriterBase

from nmigen import *
from nmigen.back.pysim import Simulator, Settle
from nmigen.utils import bits_for

import unittest


class OneDWriter(WriterBase):
    """Writes 1D automata to a double buffer"""
    def __init__(self, resolution, db, rules_config):
        super().__init__(resolution, db)
        self.rules = Rules1D(resolution.horizontal.active, rules_config)
        self.calc = Calc1DWord(self.rules)

        # These signals are used to coordinate various FSMs. They are pulsed
        # high in the comb domain, and we rely on their default value being 0.
        self.line0_start = Signal()
        self.line_start = Signal()
        self.line_end = Signal()

    def make_mem(self, m, name, init=None):
        """Makes a memory that can hold a lineful of words.
        """
        mem = Memory(width=16, depth=self.words_per_line, init=init)
        m.submodules['rp_' + name] = rp = mem.read_port(transparent=False)
        m.submodules['wp_' + name] = wp = mem.write_port()
        m.d.sync += wp.en.eq(0)
        return rp, wp

    def write_mem(self, m, write_port, addr, data):
        """Writes to an address in a memory."""
        m.d.sync += [
            write_port.addr.eq(addr),
            write_port.data.eq(data),
            write_port.en.eq(1)
        ]

    def do_line0_fsm(self, m):
        """Defines an FSM to output line zero
           Outputs from save mem, and copies to scratch mem, ready for calculation.
           Starts outputing when line0_start goes high.
           Pulses line_end when finished.
        """
        with m.FSM() as line_0:
            with m.State("WAIT"):
                with m.If(self.line0_start):
                    # Set up read for word 0
                    m.d.comb += self.save_rp.addr.eq(0)
                    m.next = "WRITE_DATA"
            with m.State("WRITE_DATA"):
                # Output read data
                self.db_write_word(m, self.save_rp.data)
                # Copy read data to scratch memory
                self.write_mem(m, self.scratch_wp, self.h_count, self.save_rp.data)
                # Set up read for next word
                m.d.comb += self.save_rp.addr.eq(self.h_count + 1)
                self.increment_counts(m, on_end="WRITE_TAG")
            with m.State("WRITE_TAG"):
                # Output row tag for line 0
                self.db_write_tag(m)
                m.next = "FINISHED"
            with m.State("FINISHED"):
                m.d.comb += self.line_end.eq(1)
                m.next = "WAIT"

    def do_line_fsm(self, m):
        """Defines an FSM to output a regular line.
           Reads from scratch memory:
            - calculates output
            - writes output to double buffer
            - writes output back to scratch memory
            - saves outtput when appropriate
           Starts outputing when line_start goes high.
           Pulses line_end when finished.
        """
        last_bit_last_word = Signal()
        first_bit_first_word = Signal()
        curr_word = Signal(16)

        with m.FSM() as line:
            with m.State("WAIT"):
                with m.If(self.line_start):
                    # Set up read for last word
                    m.d.comb += self.scratch_rp.addr.eq(self.words_per_line - 1)
                    m.next = "FETCH_LAST"

            with m.State("FETCH_LAST"):
                # Fetch left bit of input (last bit of last word of previous line)
                m.d.sync += last_bit_last_word.eq(self.scratch_rp.data[15])
                # Set up to read first word
                m.d.comb += self.scratch_rp.addr.eq(0)
                m.next = "FETCH_FIRST"

            with m.State("FETCH_FIRST"):
                m.d.sync += curr_word.eq(self.scratch_rp.data)
                m.d.sync += first_bit_first_word.eq(self.scratch_rp.data[0])
                # Set up read for second word
                m.d.comb += self.scratch_rp.addr.eq(1)
                m.next = "WRITE"

            with m.State("WRITE"):
                # Input data to calc to get output 
                m.d.comb += [
                    self.calc.input[0].eq(last_bit_last_word),
                    self.calc.input[1:17].eq(curr_word),
                    self.calc.input[17].eq(Mux(self.is_on_last_word(),
                        first_bit_first_word, self.scratch_rp.data[0]))
                ]
                # Write output to db, to scratch and to save
                self.db_write_word(m, self.calc.output)
                self.write_mem(m, self.scratch_wp, self.h_count, self.calc.output)
                with m.If(self.v_count == self.rules.speed):
                    self.write_mem(m, self.save_wp, self.h_count, self.calc.output)

                # Shift data along
                m.d.sync += [
                        last_bit_last_word.eq(curr_word[15]),
                        curr_word.eq(self.scratch_rp.data)
                ]

                # Set up for next cycle
                m.d.comb += self.scratch_rp.addr.eq(self.h_count + 2)
                self.increment_counts(m, on_end="WRITE_TAG")

            with m.State("WRITE_TAG"):
                # Output row tag 
                self.db_write_tag(m)
                m.next = "FINISHED"

            with m.State("FINISHED"):
                m.d.comb += self.line_end.eq(1)
                m.next = "WAIT"

    def elaborate(self, platform):
        m = Module()
        m.submodules.calc = self.calc

        # Use one memory each for scratch and save. 
        self.save_rp, self.save_wp = self.make_mem(m, 'save',
                init=to_words(self.rules.initdata()))
        self.scratch_rp, self.scratch_wp = self.make_mem(m, 'scratch')

        self.do_line0_fsm(m)
        self.do_line_fsm(m)

        # Wait for double buffer flip, and start either line 0 or regular line processing
        with m.FSM() as fsm:
            with m.State("WAIT_START"):
                with m.If(self.db.ready):
                    with m.If(self.v_count == 0):
                        m.d.comb += self.line0_start.eq(1)
                    with m.Else():
                        m.d.comb += self.line_start.eq(1)
                    m.next = "WAIT_END"
            with m.State("WAIT_END"):
                with m.If(self.line_end):
                    m.next = "WAIT_START"

        return m


class OneDWriterTest(SimulationTestCase):
    def setUp(self):
        res = RESOLUTIONS['TESTBIG']
        db = DoubleBuffer(res.words_per_line + 1,
                read_domain='sync', write_domain='sync')
        self.add(db, 'db')
        self.read = db.read
        config = Rules1DConfig(30, InitStyle.SINGLE, 5)
        self.rules = Rules1D(res.horizontal.active, config)
        onedw = OneDWriter(res, db.write, config)
        self.add(onedw, 'onedw')

    def check_row(self, tag, bits):
        def check_value(expected):
            actual = yield self.read.data
            #if (actual != expected): breakpoint()
            self.assertEqual(actual, expected)
            yield from self.toggle(self.read.next)
            yield
        yield from self.toggle(self.read.toggle)
        yield
        words = to_words(bits)
        for n, val in enumerate(words):
            yield from check_value(val)
        yield from check_value(tag)
        for i in range(34): yield # Give the writer a bit of time

    def test_write_read(self):
        num_frames = 3
        def reader():
            yield
            yield
            yield from self.toggle(self.read.toggle)
            for i in range(100): yield # Give the writer a bit of time
            saved = self.rules.initdata()
            for frame in range(num_frames):
                expected = saved
                for row in range(44):
                    #print(f'f:{frame} r:{row:2d}, {"".join(str(int(i)) for i in expected)}')
                    yield from self.check_row(row==0, expected)
                    if row == self.rules.speed:
                        saved = expected
                    expected = self.rules.eval(expected)

        self.run_sim(reader, write_trace=False)


if __name__ == '__main__':
        unittest.main()
