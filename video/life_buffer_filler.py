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

from elab import SimpleElaboratable, SimulationTestCase
from life_data_buffer import LifeDataBufferWrite

from enum import IntEnum
import unittest


class LifeBufferFillerMode(IntEnum):
    """The buffer filler can operate in several modes."""
    # reset RAM addresses, pre-fill buffer for calculating first line, save first line for later use
    FIRST = 0 
    # normal mode - fill one line from RAM, increment addresses
    MIDDLE = 1
    # For final line of screen, use saved first line for wrap-around
    LAST = 2 


class LifeBufferFillerControl(object):
    """Control interface for the LifeBufferFiller."""
    def __init__(self):
        self.start = Signal(1) # Input: toggle to start processing
        self.mode = Signal(LifeBufferFillerMode) # Input: mode of operation to start
        self.finished = Signal(1) # Output: toggle indicatesfilling is finished


class LifeBufferFillerRam(object):
    """Interface to RAM - should be connected to RAM prior to start of processing"""
    def __init__(self):
        # Output, data available one cycle later
        self.addr = Signal(16)
        # Input: data at address specified last cycle
        self.data = Signal(16)
    

class LifeBufferFiller(SimpleElaboratable):
    """Fills a LifeDataBuffer from RAM."""
    def __init__(self, life_data_buffer_write, words_per_line, total_words):
        self.control = LifeBufferFillerControl()
        self.ram = LifeBufferFillerRam()
        self.write = life_data_buffer_write
        self.words_per_line = words_per_line
        self.total_words = total_words

        # Internal, for line handling FSM
        self.begin_line = Signal() # input
        self.ended_line = Signal() # output

    def build_line_fsm(self, m):
        # Write one line to the LifeDataBuffer
        # Increments self.ram.addr pointer.
        # Toggles 'next' to buffer before writing

        # Always plumb read RAM data into write data
        m.d.comb += self.write.data.eq(self.ram.data)

        # Begin line always resets to zero unless told otherwise
        m.d.sync += self.begin_line.eq(0)

        with m.FSM() as one:
            with m.State("BEGIN"):
                with m.If(self.begin_line):
                    m.d.comb += self.write.next.eq(1) # toggle next
                    m.next = "WAIT_1"
            with m.State("WAIT_1"):
                # Wait 1 cycle for first RAM data to be returned
                m.d.sync += [
                    self.write.addr.eq(0),
                    self.ram.addr.eq(self.ram.addr+1),
                ]
                m.next = "WORKING"
            with m.State("WORKING"):
                m.d.comb += self.write.en.eq(1),
                m.d.sync += self.write.addr.eq(self.write.addr+1)

                with m.If(self.write.addr == self.words_per_line - 1):
                    m.d.comb += self.ended_line.eq(1)
                    m.next = "BEGIN"
                with m.Else():
                    m.d.sync += self.ram.addr.eq(self.ram.addr+1)


    def handle_first(self, m):
        # We are in first mode - read last line, first line and second line, saving first line
        with m.FSM() as first:
            with m.State("INIT"):
                m.d.sync += self.ram.addr.eq(self.total_words - self.words_per_line)
                m.d.sync += self.begin_line.eq(1)
                m.next = "READ_LAST_LINE"
            with m.State("READ_LAST_LINE"):
                with m.If(self.ended_line):
                    m.d.sync += [
                            self.ram.addr.eq(0),
                            self.write.save.eq(1),
                    ]
                    m.d.sync += self.begin_line.eq(1)
                    m.next = "READ_FIRST_LINE"
            with m.State("READ_FIRST_LINE"):
                with m.If(self.ended_line):
                    m.d.sync += self.write.save.eq(0)
                    m.d.sync += self.begin_line.eq(1)
                    m.next = "READ_SECOND_LINE"
            with m.State("READ_SECOND_LINE"):
                with m.If(self.ended_line):
                    m.d.comb += self.control.finished.eq(1)
                    m.next = "INIT"

    def handle_middle(self, m):
        # Kick of a vanilla line read
        with m.FSM() as middle:
            with m.State("INIT"):
                m.d.sync += self.begin_line.eq(1)
                m.next = "READ"
            with m.State("READ"):
                with m.If(self.ended_line):
                    m.d.comb += self.control.finished.eq(1)
                    m.next = "INIT"

    def handle_last(self, m):
        # Just toggle next without reading data - on reading side, reader will use saved data
        m.d.comb += self.write.next.eq(1)
        m.d.comb += self.control.finished.eq(1)

    def elab(self, m):
        # Define an FSM for reading all the data
        self.build_line_fsm(m)

        # This FSM handles state
        with m.FSM() as main:
            with m.State("WAIT"):
                with m.If(self.control.start):
                    with m.Switch(self.control.mode):
                        with m.Case(LifeBufferFillerMode.FIRST): m.next = "FIRST"
                        with m.Case(LifeBufferFillerMode.MIDDLE): m.next = "MIDDLE"
                        with m.Default(): m.next = "LAST"
            with m.State("FIRST"):
                self.handle_first(m)
                with m.If(self.control.finished):
                    m.next = "WAIT"
            with m.State("MIDDLE"):
                self.handle_middle(m)
                with m.If(self.control.finished):
                    m.next = "WAIT"
            with m.State("LAST"):
                self.handle_last(m)
                with m.If(self.control.finished):
                    m.next = "WAIT"


