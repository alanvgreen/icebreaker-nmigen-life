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
from life_data_buffer import LifeDataBufferRead

from enum import IntEnum
import random
import unittest
from util import all_bits_list, to_number


class LifeBufferReaderInterface:
    """Control Interface for the LifeBufferReader"""
    def __init__(self):
        self.begin = Signal() # Input: begin reading
        self.last = Signal() # Input: processing last row
        self.ended = Signal() # Output: all data has been presented.
        self.valid = Signal() # Output: data is valid
        self.count = Signal(7) # Output: number of word being presented
        # Output: 3*18bit array for life calc word 
        self.life_data = [Signal(18, name=f"life_data_{i}") for i in range(3)]
        # Output: 16 bit word for video display
        self.curr_word = Signal(16) 


class LifeBufferReader(SimpleElaboratable):
    """Reads the 3-line buffer providing inputs to downstream processing.
        - one set of life_data - 3x18 bit words - for input to CalcLifeWord
        - one current word - for output to video
    """
    def __init__(self, words_per_line, life_data_buffer_read):
        self.words_per_line = words_per_line
        self.read = life_data_buffer_read
        self.interface = LifeBufferReaderInterface()

    def build_shift_registers(self, m):
        # Build the shift registers which run every cycle to shift data in from buffer
        shift_register = [Signal(17, name=f"sr_{i}") for i in range(3)]
        for ld, rd, sr in zip(self.interface.life_data, self.read.data, shift_register):
            # Output is content of shift register + high bit of read_addr
            m.d.comb += ld[17].eq(rd[0])
            m.d.comb += ld[:17].eq(sr)
            # Move SR along and shift in read_data for next cycle
            m.d.sync += sr[0].eq(sr[16])
            m.d.sync += sr[1:].eq(rd)

    def elab(self, m):
        self.build_shift_registers(m)
        m.d.comb += self.interface.curr_word.eq(self.interface.life_data[1][1:17])
        m.d.comb += self.read.saved.eq(self.interface.last)

        # we need to read words N-1, 0, 1, 2 ... N-1, 0 for a total of N+2 words
        with m.FSM() as fsm:
            with m.State("WAIT"):
                # Wait for begin signal
                # Count is at words_per_line - 2
                with m.If(self.interface.begin):
                    m.d.sync += self.read.addr.eq(self.words_per_line - 1)
                    m.d.sync += self.interface.count.eq(0)
                    m.next = "READ_N-1"
            with m.State("READ_N-1"):
                # Unknown word in data register. Reading N-1. Read word 0 next cycle.
                m.d.sync += self.read.addr.eq(0)
                m.next = "READ_0"
            with m.State("READ_0"):
                # N-1 in data register. Reading word 0. Read word 1 next cycle
                # Tee up word 1
                m.d.sync += self.read.addr.eq(1)
                m.next = "READ_1"
            with m.State("READ_1"):
                # 0 in data register, now reading word 1. Read word 2 next cycle
                m.d.sync += self.read.addr.eq(2)
                m.next = "LOOP"
            with m.State("LOOP"):
                # Stable state: Valid data. Keep asking for next data word until
                # read words N-1 and 0 for the second time
                m.d.comb += self.interface.valid.eq(1)
                count = self.interface.count
                m.d.sync += count.eq(count+1)
                with m.If(count == self.words_per_line-3):
                    m.d.sync += self.read.addr.eq(0)
                with m.Else():
                    m.d.sync += self.read.addr.eq(count+3)
                with m.If(count == self.words_per_line - 1):
                    m.next = "ENDED"
            with m.State("ENDED"):
                m.d.comb += self.interface.ended.eq(1)
                m.next = "WAIT"


class LifeBufferReaderTest(SimulationTestCase):
    def setUp(self):
        self.read = LifeDataBufferRead()
        self.lbr = LifeBufferReader(8, self.read)
        self.add(self.lbr)
        self.extra_processes += [self.buf_sim]
        self.generate_data() # Ensure some data exists

    def generate_data(self, seed=1):
        # Data is of the form of 3 lists of 8 elements
        random.seed(seed)
        self.data_words = [[random.randrange(65536) for _ in range(8)] for _ in range(3)]
        self.data_bits = [all_bits_list(l) for l in self.data_words]

    def buf_sim(self):
        yield Passive()
        while True:
            addr = yield self.read.addr
            for i in range(3):
                yield self.read.data[i].eq(self.data_words[i][addr%8])
            yield

    def check_life_data(self, addr):
        for i in range(3):
            expected = to_number([
                    self.data_bits[i][addr * 16 - 1],
                    *self.data_bits[i][addr * 16 : (addr+1) * 16],
                    self.data_bits[i][((addr+1) * 16) % (8*16)]])
            actual = yield self.lbr.interface.life_data[i]
            if actual != expected:
                breakpoint()
            self.assertEqual(expected, actual)

    def test(self):
        lbr_if = self.lbr.interface
        num_cycles = 20
        def process():
            
            for cycle in range(num_cycles):
                self.generate_data(cycle)
                yield
                yield
                yield from self.toggle(lbr_if.begin)
                while not (yield lbr_if.valid):
                    yield
                for i in range(8):
                    self.assertTrue((yield lbr_if.valid))
                    self.assertEqual(i, (yield lbr_if.count))
                    self.assertEqual(self.data_words[1][i], (yield lbr_if.curr_word))
                    yield from self.check_life_data(i)
                    yield

                self.assertFalse((yield lbr_if.valid))
                self.assertTrue((yield lbr_if.ended))
                yield
                self.assertFalse((yield lbr_if.valid))
                self.assertFalse((yield lbr_if.ended))
                yield

        self.run_sim(process, write_trace=True )


if __name__ == '__main__':
    unittest.main()

