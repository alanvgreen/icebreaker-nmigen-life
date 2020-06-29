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

"""Demo class - writes squares in checkerboard pattern
"""
from double_buffer import DoubleBuffer
from elab import SimulationTestCase
from lfsr import Lfsr, LfsrConfig
from writer import WriterBase
from video_config import RESOLUTIONS

from nmigen import *
from nmigen.hdl.ast import Stable
from nmigen.back.pysim import Simulator
from nmigen.utils import bits_for

import unittest

class SquareWriter(WriterBase):
    """Writes squares to a double buffer"""
    def __init__(self, resolution, db, size=2):
        super().__init__(resolution, db)
        self.size = size

    def elaborate(self, platform):
        m = Module()

        # Chequer pattern
        pattern = Mux(self.h_count[self.size] ^ self.v_count[4+self.size], 0xffff, 0)

        with m.FSM() as fsm:
            with m.State("WAIT_TOGGLE"):
                # Begin: wait for pointer to toggle
                with m.If(self.db.ready):
                    m.next = "WRITE_DATA"
            with m.State("WRITE_DATA"):
                # Output pattern and increment to end
                self.db_write_word(m, pattern)
                self.increment_counts(m, on_end="WRITE_TAG")
            with m.State("WRITE_TAG"):
                # Output row tag
                self.db_write_tag(m)
                m.next = "WAIT_TOGGLE"
        return m


class SquareWriterTest(SimulationTestCase):
    def setUp(self):
        res = RESOLUTIONS['TESTBIG']
        db = DoubleBuffer(res.words_per_line + 1, read_domain='sync', write_domain='sync')
        sw = SquareWriter(res, db.write, size=0)
        self.read = db.read
        self.add(db, 'db')
        self.add(sw, 'sw')

    def check_row(self, vals):
        yield from self.toggle(self.read.toggle) # Start read new buffer
        yield
        for n, val in enumerate(vals):
            #print(f'check {n}={val}')
            self.assertEqual((yield self.read.data), val)
            yield from self.toggle(self.read.next)
            yield

    def test_write_read(self):
        num_frames = 5
        def reader():
            # Warm up, toggle pointer, etc
            for i in range(20): yield
            yield from self.toggle(self.read.toggle) # Start read new buffer
            for i in range(200): yield

            for frame in range(num_frames):
                #print(f'frame={frame}/{num_frames}')
                for row in range(44):
                    #print(f'row={row}')
                    pat0 = [0x0000, 0xffff, 0x0000, 0xffff]
                    pat1 = [0xffff, 0x0000, 0xffff, 0x0000]
                    pat = pat1 if (row & 0x10) else pat0
                    yield from self.check_row([*(pat), row==0])
        self.run_sim(reader)

if __name__ == '__main__':
        unittest.main()