class LifeBufferFillerTest(SimulationTestCase):
    def setUp(self):
        self.write = LifeDataBufferWrite()
        self.bf = LifeBufferFiller(self.write, words_per_line=4, total_words=20)
        self.add(self.bf, 'bf')
        self.extra_processes += [self.ram_sim, self.buf_recorder]
        self.reset_buf_record()

    def reset_buf_record(self):
        class Record:
            def __init__(self):
                self.write_count = 0
                self.written_data = [] # new array added every time next toggled
                self.saved = [-1] * 4 # overwritten while saving
        self.buf_record = Record()

    def buf_recorder(self):
        # Record LifeDataBuffer writes
        yield Passive()
        while True:
            next = yield self.write.next
            addr = yield self.write.addr
            data = yield self.write.data
            en = yield self.write.en
            save = yield self.write.save
            rec = self.buf_record
            curr_data = rec.written_data[-1] if rec.written_data else None
            if next:
                rec.written_data.append([-1, -1, -1, -1])
            if en:
                rec.write_count += 1
                curr_data[addr] = data
                if save:
                    rec.saved[addr] = data
            yield

    def check_buf(self, write_count, data, saved):
        rec = self.buf_record
        self.assertEqual(rec.write_count, write_count)
        self.assertEqual(rec.written_data, data)
        self.assertEqual(rec.saved, saved)

    def ram_sim(self):
        # Simulate a ram full of constants
        yield Passive()
        while True:
            addr = yield self.bf.ram.addr
            yield self.bf.ram.data.eq(addr * 0x10)
            yield

    def run_mode(self, mode):
        # run the filler once, in the given mode
        yield self.bf.control.mode.eq(mode)
        yield self.bf.control.start.eq(1)
        yield
        while not (yield self.bf.control.finished):
            yield self.bf.control.start.eq(0)
            yield

    def test_first(self):
        def process():
            yield from self.run_mode(LifeBufferFillerMode.FIRST)
        self.run_sim(process)
        self.check_buf(12,
                [
                    [0x100, 0x110, 0x120, 0x130],
                    [0x000, 0x010, 0x020, 0x030],
                    [0x040, 0x050, 0x060, 0x070]
                ],
                [0x000, 0x010, 0x020, 0x030])

    def test_full_cycle(self):
        def process():
            yield from self.run_mode(LifeBufferFillerMode.FIRST)
            yield from self.run_mode(LifeBufferFillerMode.MIDDLE)
            yield from self.run_mode(LifeBufferFillerMode.MIDDLE)
            yield from self.run_mode(LifeBufferFillerMode.MIDDLE)
            yield from self.run_mode(LifeBufferFillerMode.LAST)
        self.run_sim(process)
        self.check_buf(24, 
                [
                    [0x100, 0x110, 0x120, 0x130],
                    [0x000, 0x010, 0x020, 0x030],
                    [0x040, 0x050, 0x060, 0x070],
                    [0x080, 0x090, 0x0a0, 0x0b0],
                    [0x0c0, 0x0d0, 0x0e0, 0x0f0],
                    [0x100, 0x110, 0x120, 0x130],
                    [-1, -1, -1, -1],
                ],
                [0x000, 0x010, 0x020, 0x030])

    def test_two_full_cycles(self):
        def process():
            yield from self.run_mode(LifeBufferFillerMode.FIRST)
            yield from self.run_mode(LifeBufferFillerMode.MIDDLE)
            yield from self.run_mode(LifeBufferFillerMode.MIDDLE)
            yield from self.run_mode(LifeBufferFillerMode.MIDDLE)
            yield from self.run_mode(LifeBufferFillerMode.LAST)
            yield from self.run_mode(LifeBufferFillerMode.FIRST)
            yield from self.run_mode(LifeBufferFillerMode.MIDDLE)
            yield from self.run_mode(LifeBufferFillerMode.MIDDLE)
            yield from self.run_mode(LifeBufferFillerMode.MIDDLE)
            yield from self.run_mode(LifeBufferFillerMode.LAST)
        self.run_sim(process)
        self.check_buf(48, 
                [
                    [0x100, 0x110, 0x120, 0x130],
                    [0x000, 0x010, 0x020, 0x030],
                    [0x040, 0x050, 0x060, 0x070],
                    [0x080, 0x090, 0x0a0, 0x0b0],
                    [0x0c0, 0x0d0, 0x0e0, 0x0f0],
                    [0x100, 0x110, 0x120, 0x130],
                    [-1, -1, -1, -1],
                    [0x100, 0x110, 0x120, 0x130],
                    [0x000, 0x010, 0x020, 0x030],
                    [0x040, 0x050, 0x060, 0x070],
                    [0x080, 0x090, 0x0a0, 0x0b0],
                    [0x0c0, 0x0d0, 0x0e0, 0x0f0],
                    [0x100, 0x110, 0x120, 0x130],
                    [-1, -1, -1, -1],
                ],
                [0x000, 0x010, 0x020, 0x030])

if __name__ == '__main__':
    unittest.main()
